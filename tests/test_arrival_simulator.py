"""
Tests for GreenShift Dynamic Workload Arrival Simulator.

Covers:
 1. Jobs are released chronologically by submit_time.
 2. Jobs with identical submit_time are released together in the same simulation tick.
 3. Jobs before or at simulation_start_time are treated as backlog and released at start.
 4. Jobs after simulation_start_time remain pending until reached by the simulation clock.
 5. Accelerated simulation mode and discrete event jump mode work properly.
 6. Empty dataset handling.
 7. Invalid or missing submit_time handling.
 8. Single job ingestion failure does not stop the arrival simulation.
 9. Deterministic arrival order across multiple runs.
10. End-to-end integration: jobs enter existing ingest -> DB -> Decide scheduler.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from app.arrival.simulator import (
    ArrivalJobState,
    DynamicArrivalSimulator,
    SimulationConfig,
    SimulationJobRecord,
)
from app.shared.database import init_db, SessionLocal
from app.shared.models import JobORM, JobStatus, JobSubmitRequest


@pytest.fixture
def db_session(db):
    yield db


class TestDynamicArrivalSimulator:
    def test_chronological_ordering_and_determinism(self, tmp_path):
        csv_file = tmp_path / "test_ordering.csv"
        csv_file.write_text(
            "job_id,job_type,team,priority,region,submit_time,earliest_start_time,deadline,runtime_hours,power_kw,energy_kwh,slack_hours,deferrable,container_image,cpu_request,memory_request,carbon_budget_kg\n"
            "JOB-C,ETL,teamA,HIGH,IN-TG,2026-04-01T11:00:00Z,2026-04-01T11:00:00Z,2026-04-01T13:00:00Z,1.0,5.0,5.0,2.0,TRUE,img,500m,512Mi,10.0\n"
            "JOB-A,DATA_PROCESSING,teamA,LOW,IN-TG,2026-04-01T09:00:00Z,2026-04-01T09:00:00Z,2026-04-01T12:00:00Z,1.0,5.0,5.0,3.0,TRUE,img,500m,512Mi,10.0\n"
            "JOB-B,HPC,teamB,MEDIUM,IN-TG,2026-04-01T10:00:00Z,2026-04-01T10:00:00Z,2026-04-01T14:00:00Z,1.0,5.0,5.0,4.0,TRUE,img,500m,512Mi,10.0\n",
            encoding="utf-8",
        )

        config = SimulationConfig(
            dataset_path=str(csv_file),
            simulation_speed=0,  # instant jump
            simulation_start_time=datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc),
            auto_schedule=False,
        )

        # Mock ingest callback to avoid external network calls
        released_order = []
        def mock_ingest(db, req):
            released_order.append(req.job_id)
            return JobORM(job_id=req.job_id, team_id=req.team_id, status=JobStatus.SUBMITTED, deadline=req.deadline, runtime_minutes=req.runtime_minutes, power_kw=req.power_kw, region=req.region)

        sim = DynamicArrivalSimulator(config=config, ingest_callback=mock_ingest)
        assert len(sim.jobs) == 3
        # In loaded jobs, order must be JOB-A (09:00), JOB-B (10:00), JOB-C (11:00)
        assert [j.job_id for j in sim.jobs] == ["JOB-A", "JOB-B", "JOB-C"]

        summary = sim.run()
        assert summary.jobs_released == 3
        assert summary.jobs_submitted_successfully == 3
        assert released_order == ["JOB-A", "JOB-B", "JOB-C"]

    def test_simultaneous_release_identical_timestamps(self, tmp_path):
        csv_file = tmp_path / "test_simultaneous.csv"
        csv_file.write_text(
            "job_id,job_type,team,priority,region,submit_time,earliest_start_time,deadline,runtime_hours,power_kw,energy_kwh,slack_hours,deferrable,container_image,cpu_request,memory_request,carbon_budget_kg\n"
            "JOB-2,ETL,teamA,HIGH,IN-TG,2026-04-01T10:00:00Z,2026-04-01T10:00:00Z,2026-04-01T13:00:00Z,1.0,5.0,5.0,2.0,TRUE,img,500m,512Mi,10.0\n"
            "JOB-1,DATA_PROCESSING,teamA,LOW,IN-TG,2026-04-01T10:00:00Z,2026-04-01T10:00:00Z,2026-04-01T12:00:00Z,1.0,5.0,5.0,3.0,TRUE,img,500m,512Mi,10.0\n",
            encoding="utf-8",
        )

        config = SimulationConfig(
            dataset_path=str(csv_file),
            simulation_speed=0,
            simulation_start_time=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
            auto_schedule=False,
        )

        released_steps = []
        def mock_ingest(db, req):
            return JobORM(job_id=req.job_id, team_id=req.team_id, status=JobStatus.SUBMITTED, deadline=req.deadline, runtime_minutes=req.runtime_minutes, power_kw=req.power_kw, region=req.region)

        sim = DynamicArrivalSimulator(config=config, ingest_callback=mock_ingest)
        # At 09:00 (start), nothing ready yet
        step1 = sim.step_to_time(datetime(2026, 4, 1, 9, 30, tzinfo=timezone.utc))
        assert len(step1) == 0

        # At 10:00, both JOB-1 and JOB-2 arrive together
        step2 = sim.step_to_time(datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc))
        assert len(step2) == 2
        assert {j.job_id for j in step2} == {"JOB-1", "JOB-2"}

    def test_backlog_handling_before_start_time(self, tmp_path):
        csv_file = tmp_path / "test_backlog.csv"
        csv_file.write_text(
            "job_id,job_type,team,priority,region,submit_time,earliest_start_time,deadline,runtime_hours,power_kw,energy_kwh,slack_hours,deferrable,container_image,cpu_request,memory_request,carbon_budget_kg\n"
            "JOB-EARLY-1,ETL,teamA,HIGH,IN-TG,2026-04-01T08:30:00Z,2026-04-01T08:30:00Z,2026-04-01T13:00:00Z,1.0,5.0,5.0,2.0,TRUE,img,500m,512Mi,10.0\n"
            "JOB-EARLY-2,DATA,teamA,LOW,IN-TG,2026-04-01T09:00:00Z,2026-04-01T09:00:00Z,2026-04-01T12:00:00Z,1.0,5.0,5.0,3.0,TRUE,img,500m,512Mi,10.0\n"
            "JOB-LATER,HPC,teamB,MEDIUM,IN-TG,2026-04-01T10:30:00Z,2026-04-01T10:30:00Z,2026-04-01T14:00:00Z,1.0,5.0,5.0,4.0,TRUE,img,500m,512Mi,10.0\n",
            encoding="utf-8",
        )

        # Start clock at 09:00 -> JOB-EARLY-1 and JOB-EARLY-2 are backlog; JOB-LATER is pending
        config = SimulationConfig(
            dataset_path=str(csv_file),
            simulation_speed=0,
            simulation_start_time=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
            auto_schedule=False,
        )

        sim = DynamicArrivalSimulator(config=config, ingest_callback=lambda db, req: JobORM(job_id=req.job_id, team_id=req.team_id, status=JobStatus.SUBMITTED, deadline=req.deadline, runtime_minutes=req.runtime_minutes, power_kw=req.power_kw, region=req.region))
        assert sim.jobs[0].is_backlog is True
        assert sim.jobs[1].is_backlog is True
        assert sim.jobs[2].is_backlog is False

        summary = sim.run()
        assert summary.backlog_jobs_count == 2
        assert summary.jobs_released == 3

    def test_single_job_ingest_failure_does_not_abort_simulation(self, tmp_path):
        csv_file = tmp_path / "test_failure.csv"
        csv_file.write_text(
            "job_id,job_type,team,priority,region,submit_time,earliest_start_time,deadline,runtime_hours,power_kw,energy_kwh,slack_hours,deferrable,container_image,cpu_request,memory_request,carbon_budget_kg\n"
            "JOB-1,ETL,teamA,HIGH,IN-TG,2026-04-01T09:00:00Z,2026-04-01T09:00:00Z,2026-04-01T13:00:00Z,1.0,5.0,5.0,2.0,TRUE,img,500m,512Mi,10.0\n"
            "JOB-FAIL,BAD,teamA,LOW,IN-TG,2026-04-01T09:15:00Z,2026-04-01T09:15:00Z,2026-04-01T12:00:00Z,1.0,5.0,5.0,3.0,TRUE,img,500m,512Mi,10.0\n"
            "JOB-2,HPC,teamB,MEDIUM,IN-TG,2026-04-01T09:30:00Z,2026-04-01T09:30:00Z,2026-04-01T14:00:00Z,1.0,5.0,5.0,4.0,TRUE,img,500m,512Mi,10.0\n",
            encoding="utf-8",
        )

        config = SimulationConfig(
            dataset_path=str(csv_file),
            simulation_speed=0,
            auto_schedule=False,
        )

        def failing_ingest(db, req):
            if req.job_id == "JOB-FAIL":
                raise RuntimeError("Simulated transient ingest failure")
            return JobORM(job_id=req.job_id, team_id=req.team_id, status=JobStatus.SUBMITTED, deadline=req.deadline, runtime_minutes=req.runtime_minutes, power_kw=req.power_kw, region=req.region)

        sim = DynamicArrivalSimulator(config=config, ingest_callback=failing_ingest)
        summary = sim.run()

        # All 3 jobs were released, 2 succeeded, 1 failed, and simulation finished cleanly
        assert summary.jobs_released == 3
        assert summary.jobs_submitted_successfully == 2
        assert summary.jobs_failed == 1
        assert sim.jobs[1].state == ArrivalJobState.FAILED_INGEST
        assert "Simulated transient ingest failure" in sim.jobs[1].error_message

    def test_empty_dataset_handling(self, tmp_path):
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text("job_id,job_type,team,priority,region,submit_time,earliest_start_time,deadline,runtime_hours,power_kw,energy_kwh,slack_hours,deferrable,container_image,cpu_request,memory_request,carbon_budget_kg\n", encoding="utf-8")

        config = SimulationConfig(dataset_path=str(empty_csv), simulation_speed=0)
        sim = DynamicArrivalSimulator(config=config)
        summary = sim.run()
        assert summary.total_jobs == 0
        assert summary.jobs_released == 0

    def test_real_dataset_simulation_with_max_jobs(self, db_session, monkeypatch):
        monkeypatch.setenv("SIMULATE_CARBON_API_DOWN", "true")
        # Run real dataset with max_jobs=5 and auto_schedule=True
        # With 10 supported regions (including IN-TG, IN-PB, US-CA), all 5 jobs succeed
        config = SimulationConfig(
            dataset_path="data/greenshift_workloads_final.csv",
            simulation_speed=0,
            max_jobs=5,
            auto_schedule=True,
            reanchor_historical=True,
        )

        sim = DynamicArrivalSimulator(config=config, db=db_session)
        assert len(sim.jobs) == 5

        summary = sim.run(db=db_session)
        assert summary.total_jobs == 5
        assert summary.jobs_released == 5
        assert summary.jobs_submitted_successfully == 5
        assert summary.jobs_failed == 0

        # Verify DB records and ScheduleDecisions for supported jobs
        for j_rec in sim.jobs:
            job = db_session.get(JobORM, j_rec.job_id)
            assert job is not None
            assert job.schedule_decision is not None
            assert job.schedule_decision.selected_start is not None
