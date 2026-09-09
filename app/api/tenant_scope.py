"""
GreenShift — Tenant-Isolated Data Access

This is THE single enforcement point for all job queries.
Every router must call get_tenant_jobs() instead of querying JobORM directly.

Tenant isolation rules:
  - identity is None (dev mode / AUTH_ENABLED=false) → all jobs visible
  - identity set → ONLY jobs where tenant_id == identity.tenant_id
  - Cross-tenant access → 404 (NOT 403) to prevent leaking job existence
"""

from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.shared.auth import AuthenticatedIdentity
from app.shared.models import JobORM, JobStatus


def get_tenant_jobs(
    db: Session,
    identity: Optional[AuthenticatedIdentity],
    job_id: Optional[str] = None,
    team_id: Optional[str] = None,
    status: Optional[JobStatus] = None,
    limit: int = 100,
) -> "JobORM | List[JobORM]":
    """
    Retrieve jobs with strict tenant isolation.

    For single-job lookups (job_id set):
      - Returns the job ORM if found and authorized
      - Returns 404 for missing OR cross-tenant jobs (never 403)

    For list queries:
      - Filters by tenant_id when identity is set
      - Optionally filters by team_id and/or status
    """
    if job_id:
        job = db.query(JobORM).get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        # Cross-tenant: return 404, not 403 (prevents existence leakage)
        if identity and job.tenant_id and job.tenant_id != identity.tenant_id:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return job

    query = db.query(JobORM)
    if identity:
        query = query.filter(JobORM.tenant_id == identity.tenant_id)
    if team_id:
        query = query.filter(JobORM.team_id == team_id)
    if status:
        query = query.filter(JobORM.status == status)
    return query.order_by(JobORM.submitted_at.desc()).limit(limit).all()


def stamp_tenant(job: JobORM, identity: Optional[AuthenticatedIdentity]) -> JobORM:
    """
    Stamp a job with the authenticated tenant's ID.
    No-op when identity is None (dev mode).
    """
    if identity and identity.tenant_id:
        job.tenant_id = identity.tenant_id
    return job
