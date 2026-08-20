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


def schedule_and_store(db: Session, job: JobORM, record_audit: bool = True) -> ScheduleDecision:
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

    # Fetch carbon + tariff data (CSV -> API -> Mock priority)
    carbon_curve = get_carbon_data(job.region, now, deadline)
    tariff_curve = get_tariff_data(job.region, now, deadline)

    # Run scheduler
    decision = schedule_job(
        job_id=job.job_id,
        team_id=job.team_id,
        deadline=deadline,
        runtime_minutes=job.runtime_minutes,
        power_kw=job.power_kw,
        region=job.region,
        carbon_curve=carbon_curve,
        tariff_curve=tariff_curve,
        carbon_budget_kg=job.carbon_budget_kg,
    )

    # Persist decision
    orm = ScheduleDecisionORM(
        job_id=decision.job_id,
        selected_start=decision.selected_start,
        selected_end=decision.selected_end,
        carbon_intensity=decision.carbon_intensity,
        electricity_cost=decision.electricity_cost,
        carbon_emission=decision.carbon_emission,
        reason=decision.reason,
        budget_remaining=decision.budget_remaining,
        created_at=now,
        baseline_start=decision.baseline_start,
        baseline_carbon_emission=decision.baseline_carbon_emission,
        baseline_cost=decision.baseline_cost,
        carbon_avoided=decision.carbon_avoided,
        cost_difference=decision.cost_difference,
    )
    db.add(orm)

    # Update job status
    job.status = JobStatus.SCHEDULED
    db.commit()

    # Record audit event if requested
    if record_audit:
        try:
            from app.trust.service import record_job_scheduled
            record_job_scheduled(
                db=db,
                job_id=decision.job_id,
                selected_start=decision.selected_start.isoformat(),
                carbon_emission=decision.carbon_emission,
                carbon_avoided=decision.carbon_avoided,
                budget_remaining=decision.budget_remaining,
            )
        except Exception as exc:
            logger.warning("Audit record failed for job %s scheduling: %s", decision.job_id, exc)

    logger.info(
        "Scheduled job %s → start=%s | carbon=%.4fkg | avoided=%.4fkg",
        decision.job_id,
        decision.selected_start.isoformat(),
        decision.carbon_emission,
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
