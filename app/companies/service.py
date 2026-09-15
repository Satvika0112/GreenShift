"""
GreenShift — Company / Organization Onboarding service.

Backend-authoritative for every RBAC/identity decision here — no endpoint
in app.api.routers.companies accepts a client-supplied tenant_id/team_id/
company_id/role for authorization. See register_company() for the atomic
company+team+admin bootstrap transaction.

Company IS the existing TenantORM (see its docstring in app.shared.models) —
this module builds a richer profile and onboarding flow around the existing
tenant_id architecture, it does not introduce a second one.
"""

import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared.auth import hash_password, is_platform_admin
from app.shared.models import (
    CompanyRegisterRequest,
    CompanyUserCreateRequest,
    TeamCreateRequest,
    TeamORM,
    TenantORM,
    UserORM,
    UserRole,
)
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)


class CompanyValidationError(Exception):
    """Raised for a registration/validation failure (duplicate email, etc.)."""
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class CompanyPermissionError(Exception):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


class CompanyNotFoundError(Exception):
    pass


DEFAULT_TEAM_NAME = "General / Administration"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "company"


def _generate_unique_tenant_id(db: Session, company_name: str) -> str:
    base = f"tenant-{_slugify(company_name)}"
    candidate = base
    suffix = 0
    while db.get(TenantORM, candidate) is not None:
        suffix += 1
        candidate = f"{base}-{uuid.uuid4().hex[:6]}" if suffix > 1 else f"{base}-{suffix}"
    return candidate


def _generate_unique_username(db: Session, admin_email: str) -> str:
    base = admin_email.split("@")[0]
    candidate = base
    suffix = 0
    while db.query(UserORM).filter(UserORM.username == candidate).first() is not None:
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


def register_company(
    db: Session,
    body: CompanyRegisterRequest,
    request_id: Optional[str] = None,
) -> Tuple[TenantORM, TeamORM, UserORM]:
    """
    Atomically create a new Company (TenantORM), its default Team, and its
    first Administrator (COMPANY_ADMIN). Never trusts any role/tenant_id/
    team_id/company_id field — CompanyRegisterRequest has none — role is
    always COMPANY_ADMIN, tenant_id is always the newly generated company
    id, team_id is always the newly created default team.

    Raises CompanyValidationError for any duplicate/invalid input. On any
    failure the whole transaction is rolled back — no partially-created
    company is ever left behind.
    """
    # ── Pre-flight duplicate checks (also enforced at the DB level via
    # unique constraints — see alembic/versions/013_add_company_onboarding.py
    # and UserORM.email/.username — these checks just produce a clean 409/422
    # instead of a raw IntegrityError). ──
    existing_company_name = db.query(TenantORM).filter(TenantORM.name == body.company_name).first()
    if existing_company_name:
        raise CompanyValidationError(f"A company named '{body.company_name}' is already registered", status_code=409)

    existing_company_email = db.query(TenantORM).filter(TenantORM.company_email == body.company_email).first()
    if existing_company_email:
        raise CompanyValidationError(f"Company email '{body.company_email}' is already registered", status_code=409)

    existing_admin_email = db.query(UserORM).filter(UserORM.email == body.admin_email).first()
    if existing_admin_email:
        raise CompanyValidationError(f"Email '{body.admin_email}' is already registered", status_code=409)

    tenant_id = _generate_unique_tenant_id(db, body.company_name)
    team_id = f"team-{tenant_id}-default"
    username = _generate_unique_username(db, body.admin_email)
    now = utcnow()

    try:
        tenant = TenantORM(
            id=tenant_id,
            name=body.company_name,
            legal_name=body.legal_name,
            company_email=body.company_email,
            website=body.website,
            industry=body.industry,
            sector=body.sector,
            country=body.country,
            address=body.address,
            status="ACTIVE",
            is_active=True,
            created_at=now,
        )
        db.add(tenant)
        db.flush()  # surface any DB-level unique-constraint race before proceeding

        team = TeamORM(
            id=team_id,
            tenant_id=tenant_id,
            name=DEFAULT_TEAM_NAME,
            created_at=now,
        )
        db.add(team)
        db.flush()

        admin = UserORM(
            username=username,
            email=body.admin_email,
            hashed_password=hash_password(body.password),
            role=UserRole.COMPANY_ADMIN,
            tenant_id=tenant_id,
            team_id=team_id,
            is_active=True,
            approval_status="APPROVED",
            created_at=now,
        )
        db.add(admin)
        db.flush()

        # Audit BEFORE commit but after flush, so both events are part of
        # the same atomic transaction as the rows they describe — if the
        # commit below fails, the audit rows roll back with everything else.
        try:
            from app.trust.ledger import append_event
            from app.shared.models import EventType
            # No authenticated actor exists during public registration (the
            # administrator account did not exist yet when this event is
            # about to be recorded) — SYSTEM/registration is the honest,
            # server-derived actor_type here, matching the established
            # pattern in app.trust.service.record_user_registered.
            append_event(
                db, EventType.COMPANY_CREATED,
                payload={"company_id": tenant_id, "company_name": tenant.name, "admin_email": body.admin_email},
                tenant_id=tenant_id, team_id=team_id,
                request_id=request_id, source_service="company_registration",
            )
            append_event(
                db, EventType.COMPANY_ADMIN_CREATED,
                payload={"company_id": tenant_id, "admin_username": username, "admin_email": body.admin_email},
                tenant_id=tenant_id, team_id=team_id,
                request_id=request_id, source_service="company_registration",
            )
        except Exception:
            logger.warning("Audit record failed during company registration for %s", tenant_id, exc_info=True)

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("Company registration failed a DB-level uniqueness check for %s: %s", body.company_name, exc)
        raise CompanyValidationError(
            "Company, company email, or administrator email is already registered", status_code=409,
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(tenant)
    db.refresh(team)
    db.refresh(admin)

    try:
        from app.notify.service import create_notification, resolve_platform_admin_user_ids
        from app.shared.models import EventType as NotifEventType
        for platform_admin_id in resolve_platform_admin_user_ids(db):
            create_notification(
                db, recipient_user_id=platform_admin_id, event_type=NotifEventType.TENANT_CREATED,
                category="ACCOUNT", severity="INFO",
                title=f"New company registered: {tenant.name}",
                message=f"'{tenant.name}' registered with administrator {admin.username} ({admin.email}).",
                tenant_id=tenant_id, dedup_suffix=tenant_id, email_required=False,
            )
    except Exception:
        logger.warning("Notification failed for new company registration %s", tenant_id, exc_info=True)

    return tenant, team, admin


# ─────────────────────────────────────────────────────────────────────────────
# RBAC helpers — "own company" scoping for /companies/me/*
# ─────────────────────────────────────────────────────────────────────────────

def require_own_company(user: UserORM) -> str:
    """Every /companies/me/* endpoint operates on the authenticated user's
    own tenant_id only — never a client-supplied one. Platform Admins have
    no "own company" (tenant_id is None for them) and should use the
    existing /admin/companies/{id} endpoints instead."""
    if not user.tenant_id:
        raise CompanyValidationError(
            "This account has no associated company. Platform Admin should use /admin/companies to manage a specific company.",
            status_code=400,
        )
    return user.tenant_id


def require_company_admin_of_own_company(user: UserORM) -> str:
    """Only a COMPANY_ADMIN of the company being modified may mutate it.
    Platform Admin is explicitly, unconditionally excluded here — rather than
    using the broader is_company_admin() (which also returns True for
    Platform Admin), since a Platform Admin account could in principle have
    a tenant_id set and would otherwise be able to mutate that company's
    profile/users/teams through this "own company" surface instead of the
    explicit, audited /admin/companies/{id} path."""
    tenant_id = require_own_company(user)
    if is_platform_admin(user):
        raise CompanyPermissionError("Platform Admin cannot manage a company's profile/users/teams here — use /admin/companies")
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role_val != "COMPANY_ADMIN":
        raise CompanyPermissionError("Company Admin privileges required for this operation")
    return tenant_id


# ─────────────────────────────────────────────────────────────────────────────
# Company profile
# ─────────────────────────────────────────────────────────────────────────────

def get_own_company(db: Session, user: UserORM) -> TenantORM:
    tenant_id = require_own_company(user)
    tenant = db.get(TenantORM, tenant_id)
    if tenant is None:
        raise CompanyNotFoundError(f"Company '{tenant_id}' not found")
    return tenant


def update_own_company(db: Session, user: UserORM, updates: Dict[str, Any], request_id: Optional[str] = None) -> TenantORM:
    tenant_id = require_company_admin_of_own_company(user)
    tenant = db.get(TenantORM, tenant_id)
    if tenant is None:
        raise CompanyNotFoundError(f"Company '{tenant_id}' not found")

    if "company_email" in updates and updates["company_email"] is not None:
        conflict = (
            db.query(TenantORM)
            .filter(TenantORM.company_email == updates["company_email"], TenantORM.id != tenant_id)
            .first()
        )
        if conflict:
            raise CompanyValidationError(f"Company email '{updates['company_email']}' is already registered", status_code=409)

    for key, value in updates.items():
        if value is not None and hasattr(tenant, key):
            setattr(tenant, key, value)
    tenant.updated_at = utcnow()

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CompanyValidationError("Update violates a uniqueness constraint (e.g. company email)", status_code=409) from exc
    db.refresh(tenant)

    try:
        from app.trust.ledger import append_event
        from app.shared.models import EventType
        append_event(
            db, EventType.CONFIG_CHANGED,
            payload={"company_id": tenant_id, "updated_fields": list(updates.keys())},
            actor=user, tenant_id=tenant_id, team_id=user.team_id,
            request_id=request_id, source_service="companies",
        )
    except Exception:
        logger.warning("Audit record failed for company profile update on %s", tenant_id, exc_info=True)

    return tenant


def company_counts(db: Session, tenant_id: str) -> Dict[str, int]:
    from app.shared.models import JobORM
    return {
        "user_count": db.query(UserORM).filter(UserORM.tenant_id == tenant_id).count(),
        "workload_count": db.query(JobORM).filter(JobORM.tenant_id == tenant_id).count(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Company-scoped users
# ─────────────────────────────────────────────────────────────────────────────

def list_own_company_users(db: Session, user: UserORM) -> List[UserORM]:
    tenant_id = require_own_company(user)
    return (
        db.query(UserORM)
        .filter(UserORM.tenant_id == tenant_id)
        .order_by(UserORM.created_at.desc())
        .all()
    )


def create_own_company_user(
    db: Session, user: UserORM, body: CompanyUserCreateRequest, request_id: Optional[str] = None,
) -> UserORM:
    tenant_id = require_company_admin_of_own_company(user)

    # Defense in depth: CompanyUserCreateRequest.role defaults to COMPANY_USER
    # and has no tenant_id/company_id field at all, but a direct/internal
    # caller could still pass PLATFORM_ADMIN — reject it explicitly here too,
    # the "never trust, re-validate at the service boundary" pattern.
    if body.role == UserRole.PLATFORM_ADMIN:
        raise CompanyPermissionError("Cannot create a PLATFORM_ADMIN user via company user management")

    username = body.username or body.email.split("@")[0]
    existing = db.query(UserORM).filter(
        (UserORM.email == body.email) | (UserORM.username == username)
    ).first()
    if existing:
        raise CompanyValidationError(f"User with email '{body.email}' or username '{username}' already exists", status_code=409)

    new_user = UserORM(
        username=username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
        tenant_id=tenant_id,
        team_id=body.team_id,
        is_active=True,
        approval_status="APPROVED",
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CompanyValidationError(f"User with email '{body.email}' or username '{username}' already exists", status_code=409) from exc
    db.refresh(new_user)

    try:
        from app.trust.service import record_user_registered
        record_user_registered(
            db, username=new_user.username, role=new_user.role.value,
            team_id=new_user.team_id, status="APPROVED", tenant_id=tenant_id, actor=user,
        )
    except Exception:
        logger.warning("Audit record failed for company user creation on %s", tenant_id, exc_info=True)

    return new_user


# ─────────────────────────────────────────────────────────────────────────────
# Company-scoped teams
# ─────────────────────────────────────────────────────────────────────────────

def list_own_company_teams(db: Session, user: UserORM) -> List[Dict[str, Any]]:
    tenant_id = require_own_company(user)
    teams = db.query(TeamORM).filter(TeamORM.tenant_id == tenant_id).order_by(TeamORM.created_at.asc()).all()
    result = []
    for t in teams:
        member_count = db.query(UserORM).filter(UserORM.tenant_id == tenant_id, UserORM.team_id == t.id).count()
        result.append({"id": t.id, "tenant_id": t.tenant_id, "name": t.name, "created_at": t.created_at, "member_count": member_count})
    return result


def create_own_company_team(
    db: Session, user: UserORM, body: TeamCreateRequest, request_id: Optional[str] = None,
) -> TeamORM:
    tenant_id = require_company_admin_of_own_company(user)

    existing = db.query(TeamORM).filter(TeamORM.tenant_id == tenant_id, TeamORM.name == body.name).first()
    if existing:
        raise CompanyValidationError(f"A team named '{body.name}' already exists in this company", status_code=409)

    team_id = f"team-{tenant_id}-{_slugify(body.name)}"
    if db.get(TeamORM, team_id) is not None:
        team_id = f"team-{tenant_id}-{uuid.uuid4().hex[:8]}"

    team = TeamORM(id=team_id, tenant_id=tenant_id, name=body.name, created_at=utcnow())
    db.add(team)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CompanyValidationError(f"A team named '{body.name}' already exists in this company", status_code=409) from exc
    db.refresh(team)

    try:
        from app.trust.ledger import append_event
        from app.shared.models import EventType
        append_event(
            db, EventType.CONFIG_CHANGED,
            payload={"company_id": tenant_id, "team_id": team_id, "team_name": team.name, "action": "TEAM_CREATED"},
            actor=user, tenant_id=tenant_id, team_id=team_id,
            request_id=request_id, source_service="companies",
        )
    except Exception:
        logger.warning("Audit record failed for team creation on %s", tenant_id, exc_info=True)

    return team
