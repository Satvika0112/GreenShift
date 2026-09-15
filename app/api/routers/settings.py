"""
GreenShift — Settings API.

GET/PUT /settings/optimization-policy — backend-owned company scheduling
optimization policy (GreenShift Policy-Aware Optimization). See
app.settings.optimization_policy_service for the RBAC/tenant-derivation
implementation, which mirrors app.companies.service's existing
/companies/me pattern: tenant_id always comes from the authenticated
caller, never a request body/query parameter.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.companies.service import CompanyNotFoundError, CompanyPermissionError, CompanyValidationError
from app.settings.optimization_policy_service import (
    OptimizationPolicyValidationError,
    get_own_company_policy,
    update_own_company_policy,
)
from app.shared.database import get_db
from app.shared.auth import get_current_user
from app.shared.models import OptimizationPolicyResponse, OptimizationPolicyUpdateRequest, UserORM
from app.shared.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])


def _request_id(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


def _map_error(exc: Exception):
    if isinstance(exc, CompanyNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (CompanyPermissionError, CompanyValidationError, OptimizationPolicyValidationError)):
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    raise exc


@router.get(
    "/optimization-policy",
    response_model=OptimizationPolicyResponse,
    summary="Get the authenticated user's own company's scheduling optimization policy",
)
def api_get_optimization_policy(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Read-only for any authenticated member of the company (COMPANY_ADMIN
    and COMPANY_USER alike). Never accepts a tenant_id/company_id — the
    caller's own company is always derived from their authenticated
    session (app.shared.auth.get_current_user).
    """
    try:
        return get_own_company_policy(db, current_user)
    except (CompanyNotFoundError, CompanyValidationError) as exc:
        _map_error(exc)


@router.put(
    "/optimization-policy",
    response_model=OptimizationPolicyResponse,
    summary="Update the authenticated Company Admin's own company's scheduling optimization policy",
)
def api_update_optimization_policy(
    request: Request,
    body: OptimizationPolicyUpdateRequest,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    COMPANY_ADMIN only (Platform Admin explicitly excluded — see
    app.companies.service.require_company_admin_of_own_company; a plain
    COMPANY_USER is rejected with 403). Records an
    OPTIMIZATION_POLICY_CHANGED audit event via the existing Trust/Audit
    mechanism. The actor is always the authenticated caller — never a
    client-supplied identity.
    """
    try:
        return update_own_company_policy(
            db, current_user, body.policy, body.carbon_tolerance_pct,
            actor=current_user, request_id=_request_id(request),
        )
    except (CompanyNotFoundError, CompanyPermissionError, CompanyValidationError, OptimizationPolicyValidationError) as exc:
        _map_error(exc)
