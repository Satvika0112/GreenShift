"""
GreenShift Policy-Aware Optimization — company policy persistence service.

Backend-authoritative source of truth for a company's (tenant's) active
scheduling optimization policy — never frontend localStorage. Mirrors the
RBAC/tenant-derivation pattern app.companies.service already uses for
/companies/me (require_own_company / require_company_admin_of_own_company):
every function here operates on the authenticated caller's own tenant_id
only, never a client-supplied one, so cross-tenant IDOR is structurally
impossible the same way it already is for the company profile endpoints.

Policy CHANGES are recorded through the existing Trust/Audit mechanism
(app.trust.service.record_optimization_policy_changed) — this module never
touches the hash-chain ledger directly.
"""

import logging
from typing import Any, Optional, Tuple

from sqlalchemy.orm import Session

from app.companies.service import (
    require_company_admin_of_own_company,
    require_own_company,
)
from app.decide.optimization_policy import (
    DEFAULT_POLICY,
    InvalidOptimizationPolicyError,
    OptimizationPolicy,
    validate_carbon_tolerance_pct,
    validate_policy,
)
from app.shared.models import OptimizationPolicyORM, OptimizationPolicyResponse, UserORM
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)


class OptimizationPolicyValidationError(Exception):
    """Raised for an invalid policy/tolerance value on write."""
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _active_row(db: Session, tenant_id: str) -> Optional[OptimizationPolicyORM]:
    return (
        db.query(OptimizationPolicyORM)
        .filter(OptimizationPolicyORM.tenant_id == tenant_id, OptimizationPolicyORM.is_active.is_(True))
        .first()
    )


def _to_response(db: Session, row: Optional[OptimizationPolicyORM]) -> OptimizationPolicyResponse:
    if row is None:
        # No policy configured yet — the honest, explicit default, never a
        # fabricated "updated_by"/"updated_at".
        return OptimizationPolicyResponse(
            policy=DEFAULT_POLICY.value,
            carbon_tolerance_pct=None,
            updated_by=None,
            updated_at=None,
        )
    updated_by_username = None
    if row.updated_by_user_id:
        updater = db.get(UserORM, row.updated_by_user_id)
        updated_by_username = updater.username if updater else None
    return OptimizationPolicyResponse(
        policy=row.policy,
        carbon_tolerance_pct=row.carbon_tolerance_pct,
        updated_by=updated_by_username,
        updated_at=row.updated_at or row.created_at,
    )


def get_own_company_policy(db: Session, user: UserORM) -> OptimizationPolicyResponse:
    """
    Read the authenticated caller's own company's active policy.

    Any authenticated user with a tenant_id may read — COMPANY_ADMIN and
    COMPANY_USER alike (mirrors GET /companies/me, which is also
    read-by-any-tenant-member, write-by-admin-only). Platform Admin has no
    tenant_id of their own and gets the same "no associated company" error
    require_own_company already raises for /companies/me — this endpoint
    is self-service, not the Platform Admin's cross-tenant management
    surface (that convention already lives at /admin/companies/{id} for
    other resources and is unchanged by this feature).
    """
    tenant_id = require_own_company(user)
    return _to_response(db, _active_row(db, tenant_id))


def resolve_effective_policy(db: Session, tenant_id: Optional[str]) -> Tuple[OptimizationPolicy, Optional[float]]:
    """
    Resolve the effective (policy, carbon_tolerance_pct) to apply when
    scheduling a tenant's jobs. Always server-side — DECIDE never accepts a
    policy value from the frontend/job payload.

    No tenant_id (e.g. a legacy/unscoped job), or no policy row configured
    yet for this tenant, resolves to DEFAULT_POLICY (CARBON_FIRST) with no
    tolerance — the scheduler's original, only behavior — so a company that
    has never configured a policy sees no change in scheduling outcomes
    from this feature's introduction.
    """
    if not tenant_id:
        return DEFAULT_POLICY, None
    row = _active_row(db, tenant_id)
    if row is None:
        return DEFAULT_POLICY, None
    try:
        policy = validate_policy(row.policy)
    except InvalidOptimizationPolicyError:
        # A row can only ever hold a valid value in practice (the DB CHECK
        # constraint plus update_own_company_policy()'s own validation both
        # prevent this) — this is a defensive fail-safe only, so a corrupted
        # row can never make DECIDE apply an unintended/undefined policy.
        logger.error(
            "Tenant %s has an invalid stored optimization policy %r — falling back to %s",
            tenant_id, row.policy, DEFAULT_POLICY.value,
        )
        return DEFAULT_POLICY, None
    tolerance = row.carbon_tolerance_pct if policy == OptimizationPolicy.CARBON_CONSTRAINED else None
    return policy, tolerance


def update_own_company_policy(
    db: Session,
    user: UserORM,
    policy: str,
    carbon_tolerance_pct: Optional[float],
    actor: Optional[Any] = None,
    request_id: Optional[str] = None,
) -> OptimizationPolicyResponse:
    """
    Update the authenticated Company Admin's own company's policy.

    COMPANY_ADMIN only — Platform Admin is explicitly excluded by
    require_company_admin_of_own_company, matching the identical guard
    already used for PATCH /companies/me. Records an
    OPTIMIZATION_POLICY_CHANGED audit event capturing the previous and new
    (policy, carbon_tolerance_pct) and the real authenticated actor.
    """
    tenant_id = require_company_admin_of_own_company(user)

    try:
        validated_policy = validate_policy(policy)
    except InvalidOptimizationPolicyError as exc:
        raise OptimizationPolicyValidationError(str(exc)) from exc

    validated_tolerance: Optional[float] = None
    if validated_policy == OptimizationPolicy.CARBON_CONSTRAINED:
        if carbon_tolerance_pct is None:
            raise OptimizationPolicyValidationError(
                "carbon_tolerance_pct is required when policy is CARBON_CONSTRAINED"
            )
        try:
            validated_tolerance = validate_carbon_tolerance_pct(carbon_tolerance_pct)
        except InvalidOptimizationPolicyError as exc:
            raise OptimizationPolicyValidationError(str(exc)) from exc
    elif carbon_tolerance_pct is not None:
        # An ambiguous request (a tolerance supplied for a policy that
        # doesn't use one) fails loudly rather than silently ignoring the
        # extra field or guessing the caller meant CARBON_CONSTRAINED.
        raise OptimizationPolicyValidationError(
            "carbon_tolerance_pct is only accepted when policy is CARBON_CONSTRAINED"
        )

    row = _active_row(db, tenant_id)
    previous_policy = row.policy if row else None
    previous_tolerance = row.carbon_tolerance_pct if row else None

    now = utcnow()
    if row is None:
        row = OptimizationPolicyORM(
            tenant_id=tenant_id,
            policy=validated_policy.value,
            carbon_tolerance_pct=validated_tolerance,
            is_active=True,
            created_at=now,
            updated_at=now,
            updated_by_user_id=user.id,
        )
        db.add(row)
    else:
        row.policy = validated_policy.value
        row.carbon_tolerance_pct = validated_tolerance
        row.updated_at = now
        row.updated_by_user_id = user.id

    db.commit()
    db.refresh(row)

    try:
        from app.trust.service import record_optimization_policy_changed
        record_optimization_policy_changed(
            db,
            previous_policy=previous_policy,
            new_policy=validated_policy.value,
            previous_carbon_tolerance_pct=previous_tolerance,
            new_carbon_tolerance_pct=validated_tolerance,
            tenant_id=tenant_id,
            actor=actor or user,
            request_id=request_id,
        )
    except Exception as exc:
        logger.warning("Audit record failed for optimization policy change (tenant=%s): %s", tenant_id, exc)

    return _to_response(db, row)
