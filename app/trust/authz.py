"""
Trust/Audit RBAC scoping.

Deliberately independent of app.api.tenant_scope.get_tenant_jobs (which
already correctly excludes COMPANY_ADMIN from team-scoping via its own
is_team_restricted() helper — not a bug as of this writing). That function
is shared by 6 other routers outside Trust/Audit ownership, so it is not
modified; Trust/Audit instead owns its own correctly-scoped authorization
here, matching the pattern app.brsr.service already uses for its own
require_view_access/require_edit_access.

RBAC matrix enforced throughout this module:
  PLATFORM_ADMIN — global visibility; only role that may verify the global
                   chain or create/verify anchors.
  COMPANY_ADMIN  — every team within their own company; audit read only.
  COMPANY_USER   — their own team only; audit read only.

Never derive tenant_id/team_id/role from client input — always from the
authenticated UserORM (app.shared.auth.get_current_user).
"""

from fastapi import HTTPException
from sqlalchemy import and_, false, or_
from sqlalchemy.orm import Query, Session

from app.shared.auth import is_platform_admin
from app.shared.models import AuditEventORM, JobORM, UserORM


def _role_value(user: UserORM) -> str:
    role = getattr(user, "role", None)
    return role.value if hasattr(role, "value") else str(role)


def require_global_chain_access(user: UserORM) -> None:
    """/trust/verify and /trust/anchor/create (and by extension anchor
    listing) are Platform-Admin-only — enforced here, not left to the
    frontend."""
    if not is_platform_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Only Platform Admin can verify the global audit chain or manage anchors.",
        )


def scope_audit_events_query(db: Session, query: Query, user: UserORM) -> Query:
    """
    Apply the Trust/Audit RBAC matrix to an AuditEventORM query.

    Prefers the event's own tenant_id/team_id columns (populated for every
    event created after this feature shipped). Falls back to resolving
    scope via the event's job_id -> JobORM.tenant_id/team_id for legacy
    rows created before these columns existed (tenant_id/team_id NULL on
    the event itself) — this is the same fallback the pre-existing
    /trust/events endpoint already used, preserved here rather than
    silently losing visibility into pre-migration history.
    """
    if is_platform_admin(user):
        return query

    if not user.tenant_id:
        return query.filter(false())  # no tenant -> no visibility

    tenant_job_ids = db.query(JobORM.job_id).filter(JobORM.tenant_id == user.tenant_id)
    tenant_filter = or_(
        AuditEventORM.tenant_id == user.tenant_id,
        and_(AuditEventORM.tenant_id.is_(None), AuditEventORM.job_id.in_(tenant_job_ids)),
    )
    query = query.filter(tenant_filter)

    if _role_value(user) == "COMPANY_USER":
        # Checked unconditionally (not "and user.team_id") so a Company User
        # with no team assigned yet fails closed to zero events instead of
        # silently falling through to the whole tenant's audit trail — matches
        # can_view_job_audit's `bool(user.team_id) and job.team_id == ...`
        # below, which denies outright (never grants visibility into
        # team_id-null rows either) when user.team_id is falsy.
        if not user.team_id:
            return query.filter(false())
        team_job_ids = db.query(JobORM.job_id).filter(JobORM.team_id == user.team_id)
        team_filter = or_(
            AuditEventORM.team_id == user.team_id,
            and_(AuditEventORM.team_id.is_(None), AuditEventORM.job_id.in_(team_job_ids)),
        )
        query = query.filter(team_filter)

    return query


def can_view_job_audit(user: UserORM, job: JobORM) -> bool:
    """Whether `user` may view `job`'s audit trail, per the Trust/Audit RBAC
    matrix (Company Admin: whole company; Company User: own team only)."""
    if is_platform_admin(user):
        return True
    if not user.tenant_id or job.tenant_id != user.tenant_id:
        return False
    if _role_value(user) == "COMPANY_ADMIN":
        return True
    return bool(user.team_id) and job.team_id == user.team_id


def get_authorized_job_or_404(db: Session, user: UserORM, job_id: str) -> JobORM:
    """Resolve a job for audit purposes, enforcing the Trust/Audit RBAC
    matrix. Unauthorized access (cross-tenant, cross-team, or nonexistent)
    all return 404 — never leaking whether a job exists outside the
    caller's authorized scope."""
    job = db.get(JobORM, job_id)
    if job is None or not can_view_job_audit(user, job):
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job
