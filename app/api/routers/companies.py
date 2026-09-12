"""
GreenShift — Company / Organization Onboarding API.

POST /companies/register is the only PUBLIC endpoint here — everything else
requires authentication and operates strictly on the caller's own company
(never a client-supplied tenant_id/company_id). See app.companies.service
for the RBAC/transaction implementation.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.companies.service import (
    CompanyNotFoundError,
    CompanyPermissionError,
    CompanyValidationError,
    company_counts,
    create_own_company_team,
    create_own_company_user,
    get_own_company,
    list_own_company_teams,
    list_own_company_users,
    register_company,
    update_own_company,
)
from app.shared.database import get_db
from app.shared.auth import get_current_user
from app.shared.rate_limiter import limiter
from app.shared.models import (
    CompanyRegisterRequest,
    CompanyRegisterResponse,
    CompanyRegisteredAdmin,
    CompanyProfileResponse,
    CompanyProfileUpdateRequest,
    CompanyUserCreateRequest,
    TeamCreateRequest,
    TeamResponse,
    UserORM,
    UserResponse,
)
from app.shared.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/companies", tags=["Companies"])


def _request_id(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


def _map_error(exc: Exception):
    if isinstance(exc, CompanyPermissionError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, CompanyNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, CompanyValidationError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    raise exc


@router.post(
    "/register",
    response_model=CompanyRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new company and its first administrator (public)",
)
@limiter.limit("5/minute")
def api_register_company(request: Request, body: CompanyRegisterRequest, db: Session = Depends(get_db)):
    """
    Public, unauthenticated endpoint. Atomically creates a new Company
    (tenant), its default team, and its first COMPANY_ADMIN. Role, tenant_id,
    team_id, and company_id are never accepted from the request body — see
    CompanyRegisterRequest, which has no such fields at all.
    """
    try:
        tenant, team, admin = register_company(db, body, request_id=_request_id(request))
    except CompanyValidationError as exc:
        _map_error(exc)
    return CompanyRegisterResponse(
        company_id=tenant.id,
        company_name=tenant.name,
        team_id=team.id,
        team_name=team.name,
        admin=CompanyRegisteredAdmin(id=admin.id, username=admin.username, email=admin.email, role=admin.role),
    )


@router.get(
    "/me",
    response_model=CompanyProfileResponse,
    summary="Get the authenticated user's own company profile",
)
def api_get_my_company(db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    try:
        tenant = get_own_company(db, current_user)
    except (CompanyNotFoundError, CompanyValidationError) as exc:
        _map_error(exc)
    counts = company_counts(db, tenant.id)
    return CompanyProfileResponse.model_validate(tenant).model_copy(update=counts)


@router.patch(
    "/me",
    response_model=CompanyProfileResponse,
    summary="Update the authenticated Company Admin's own company profile",
)
def api_update_my_company(
    request: Request, body: CompanyProfileUpdateRequest,
    db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user),
):
    try:
        tenant = update_own_company(
            db, current_user, body.model_dump(exclude_unset=True), request_id=_request_id(request),
        )
    except (CompanyNotFoundError, CompanyPermissionError, CompanyValidationError) as exc:
        _map_error(exc)
    counts = company_counts(db, tenant.id)
    return CompanyProfileResponse.model_validate(tenant).model_copy(update=counts)


@router.get(
    "/me/users",
    response_model=List[UserResponse],
    summary="List users in the authenticated user's own company (read-only for Company User)",
)
def api_list_my_company_users(db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    try:
        return list_own_company_users(db, current_user)
    except CompanyValidationError as exc:
        _map_error(exc)


@router.post(
    "/me/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user in the authenticated Company Admin's own company",
)
def api_create_my_company_user(
    request: Request, body: CompanyUserCreateRequest,
    db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user),
):
    try:
        return create_own_company_user(db, current_user, body, request_id=_request_id(request))
    except (CompanyPermissionError, CompanyValidationError) as exc:
        _map_error(exc)


@router.get(
    "/me/teams",
    response_model=List[TeamResponse],
    summary="List teams in the authenticated user's own company",
)
def api_list_my_company_teams(db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    try:
        return list_own_company_teams(db, current_user)
    except CompanyValidationError as exc:
        _map_error(exc)


@router.post(
    "/me/teams",
    response_model=TeamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a team in the authenticated Company Admin's own company",
)
def api_create_my_company_team(
    request: Request, body: TeamCreateRequest,
    db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user),
):
    try:
        team = create_own_company_team(db, current_user, body, request_id=_request_id(request))
    except (CompanyPermissionError, CompanyValidationError) as exc:
        _map_error(exc)
    return TeamResponse(id=team.id, tenant_id=team.tenant_id, name=team.name, created_at=team.created_at, member_count=0)
