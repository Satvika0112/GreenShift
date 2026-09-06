"""
Agent 3 — DISPATCH
Dispatcher service — polls the DB for scheduled jobs ready to run
and creates Kubernetes Jobs at the right time.

Implementation decision (see docs/DECISIONS.md ADR-002):
  Uses a time-aware polling loop rather than Kubernetes CronJobs.
  Polls every DISPATCHER_POLL_INTERVAL_SECONDS seconds.
  When now >= selected_start, creates the Kubernetes Job.
"""

import logging
import time
from datetime import timezone

from sqlalchemy.orm import Session

from app.dispatch.dispatcher import dispatch_job, refresh_job_status, DispatchError
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import JobORM, JobStatus, KubernetesExecutionORM
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)


def _get_jobs_ready_to_dispatch(db: Session):
    """Return APPROVED jobs whose selected_start <= now."""
    return (
        db.query(JobORM)
        .join(JobORM.schedule_decision)
        .filter(JobORM.status == JobStatus.APPROVED)
        .filter(JobORM.schedule_decision.has())
        .all()
    )


def _filter_ready(jobs):
    """Filter to jobs where selected_start is now or in the past."""
    now = utcnow()
    ready = []
    for job in jobs:
        sd = job.schedule_decision
        if sd is None:
            continue
        start = sd.selected_start
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if start <= now:
            ready.append(job)
        else:
            remaining = (start - now).total_seconds()
            logger.debug("Job %s not ready yet — starts in %.0fs", job.job_id, remaining)
    return ready


def _get_active_executions(db: Session):
    """Return executions in QUEUED or RUNNING state."""
    return (
        db.query(KubernetesExecutionORM)
        .filter(KubernetesExecutionORM.gs_status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        .all()
    )


def dispatch_loop_tick(db: Session) -> None:
    """One iteration of the dispatch loop."""
    # 1. Dispatch ready jobs
    scheduled = _get_jobs_ready_to_dispatch(db)
    ready = _filter_ready(scheduled)
    for job in ready:
        try:
            dispatch_job(db, job)
        except DispatchError as exc:
            logger.error("Dispatch failed for %s: %s", job.job_id, exc)

    # 2. Refresh status of active executions
    active = _get_active_executions(db)
    for execution in active:
        try:
            refresh_job_status(db, execution)
        except Exception as exc:
            logger.error("Status refresh failed for %s: %s", execution.kubernetes_job_name, exc)


def run_dispatch_loop() -> None:
    """Long-running dispatch service."""
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
    # Verify Kubernetes connectivity at startup
    from app.dispatch.kubernetes_client import check_kubernetes_available
    try:
        if check_kubernetes_available():
            logger.info("Kubernetes connection successful")
        else:
            logger.warning("Kubernetes connection failed: API unreachable or health check timed out")
    except Exception as exc:
        logger.warning("Kubernetes connection failed: %s", exc)

    poll_interval = getattr(settings, "dispatch_poll_seconds", settings.dispatcher_poll_interval_seconds)
    logger.info("DISPATCH service started — polling every %ds", poll_interval)
    while True:
        db = SessionLocal()
        try:
            dispatch_loop_tick(db)
        except Exception as exc:
            logger.error("DISPATCH loop error: %s", exc)
        finally:
            db.close()
        time.sleep(poll_interval)


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    run_dispatch_loop()
