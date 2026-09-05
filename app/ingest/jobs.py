"""
Agent 1 — INGEST
Job Registry — CRUD operations for the jobs table.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.shared.models import JobORM, JobStatus, JobSubmitRequest
from app.shared.timezone import normalize_to_utc
from app.shared.utils import generate_job_id, utcnow

logger = logging.getLogger(__name__)


def submit_job(db: Session, request: JobSubmitRequest) -> JobORM:
    """
    Register a new job in the job registry.

    If request.job_id is set (e.g. from a CSV bulk load), the provided ID is
    used directly. This preserves original IDs from the workloads dataset.
    Otherwise a new GreenShift job ID is generated.

    Args:
        db:      SQLAlchemy session
        request: Validated job submission request

    Returns:
        Newly created JobORM instance (status=SUBMITTED)
    """
    # Use provided job_id (CSV dataset) or generate a new one
    job_id = request.job_id if request.job_id else generate_job_id()
    now = utcnow()
    req_tz = getattr(request, "timezone", None)
    submitted_at_raw = request.submit_time if request.submit_time else now
    submitted_at = normalize_to_utc(submitted_at_raw, region=request.region, timezone_name=req_tz)
    deadline = normalize_to_utc(request.deadline, region=request.region, timezone_name=req_tz)
    earliest_start_time = (
        normalize_to_utc(request.earliest_start_time, region=request.region, timezone_name=req_tz)
        if request.earliest_start_time
        else None
    )

    # Calculate energy_kwh if not provided:
    # Formula: energy_kwh = power_kw × (runtime_minutes / 60)
    energy_kwh = request.energy_kwh
    if energy_kwh is None or energy_kwh <= 0:
        energy_kwh = request.power_kw * (request.runtime_minutes / 60.0)

    job = JobORM(
        job_id               = job_id,
        team_id              = request.team_id,
        submitted_at         = submitted_at,
        deadline             = deadline,
        runtime_minutes      = request.runtime_minutes,
        power_kw             = request.power_kw,
        region               = request.region,
        status               = JobStatus.SUBMITTED,
        container_image      = request.container_image,
        cpu_request          = request.cpu_request,
        memory_request       = request.memory_request,
        carbon_budget_kg     = request.carbon_budget_kg,
        # Real-dataset fields
        job_type             = request.job_type,
        priority             = request.priority,
        earliest_start_time  = earliest_start_time,
        energy_kwh           = round(energy_kwh, 6),
        deferrable           = request.deferrable,
    )
    job = db.merge(job)
    db.commit()
    db.refresh(job)

    logger.info(
        "Job registered: %s (team=%s, type=%s, region=%s, priority=%s, deferrable=%s)",
        job_id, request.team_id, request.job_type or "n/a",
        request.region, request.priority or "n/a", request.deferrable,
    )
    return job


def get_job(db: Session, job_id: str) -> Optional[JobORM]:
    """Retrieve a job by ID."""
    return db.get(JobORM, job_id)


def list_jobs(
    db: Session,
    team_id: Optional[str] = None,
    status: Optional[JobStatus] = None,
    limit: int = 100,
) -> List[JobORM]:
    """List jobs, optionally filtered by team and/or status."""
    query = db.query(JobORM)
    if team_id:
        query = query.filter(JobORM.team_id == team_id)
    if status:
        query = query.filter(JobORM.status == status)
    return query.order_by(JobORM.submitted_at.desc()).limit(limit).all()


def update_job_status(db: Session, job_id: str, status: JobStatus) -> Optional[JobORM]:
    """Update the status of an existing job."""
    job = db.get(JobORM, job_id)
    if job is None:
        logger.warning("update_job_status: job %s not found", job_id)
        return None
    job.status = status
    db.commit()
    db.refresh(job)
    logger.info("Job %s status → %s", job_id, status)
    return job


def get_jobs_awaiting_schedule(db: Session) -> List[JobORM]:
    """Return all jobs with status=SUBMITTED that have not yet been scheduled."""
    return (
        db.query(JobORM)
        .filter(JobORM.status == JobStatus.SUBMITTED)
        .filter(JobORM.deadline > utcnow())
        .all()
    )
