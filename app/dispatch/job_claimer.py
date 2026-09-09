"""
Atomic job claiming using PostgreSQL row-level locking.

Multiple dispatcher workers can safely claim disjoint batches of READY jobs
concurrently. FOR UPDATE SKIP LOCKED ensures no two workers claim the same job.

For SQLite (development): falls back to query + update with priority/deadline
ordering (safe for single worker dev/test environments).
"""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.models import JobORM, JobStatus, ScheduleDecisionORM
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)

CLAIM_BATCH_SIZE = 50           # Jobs per claim batch
CLAIM_LEASE_SECONDS = 120       # Lease timeout — CLAIMING → READY if worker dies
WORKER_ID = os.environ.get("WORKER_ID", f"dispatcher-{uuid.uuid4().hex[:8]}")  # Unique per process instance


def _is_postgresql() -> bool:
    """Check if we're connected to PostgreSQL (supports SKIP LOCKED)."""
    return "postgresql" in (settings.database_url or "").lower()


def claim_ready_jobs(db: Session, batch_size: int = CLAIM_BATCH_SIZE) -> List[JobORM]:
    """
    Atomically claim a batch of READY jobs for this dispatcher worker.

    PostgreSQL: Uses FOR UPDATE SKIP LOCKED for true concurrent claiming.
    SQLite: Uses optimistic UPDATE ... WHERE status='READY' (safe for single worker).

    Returns: List of JobORM records now in CLAIMING state, owned by this worker.
    """
    now = utcnow()
    lease_expires = now + timedelta(seconds=CLAIM_LEASE_SECONDS)

    if _is_postgresql():
        return _claim_postgresql(db, batch_size, now, lease_expires)
    else:
        return _claim_sqlite(db, batch_size, now, lease_expires)


def _claim_postgresql(db: Session, batch_size: int, now: datetime, lease_expires: datetime) -> List[JobORM]:
    """
    PostgreSQL atomic claim:
    1. SELECT ... FOR UPDATE SKIP LOCKED — lock rows other workers can't see
    2. UPDATE status → CLAIMING with worker_id and lease
    """
    result = db.execute(
        text("""
            SELECT job_id FROM jobs
            WHERE status = :ready_status
            ORDER BY
                CASE priority
                    WHEN 'CRITICAL' THEN 0
                    WHEN 'HIGH' THEN 1
                    WHEN 'MEDIUM' THEN 2
                    WHEN 'LOW' THEN 3
                    ELSE 4
                END,
                deadline ASC
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        """),
        {"ready_status": JobStatus.READY.value, "batch_size": batch_size},
    )
    job_ids = [row[0] for row in result.fetchall()]

    if not job_ids:
        return []

    # Bulk update claimed jobs
    db.execute(
        update(JobORM)
        .where(JobORM.job_id.in_(job_ids))
        .values(
            status=JobStatus.CLAIMING,
            claimed_by=WORKER_ID,
            claimed_at=now,
            lease_expires_at=lease_expires,
        )
    )
    db.commit()

    # Re-fetch the claimed jobs with relationships
    claimed = db.query(JobORM).filter(JobORM.job_id.in_(job_ids)).all()
    logger.info("[%s] Claimed %d jobs: %s", WORKER_ID, len(claimed), [j.job_id for j in claimed[:5]])
    return claimed


def _claim_sqlite(db: Session, batch_size: int, now: datetime, lease_expires: datetime) -> List[JobORM]:
    """
    SQLite fallback: query + update with priority and deadline ordering (safe for single-worker dev mode).
    No SKIP LOCKED — relies on single dispatcher.
    """
    priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    jobs = (
        db.query(JobORM)
        .filter(JobORM.status == JobStatus.READY)
        .all()
    )
    jobs.sort(key=lambda j: (
        priority_order.get(j.priority, 4),
        j.deadline if j.deadline is not None else datetime.max.replace(tzinfo=timezone.utc),
    ))
    claimed = jobs[:batch_size]

    for job in claimed:
        job.status = JobStatus.CLAIMING
        job.claimed_by = WORKER_ID
        job.claimed_at = now
        job.lease_expires_at = lease_expires

    if claimed:
        db.commit()
        logger.info("[%s] Claimed %d jobs (SQLite mode)", WORKER_ID, len(claimed))
    return claimed


def recover_expired_claims(db: Session) -> int:
    """
    Find jobs stuck in CLAIMING where lease has expired (worker crashed).
    Transition them back to READY so another worker picks them up.

    Returns count of recovered jobs.
    """
    now = utcnow()
    expired = (
        db.query(JobORM)
        .filter(JobORM.status == JobStatus.CLAIMING)
        .filter(JobORM.lease_expires_at < now)
        .all()
    )

    for job in expired:
        logger.warning(
            "Recovering expired claim: job %s was claimed by %s at %s (lease expired %s)",
            job.job_id, job.claimed_by, job.claimed_at, job.lease_expires_at,
        )
        job.status = JobStatus.READY
        job.claimed_by = None
        job.claimed_at = None
        job.lease_expires_at = None

    if expired:
        db.commit()
        logger.info("Recovered %d expired claims → READY", len(expired))

    return len(expired)


def promote_scheduled_to_ready(db: Session) -> int:
    """
    Transition SCHEDULED or APPROVED jobs whose selected_start <= now to READY.
    This is the bridge between the scheduler and the dispatch queue.

    Returns count of promoted jobs.
    """
    now = utcnow()
    promoted = (
        db.query(JobORM)
        .join(JobORM.schedule_decision)
        .filter(JobORM.status.in_([JobStatus.SCHEDULED, JobStatus.APPROVED]))
        .filter(ScheduleDecisionORM.selected_start <= now)
        .all()
    )

    for job in promoted:
        job.status = JobStatus.READY

    if promoted:
        db.commit()
        logger.info("Promoted %d SCHEDULED/APPROVED jobs → READY", len(promoted))

    return len(promoted)
