"""
Dynamic Workload Arrival Simulator for GreenShift.

Position: Input boundary of GreenShift
Flow:
  WORKLOAD DATASET
        │
        ▼
  DynamicArrivalSimulator (submit_time, simulation clock, arrival queues)
        │
  Job Arrival Event
        │
        ▼
  EXISTING INGESTION PIPELINE (ingest_job in app.ingest.service)
        │
        ▼
  EXISTING DATABASE (JobORM)
        │
        ▼
  EXISTING DECIDE SCHEDULER (schedule_and_store in app.decide.service)
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.ingest.job_csv_loader import load_jobs_from_csv
from app.ingest.jobs import get_job
from app.ingest.service import ingest_job
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import JobORM, JobSubmitRequest
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Enums & Data Models
# ─────────────────────────────────────────────────────────────────────────────

class ArrivalJobState(str, enum.Enum):
    PENDING = "PENDING"                         # Waiting for clock to reach submit_time
    ARRIVED = "ARRIVED"                         # Clock reached submit_time; released
    SUBMITTED_TO_INGEST = "SUBMITTED_TO_INGEST" # Successfully ingested via ingest_job()
    FAILED_INGEST = "FAILED_INGEST"             # Ingestion threw an error for this job


@dataclass
class SimulationJobRecord:
    job_id: str
    submit_time: datetime
    state: ArrivalJobState
    job_dict: Dict[str, Any]
    is_backlog: bool = False
    released_at_sim_time: Optional[datetime] = None
    released_at_real_time: Optional[datetime] = None
    error_message: Optional[str] = None


class SimulationConfig(BaseModel):
    """Configuration for Dynamic Arrival Simulator."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataset_path: str = Field(
        default="data/greenshift_workloads_final.csv",
        description="Path to workload dataset CSV",
    )
    simulation_start_time: Optional[datetime] = Field(
        default=None,
        description="Simulation clock start time (UTC). If None, defaults to earliest submit_time in dataset",
    )
    simulation_speed: float = Field(
        default=60.0,
        description="Speed multiplier (e.g. 60.0 = 1 real sec is 60 sim sec). Set <= 0 for instantaneous discrete jumps",
    )
    step_size_seconds: float = Field(
        default=60.0,
        description="Simulated seconds advanced per clock step",
    )
    max_jobs: Optional[int] = Field(
        default=None,
        description="Maximum jobs to simulate (useful for testing / short demos)",
    )
    auto_schedule: bool = Field(
        default=True,
        description="Trigger existing DECIDE scheduler immediately upon ingestion",
    )
    reanchor_historical: bool = Field(
        default=True,
        description="Re-anchor historical deadlines to future to satisfy future deadline validations",
    )


class SimulationSummary(BaseModel):
    """Summary of a completed arrival simulation run."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    total_jobs: int
    jobs_released: int
    jobs_submitted_successfully: int
    jobs_failed: int
    backlog_jobs_count: int
    simulation_start_time: datetime
    simulation_end_time: datetime
    duration_real_seconds: float
    duration_simulated_seconds: float
    speed_multiplier: float
    released_job_ids: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Arrival Simulator Class
# ─────────────────────────────────────────────────────────────────────────────

class DynamicArrivalSimulator:
    """
    Modular Workload Arrival Simulator.

    Controls WHEN jobs enter GreenShift based on their submit_time,
    while delegating HOW jobs are ingested and scheduled to the existing
    ingest and decide services.
    """

    def __init__(
        self,
        config: Optional[SimulationConfig] = None,
        db: Optional[Session] = None,
        ingest_callback: Optional[Callable[[Session, JobSubmitRequest], JobORM]] = None,
    ):
        self.config = config or SimulationConfig()
        self._external_db = db
        self._ingest_callback = ingest_callback or ingest_job

        # State tracking
        self.jobs: List[SimulationJobRecord] = []
        self.simulation_start_time: datetime = datetime.now(timezone.utc)
        self.current_simulation_time: datetime = self.simulation_start_time
        self.is_initialized: bool = False
        self.is_running: bool = False
        self.is_completed: bool = False

        # Load and prepare jobs
        self.load_dataset()

    def load_dataset(self) -> int:
        """
        Load workload CSV, sort chronologically by submit_time with deterministic
        job_id tiebreaker, and initialize simulation clock and backlog queue.
        """
        valid_jobs, validation_errors = load_jobs_from_csv(
            self.config.dataset_path,
            reanchor_historical=self.config.reanchor_historical,
        )

        if validation_errors:
            logger.warning(
                "DynamicArrivalSimulator: %d validation errors during dataset load: %s",
                len(validation_errors),
                validation_errors[:5],
            )

        if not valid_jobs:
            logger.warning("DynamicArrivalSimulator: Dataset at %s yielded 0 valid jobs", self.config.dataset_path)
            self.jobs = []
            self.is_initialized = True
            return 0

        # Sort chronologically by submit_time (primary), job_id (secondary for determinism)
        def sort_key(j: dict) -> Tuple[datetime, str]:
            st = j.get("submit_time")
            if st is None:
                st = datetime.min.replace(tzinfo=timezone.utc)
            elif st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)
            return (st, j.get("job_id", ""))

        sorted_jobs = sorted(valid_jobs, key=sort_key)

        if self.config.max_jobs and self.config.max_jobs > 0:
            sorted_jobs = sorted_jobs[: self.config.max_jobs]

        # Determine simulation start time
        if self.config.simulation_start_time:
            sim_start = self.config.simulation_start_time
            if sim_start.tzinfo is None:
                sim_start = sim_start.replace(tzinfo=timezone.utc)
        else:
            first_submit = sorted_jobs[0].get("submit_time")
            if first_submit:
                sim_start = first_submit if first_submit.tzinfo else first_submit.replace(tzinfo=timezone.utc)
            else:
                sim_start = datetime.now(timezone.utc)

        self.simulation_start_time = sim_start
        self.current_simulation_time = sim_start

        # Create job records and classify backlog
        self.jobs = []
        backlog_count = 0
        for job_dict in sorted_jobs:
            st = job_dict.get("submit_time")
            if st is None:
                st = sim_start
            elif st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)

            is_backlog = (st <= self.simulation_start_time)
            if is_backlog:
                backlog_count += 1

            record = SimulationJobRecord(
                job_id=job_dict["job_id"],
                submit_time=st,
                state=ArrivalJobState.PENDING,
                job_dict=job_dict,
                is_backlog=is_backlog,
            )
            self.jobs.append(record)

        self.is_initialized = True
        logger.info(
            "DynamicArrivalSimulator initialized: %d total jobs (%d backlog at sim start %s)",
            len(self.jobs),
            backlog_count,
            self.simulation_start_time.isoformat(),
        )
        return len(self.jobs)

    @property
    def pending_jobs(self) -> List[SimulationJobRecord]:
        return [j for j in self.jobs if j.state == ArrivalJobState.PENDING]

    @property
    def released_jobs(self) -> List[SimulationJobRecord]:
        return [j for j in self.jobs if j.state != ArrivalJobState.PENDING]

    def _submit_to_ingest(self, db: Session, record: SimulationJobRecord) -> bool:
        """
        Build standard JobSubmitRequest and submit to existing ingest_job().
        Optionally trigger DECIDE scheduling if auto_schedule is enabled.
        """
        job_dict = record.job_dict
        try:
            request = JobSubmitRequest(
                job_id              = record.job_id,
                team_id             = job_dict.get("team_id", "unknown"),
                deadline            = job_dict["deadline"],
                runtime_minutes     = job_dict["runtime_minutes"],
                power_kw            = job_dict["power_kw"],
                region              = job_dict.get("region", "IN-TG"),
                container_image     = job_dict.get("container_image", "greenshift/sample-workload:latest"),
                cpu_request         = job_dict.get("cpu_request", "500m"),
                memory_request      = job_dict.get("memory_request", "512Mi"),
                carbon_budget_kg    = job_dict.get("carbon_budget_kg"),
                job_type            = job_dict.get("job_type"),
                priority            = job_dict.get("priority", "MEDIUM"),
                earliest_start_time = job_dict.get("earliest_start_time"),
                energy_kwh          = job_dict.get("energy_kwh"),
                deferrable          = job_dict.get("deferrable", True),
            )

            # Call existing ingestion pipeline
            job_orm = self._ingest_callback(db, request)
            logger.info("[INGEST] Job %s sent to existing ingestion pipeline", record.job_id)

            # Optionally trigger decide scheduling
            if self.config.auto_schedule:
                from app.decide.service import schedule_and_store
                schedule_and_store(db, job_orm)
                logger.info("[DECIDE] Job %s scheduled via existing Decide service", record.job_id)

            record.state = ArrivalJobState.SUBMITTED_TO_INGEST
            return True

        except Exception as exc:
            record.state = ArrivalJobState.FAILED_INGEST
            record.error_message = str(exc)
            logger.error("[INGEST_FAIL] Failed to ingest job %s: %s", record.job_id, exc)
            return False

    def step_to_time(self, target_sim_time: datetime, db: Optional[Session] = None) -> List[SimulationJobRecord]:
        """
        Advance simulation clock to target_sim_time and release all jobs whose
        submit_time <= target_sim_time.
        """
        if target_sim_time.tzinfo is None:
            target_sim_time = target_sim_time.replace(tzinfo=timezone.utc)

        self.current_simulation_time = target_sim_time
        arrived_this_step: List[SimulationJobRecord] = []

        # Find all pending jobs ready to be released
        ready_records = [
            j for j in self.jobs
            if j.state == ArrivalJobState.PENDING and j.submit_time <= self.current_simulation_time
        ]

        if not ready_records:
            return []

        session_provided = db is not None or self._external_db is not None
        active_db = db or self._external_db or SessionLocal()

        now_real = datetime.now(timezone.utc)

        try:
            for record in ready_records:
                record.state = ArrivalJobState.ARRIVED
                record.released_at_sim_time = self.current_simulation_time
                record.released_at_real_time = now_real

                backlog_tag = " [BACKLOG]" if record.is_backlog else ""
                logger.info(
                    "[ARRIVAL%s] Sim time: %s | Job %s arrived (submit_time: %s)",
                    backlog_tag,
                    self.current_simulation_time.strftime("%Y-%m-%d %H:%M:%S"),
                    record.job_id,
                    record.submit_time.strftime("%Y-%m-%d %H:%M:%S"),
                )

                # Send to existing ingest
                self._submit_to_ingest(active_db, record)
                arrived_this_step.append(record)

        finally:
            if not session_provided:
                active_db.close()

        return arrived_this_step

    def run(
        self,
        progress_callback: Optional[Callable[[datetime, List[SimulationJobRecord]], None]] = None,
        db: Optional[Session] = None,
    ) -> SimulationSummary:
        """
        Execute full dynamic arrival simulation until all jobs have arrived.

        Supports:
          - Accelerated sleep mode: simulation_speed > 0
          - Discrete jump mode: simulation_speed <= 0 (instantaneous progression)
        """
        if not self.jobs:
            logger.info("[SIMULATION] No jobs to simulate.")
            return SimulationSummary(
                total_jobs=0,
                jobs_released=0,
                jobs_submitted_successfully=0,
                jobs_failed=0,
                backlog_jobs_count=0,
                simulation_start_time=self.simulation_start_time,
                simulation_end_time=self.simulation_start_time,
                duration_real_seconds=0.0,
                duration_simulated_seconds=0.0,
                speed_multiplier=self.config.simulation_speed,
                released_job_ids=[],
            )

        self.is_running = True
        real_start_time = time.time()

        logger.info(
            "[SIMULATION] Started at sim_time=%s (Speed: %.1fx, Jobs: %d)",
            self.simulation_start_time.strftime("%Y-%m-%d %H:%M:%S"),
            self.config.simulation_speed,
            len(self.jobs),
        )

        session_provided = db is not None or self._external_db is not None
        active_db = db or self._external_db or SessionLocal()

        try:
            # 1. Release initial backlog at t = simulation_start_time
            initial_releases = self.step_to_time(self.simulation_start_time, db=active_db)
            if progress_callback and initial_releases:
                progress_callback(self.simulation_start_time, initial_releases)

            # 2. Progress clock event-driven until all jobs released
            while self.pending_jobs:
                next_job = self.pending_jobs[0]
                next_time = max(self.current_simulation_time, next_job.submit_time)

                if self.config.simulation_speed > 0:
                    sim_gap = (next_time - self.current_simulation_time).total_seconds()
                    if sim_gap > 0:
                        # Proportional sleep scaled by speed, capped at 1.0s per tick for snappy UX
                        sleep_duration = min(sim_gap / self.config.simulation_speed, 1.0)
                        if sleep_duration > 0.005:
                            time.sleep(sleep_duration)

                released = self.step_to_time(next_time, db=active_db)
                if progress_callback and released:
                    progress_callback(next_time, released)

            self.is_completed = True
            real_end_time = time.time()
            duration_real = round(real_end_time - real_start_time, 3)
            duration_sim = (self.current_simulation_time - self.simulation_start_time).total_seconds()

            succ_count = sum(1 for j in self.jobs if j.state == ArrivalJobState.SUBMITTED_TO_INGEST)
            fail_count = sum(1 for j in self.jobs if j.state == ArrivalJobState.FAILED_INGEST)
            backlog_count = sum(1 for j in self.jobs if j.is_backlog)

            summary = SimulationSummary(
                total_jobs=len(self.jobs),
                jobs_released=len(self.released_jobs),
                jobs_submitted_successfully=succ_count,
                jobs_failed=fail_count,
                backlog_jobs_count=backlog_count,
                simulation_start_time=self.simulation_start_time,
                simulation_end_time=self.current_simulation_time,
                duration_real_seconds=duration_real,
                duration_simulated_seconds=duration_sim,
                speed_multiplier=self.config.simulation_speed,
                released_job_ids=[j.job_id for j in self.jobs if j.state != ArrivalJobState.PENDING],
            )

            logger.info("[SIMULATION] Completed")
            logger.info("[SUMMARY]")
            logger.info("  Total jobs: %d", summary.total_jobs)
            logger.info("  Jobs released: %d (Backlog: %d)", summary.jobs_released, summary.backlog_jobs_count)
            logger.info("  Jobs successfully submitted to ingest: %d", summary.jobs_submitted_successfully)
            logger.info("  Jobs failed: %d", summary.jobs_failed)
            logger.info("  Real duration: %.2fs | Simulated duration: %.2fs (%.1fh)", duration_real, duration_sim, duration_sim/3600.0)

            return summary

        finally:
            self.is_running = False
            if not session_provided:
                active_db.close()


def run_dynamic_arrival_simulation(
    dataset_path: str = "data/greenshift_workloads_final.csv",
    speed: float = 60.0,
    max_jobs: Optional[int] = None,
    simulation_start_time: Optional[datetime] = None,
    db: Optional[Session] = None,
) -> SimulationSummary:
    """
    Convenience function to run a dynamic arrival simulation with standard configuration.
    """
    config = SimulationConfig(
        dataset_path=dataset_path,
        simulation_speed=speed,
        max_jobs=max_jobs,
        simulation_start_time=simulation_start_time,
    )
    sim = DynamicArrivalSimulator(config=config, db=db)
    return sim.run()
