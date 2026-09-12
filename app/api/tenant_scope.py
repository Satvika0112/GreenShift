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

from app.shared.auth import AuthenticatedIdentity, is_company_admin, is_platform_admin
from app.shared.models import JobORM, JobStatus


def is_team_restricted(identity: Optional[AuthenticatedIdentity]) -> bool:
    """
    True only for a plain Company User. Platform Admin is global; Company
    Admin must see every team within their own tenant (never just their own
    team) — so neither is subject to the team filter below. Deliberately
    checks both roles explicitly rather than `not is_company_admin(identity)`
    alone, since `is_company_admin()` also returns True for Platform Admin.
    """
    if not identity:
        return False
    return not is_platform_admin(identity) and not is_company_admin(identity)


def get_tenant_jobs(
    db: Session,
    identity: Optional[AuthenticatedIdentity],
    job_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    team_id: Optional[str] = None,
    status: Optional[JobStatus] = None,
    limit: int = 100,
) -> "JobORM | List[JobORM]":
    """
    Retrieve jobs with strict tenant and team isolation.

    - Platform admins can view all jobs, or filter by a specific tenant_id.
    - Company admins can view all jobs within their own tenant.
    - Company Users are strictly scoped to their own team within their tenant.
    - Cross-tenant access yields 404 (prevents leaking existence).
    - Cross-team access for non-admin yields 403 (Access forbidden).
    """
    team_restricted = is_team_restricted(identity)

    if job_id:
        job = db.get(JobORM, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        # Platform admin can access any job
        if identity and is_platform_admin(identity):
            return job
        # Tenant isolation: Cross-tenant access -> 404
        if identity and job.tenant_id and identity.tenant_id and job.tenant_id != identity.tenant_id:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        # Team isolation for Company Users only: Cross-team access -> 403.
        # Compared unconditionally (not just "if identity_team truthy") so a
        # Company User with no team assigned yet fails closed to team-scoped
        # jobs rather than silently falling through to tenant-wide access.
        if identity and team_restricted:
            identity_team = getattr(identity, "team_id", None)
            if job.team_id != identity_team:
                raise HTTPException(status_code=403, detail=f"Access forbidden: Job {job_id} belongs to another team")
        return job

    query = db.query(JobORM)
    if identity:
        if is_platform_admin(identity):
            # Platform admin can optionally filter by tenant_id
            if tenant_id:
                query = query.filter(JobORM.tenant_id == tenant_id)
        else:
            # Regular company user/admin is strictly locked to their tenant
            if identity.tenant_id:
                query = query.filter(JobORM.tenant_id == identity.tenant_id)
    elif tenant_id:
        # Dev mode / no identity provided
        query = query.filter(JobORM.tenant_id == tenant_id)

    # Team isolation: Company Users are strictly locked to their own team,
    # applied unconditionally (even when they have no team assigned yet) so a
    # missing team_id fails closed instead of broadening to the whole tenant.
    # Company Admin and Platform Admin may see every team in scope, and may
    # optionally filter by a specific team_id.
    if identity and team_restricted:
        identity_team = getattr(identity, "team_id", None)
        query = query.filter(JobORM.team_id == identity_team)
    elif team_id:
        query = query.filter(JobORM.team_id == team_id)

    if status:
        query = query.filter(JobORM.status == status)
    return query.order_by(JobORM.submitted_at.desc()).limit(limit).all()


def stamp_tenant(job: JobORM, identity: Optional[AuthenticatedIdentity]) -> JobORM:
    """
    Stamp a job with the authenticated tenant's ID and company name.
    """
    if identity:
        if identity.tenant_id:
            job.tenant_id = identity.tenant_id
        if identity.company_name:
            job.company_name = identity.company_name
    return job

