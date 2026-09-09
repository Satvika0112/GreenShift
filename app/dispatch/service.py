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
from app.dispatch.job_claimer import (
    WORKER_ID,
    claim_ready_jobs,
    recover_expired_claims,
    promote_scheduled_to_ready,
)
from app.observability.metrics import (
    dispatcher_jobs_total,
    dispatcher_duration_seconds,
    dispatch_queue_depth,
    dispatch_claiming_count,
)
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import JobORM, JobStatus, KubernetesExecutionORM
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)

DISPATCH_POLL_SECONDS = 5  # Tighter loop — small batches, not big sweeps


def _get_jobs_ready_to_dispatch(db: Session):
    """Fallback query: find jobs whose start time has arrived."""
    now = utcnow()
    return (
        db.query(JobORM)
        .filter(JobORM.status.in_([JobStatus.SCHEDULED, JobStatus.APPROVED]))
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


def _get_active_executions(db: Session) -> list:
    """Find executions that are still running and need status polling."""
    return (
        db.query(KubernetesExecutionORM)
        .filter(KubernetesExecutionORM.k8s_status.in_(["Pending", "Running", "ContainerCreating"]))
        .all()
    )


def dispatch_loop_tick(db: Session) -> dict:
    """
    Single tick of the horizontally scalable dispatcher loop:
    1. Recover expired leases from crashed workers (CLAIMING -> READY)
    2. Promote SCHEDULED/APPROVED -> READY (time-based readiness)
    3. Claim a batch of READY jobs atomically
    4. Dispatch each claimed job to Kubernetes
    5. Refresh status of active K8s executions
    """
    stats = {"recovered": 0, "promoted": 0, "claimed": 0, "dispatched": 0, "failed": 0, "refreshed": 0}

    # 1. Recover expired claims
    stats["recovered"] = recover_expired_claims(db)

    # 2. Promote scheduled -> ready
    stats["promoted"] = promote_scheduled_to_ready(db)

    # Observability gauges
    ready_count = db.query(JobORM).filter(JobORM.status == JobStatus.READY).count()
    claiming_count = db.query(JobORM).filter(JobORM.status == JobStatus.CLAIMING).count()
    dispatch_queue_depth.set(ready_count)
    dispatch_claiming_count.set(claiming_count)

    # 3. Claim batch
    claimed_jobs = claim_ready_jobs(db)
    stats["claimed"] = len(claimed_jobs)

    # 4. Dispatch each claimed job
    for job in claimed_jobs:
        start = time.monotonic()
        try:
            dispatch_job(db, job)
            stats["dispatched"] += 1
            dispatcher_jobs_total.labels(status="success").inc()
            dispatcher_duration_seconds.observe(time.monotonic() - start)
        except DispatchError as exc:
            logger.error("[%s] Dispatch failed for %s: %s", WORKER_ID, job.job_id, exc)
            stats["failed"] += 1
            dispatcher_jobs_total.labels(status="failed").inc()
            # dispatch_job already marks the job FAILED internally
        except Exception as exc:
            logger.error("[%s] Unexpected dispatch failure for %s: %s", WORKER_ID, job.job_id, exc)
            stats["failed"] += 1
            dispatcher_jobs_total.labels(status="failed").inc()

    # 5. Refresh active executions
    active = _get_active_executions(db)
    for execution in active:
        try:
            refresh_job_status(db, execution)
            stats["refreshed"] += 1
        except Exception as exc:
            logger.error("Status refresh failed for %s: %s", execution.kubernetes_job_name, exc)

    return stats


def run_dispatch_loop() -> None:
    """Long-running dispatch service. Can run as multiple replicas."""
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

    # Verify Kubernetes connectivity at startup
    from app.dispatch.kubernetes_client import check_kubernetes_available
    try:
        if check_kubernetes_available():
            logger.info("Kubernetes connection successful")
        else:
            logger.warning("Kubernetes connection failed: API unreachable or health check timed out")
    except Exception as exc:
        logger.warning("Kubernetes connection failed: %s", exc)

    poll_interval = getattr(settings, "dispatch_poll_seconds", DISPATCH_POLL_SECONDS)
    logger.info("[%s] DISPATCH worker started — polling every %ds", WORKER_ID, poll_interval)

    while True:
        db = SessionLocal()
        try:
            stats = dispatch_loop_tick(db)
            if stats["claimed"] > 0 or stats["recovered"] > 0 or stats["promoted"] > 0:
                logger.info("[%s] tick: %s", WORKER_ID, stats)
        except Exception as exc:
            logger.error("[%s] DISPATCH loop error: %s", WORKER_ID, exc)
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
