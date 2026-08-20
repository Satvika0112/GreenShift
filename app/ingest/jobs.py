"""
Agent 1 — INGEST
Job Registry — CRUD operations for the jobs table.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.shared.models import JobORM, JobStatus, JobSubmitRequest
from app.shared.utils import generate_job_id, utcnow

logger = logging.getLogger(__name__)


def submit_job(db: Session, request: JobSubmitRequest) -> JobORM:
    """
    Register a new job in the job registry.

    Args:
        db:      SQLAlchemy session
        request: Validated job submission request

    Returns:
        Newly created JobORM instance (status=SUBMITTED)
    """
    job_id = generate_job_id()
    now = utcnow()

    job = JobORM(
        job_id=job_id,
        team_id=request.team_id,
        submitted_at=now,
        deadline=request.deadline,
        runtime_minutes=request.runtime_minutes,
        power_kw=request.power_kw,
        region=request.region,
        status=JobStatus.SUBMITTED,
        container_image=request.container_image,
        cpu_request=request.cpu_request,
        memory_request=request.memory_request,
        carbon_budget_kg=request.carbon_budget_kg,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info("Job registered: %s (team=%s, region=%s)", job_id, request.team_id, request.region)
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
