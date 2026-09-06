"""
Agent 2 — DECIDE
Decision service — orchestrates scheduling for pending jobs.
Stores ScheduleDecision in DB and triggers dispatch.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.decide.scheduler import schedule_job
from app.ingest.data_sources import get_carbon_data, get_tariff_data
from app.ingest.jobs import update_job_status, get_job
from app.shared.database import SessionLocal
from app.shared.models import (
    JobORM,
    JobStatus,
    ScheduleDecisionORM,
    ScheduleDecision,
)
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)


def schedule_and_store(db: Session, job: JobORM, record_audit: bool = False) -> ScheduleDecision:
    """
    Run the scheduler for a job and persist the ScheduleDecision.

    Args:
        db:           SQLAlchemy session
        job:          JobORM record to schedule
        record_audit: Whether to automatically record a JOB_SCHEDULED audit event

    Returns:
        ScheduleDecision pydantic model
    """
    now = utcnow()
    deadline = job.deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    # Fetch carbon + tariff data (API/CSV -> Mock priority)
    carbon_curve = get_carbon_data(job.region, now, deadline)
    tariff_curve = get_tariff_data(job.region, now, deadline, job_type=job.job_type)

    # Run scheduler with full dataset parameters
    decision = schedule_job(
        job_id              = job.job_id,
        team_id             = job.team_id,
        deadline            = deadline,
        runtime_minutes     = job.runtime_minutes,
        power_kw            = job.power_kw,
        region              = job.region,
        carbon_curve        = carbon_curve,
        tariff_curve        = tariff_curve,
        carbon_budget_kg    = job.carbon_budget_kg,
        energy_kwh          = job.energy_kwh,
        earliest_start_time = job.earliest_start_time,
        deferrable          = job.deferrable,
        job_type            = job.job_type,
        tariff_plan         = getattr(job, "tariff_plan", None),
        cpu_request         = getattr(job, "cpu_request", "500m"),
        memory_request      = getattr(job, "memory_request", "512Mi"),
    )

    # Persist decision with regional & impact details (update if already exists)
    existing_sd = db.query(ScheduleDecisionORM).filter(ScheduleDecisionORM.job_id == decision.job_id).first()
    if existing_sd:
        existing_sd.selected_start           = decision.selected_start
        existing_sd.selected_end             = decision.selected_end
        existing_sd.carbon_intensity         = decision.carbon_intensity
        existing_sd.electricity_cost         = decision.electricity_cost
        existing_sd.carbon_emission          = decision.carbon_emission
        existing_sd.region_id                = decision.region_id
        existing_sd.tariff_plan              = decision.tariff_plan
        existing_sd.currency                 = decision.currency
        existing_sd.native_cost              = decision.native_cost
        existing_sd.baseline_native_cost     = decision.baseline_native_cost
        existing_sd.tariff_inr_per_kwh       = decision.tariff_inr_per_kwh
        existing_sd.tariff_category          = decision.tariff_category
        existing_sd.reason                   = decision.reason
        existing_sd.budget_remaining         = decision.budget_remaining
        existing_sd.created_at               = now
        existing_sd.baseline_start           = decision.baseline_start
        existing_sd.baseline_end             = decision.baseline_end
        existing_sd.baseline_carbon_emission = decision.baseline_carbon_emission
        existing_sd.baseline_cost            = decision.baseline_cost
        existing_sd.carbon_avoided           = decision.carbon_avoided
        existing_sd.cost_difference          = decision.cost_difference
        existing_sd.carbon_reduction_pct     = decision.carbon_reduction_pct
        existing_sd.cost_reduction_pct       = decision.cost_reduction_pct
        existing_sd.scheduling_delay_hours   = decision.scheduling_delay_hours
        existing_sd.sla_met                  = decision.sla_met
    else:
        orm = ScheduleDecisionORM(
            job_id                   = decision.job_id,
            selected_start           = decision.selected_start,
            selected_end             = decision.selected_end,
            carbon_intensity         = decision.carbon_intensity,
            electricity_cost         = decision.electricity_cost,
            carbon_emission          = decision.carbon_emission,
            region_id                = decision.region_id,
            tariff_plan              = decision.tariff_plan,
            currency                 = decision.currency,
            native_cost              = decision.native_cost,
            baseline_native_cost     = decision.baseline_native_cost,
            tariff_inr_per_kwh       = decision.tariff_inr_per_kwh,
            tariff_category          = decision.tariff_category,
            reason                   = decision.reason,
            budget_remaining         = decision.budget_remaining,
            created_at               = now,
            baseline_start           = decision.baseline_start,
            baseline_end             = decision.baseline_end,
            baseline_carbon_emission = decision.baseline_carbon_emission,
            baseline_cost            = decision.baseline_cost,
            carbon_avoided           = decision.carbon_avoided,
            cost_difference          = decision.cost_difference,
            carbon_reduction_pct     = decision.carbon_reduction_pct,
            cost_reduction_pct       = decision.cost_reduction_pct,
            scheduling_delay_hours   = decision.scheduling_delay_hours,
            sla_met                  = decision.sla_met,
        )
        db.add(orm)

    # Update job status to PENDING_APPROVAL (Human Approval Gate)
    job.status = JobStatus.PENDING_APPROVAL
    job.updated_at = now
    db.commit()

    saved_sd = existing_sd or orm
    db.refresh(saved_sd)
    decision.id = saved_sd.id

    # Record audit events if requested
    if record_audit:
        try:
            from app.trust.service import record_job_scheduled, record_schedule_proposed
            record_job_scheduled(
                db=db,
                job_id=decision.job_id,
                selected_start=decision.selected_start.isoformat(),
                carbon_emission=decision.carbon_emission,
                carbon_avoided=decision.carbon_avoided,
                budget_remaining=decision.budget_remaining,
            )
            # Add schedule proposed event with decision id
            sd_record = db.query(ScheduleDecisionORM).filter(ScheduleDecisionORM.job_id == decision.job_id).first()
            if sd_record:
                record_schedule_proposed(
                    db=db,
                    job_id=decision.job_id,
                    schedule_decision_id=sd_record.id,
                    selected_start=decision.selected_start.isoformat(),
                    carbon_emission=decision.carbon_emission,
                    electricity_cost=decision.electricity_cost,
                    region_id=decision.region_id,
                    tariff_plan=decision.tariff_plan,
                    deadline=job.deadline.isoformat() if job.deadline else None,
                )
        except Exception as exc:
            logger.warning("Audit record failed for job %s scheduling: %s", decision.job_id, exc)

    logger.info(
        "Scheduled job %s → PENDING_APPROVAL | start=%s | carbon=%.4fkg | cost=$%.4f | avoided=%.4fkg",
        decision.job_id,
        decision.selected_start.isoformat(),
        decision.carbon_emission,
        decision.electricity_cost,
        decision.carbon_avoided or 0.0,
    )

    return decision


def process_pending_jobs(db: Session) -> int:
    """
    Find all SUBMITTED jobs and schedule them.
    Returns the number of jobs processed.
    """
    from app.ingest.jobs import get_jobs_awaiting_schedule

    pending = get_jobs_awaiting_schedule(db)
    count = 0
    for job in pending:
        try:
            schedule_and_store(db, job, record_audit=True)
            count += 1
        except Exception as exc:
            logger.error("Failed to schedule job %s: %s", job.job_id, exc)
            job.status = JobStatus.FAILED
            db.commit()

    return count


def run_decide_loop() -> None:
    """
    Long-running background process.
    Polls for newly submitted jobs and schedules them.
    """
    import time
    from app.shared.database import init_db

    # Retry DB initialisation — PostgreSQL may still be starting up
    for attempt in range(1, 16):
        try:
            init_db()
            logger.info("Database initialised successfully")
            break
        except Exception as exc:
            logger.warning(
                "DB not ready on attempt %d/15: %s — retrying in 4s", attempt, exc
            )
            time.sleep(4)
    else:
        logger.error("Database never became ready after 15 attempts — exiting")
        return

    poll_interval = 60
    logger.info("DECIDE service started — polling every %ds", poll_interval)
    while True:
        db = SessionLocal()
        try:
            count = process_pending_jobs(db)
            if count > 0:
                logger.info("Scheduled %d jobs", count)
        except Exception as exc:
            logger.error("DECIDE loop error: %s", exc)
        finally:
            db.close()
        time.sleep(poll_interval)


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    run_decide_loop()
