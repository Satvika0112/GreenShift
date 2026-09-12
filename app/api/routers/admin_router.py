"""
GreenShift — Admin Router

RBAC-protected endpoints for ADMIN users to manage users and API keys
within their own tenant.

RULE 4: Tenants are provisioned-only (seed script). No POST /admin/tenants.
RULE 3: API keys can NEVER have ADMIN role.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.shared.auth import (
    AuthenticatedIdentity,
    get_current_identity,
    get_current_user,
    hash_password,
    is_platform_admin,
    is_company_admin,
    require_platform_admin,
    require_company_admin,
)
from app.shared.database import get_db
from app.trust.service import (
    record_user_registered,
    record_user_activated,
    record_user_deactivated,
)
from app.shared.models import (
    API_KEY_ALLOWED_ROLES,
    APIKeyCreateRequest,
    APIKeyCreateResponse,
    APIKeyListItem,
    APIKeyORM,
    CompanyCreateRequest,
    CompanyResponse,
    CompanyUpdateRequest,
    JobORM,
    TenantORM,
    TenantUserResponse,
    UserApprovalStatus,
    UserCreateRequest,
    UserORM,
    UserResponse,
    UserRole,
    UserStatusUpdateRequest,
)

router = APIRouter(tags=["Admin"])


# ─── Company Management ───────────────────────────────────────────────────────

@router.get(
    "/companies",
    response_model=List[CompanyResponse],
    summary="List companies / tenants",
)
def list_companies(
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(require_company_admin),
):
    """
    List companies:
    - Platform Admin: lists all registered companies with user and workload counts.
    - Company Admin: lists only their own company.
    """
    if is_platform_admin(identity):
        tenants = db.query(TenantORM).order_by(TenantORM.created_at.desc()).all()
    else:
        tenants = db.query(TenantORM).filter(TenantORM.id == identity.tenant_id).all()

    result = []
    for t in tenants:
        user_count = db.query(UserORM).filter(UserORM.tenant_id == t.id).count()
        workload_count = db.query(JobORM).filter(JobORM.tenant_id == t.id).count()
        result.append(
            CompanyResponse(
                id=t.id,
                name=t.name,
                is_active=t.is_active,
                created_at=t.created_at,
                user_count=user_count,
                workload_count=workload_count,
            )
        )
    return result


@router.post(
    "/companies",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new company / tenant (Platform Admin only)",
)
def create_company(
    body: CompanyCreateRequest,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(require_platform_admin),
):
    """Platform Admin creates a new tenant organization."""
    # Generate tenant ID if not supplied
    company_id = body.id or f"tenant-{body.name.lower().replace(' ', '-')}"
    existing = db.query(TenantORM).filter(
        (TenantORM.id == company_id) | (TenantORM.name == body.name)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Company with ID '{company_id}' or name '{body.name}' already exists",
        )

    tenant = TenantORM(
        id=company_id,
        name=body.name,
        is_active=body.is_active,
        created_at=datetime.now(timezone.utc),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    return CompanyResponse(
        id=tenant.id,
        name=tenant.name,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        user_count=0,
        workload_count=0,
    )


@router.get(
    "/companies/{company_id}",
    response_model=CompanyResponse,
    summary="Get details of a company",
)
def get_company(
    company_id: str,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(require_company_admin),
):
    """Get company details. Enforces company isolation."""
    if not is_platform_admin(identity) and identity.tenant_id != company_id:
        raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")

    tenant = db.get(TenantORM, company_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")

    user_count = db.query(UserORM).filter(UserORM.tenant_id == tenant.id).count()
    workload_count = db.query(JobORM).filter(JobORM.tenant_id == tenant.id).count()
    return CompanyResponse(
        id=tenant.id,
        name=tenant.name,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        user_count=user_count,
        workload_count=workload_count,
    )


@router.put(
    "/companies/{company_id}",
    response_model=CompanyResponse,
    summary="Update company details",
)
def update_company(
    company_id: str,
    body: CompanyUpdateRequest,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(require_company_admin),
):
    """Update company details. Platform Admin or matching Company Admin."""
    if not is_platform_admin(identity) and identity.tenant_id != company_id:
        raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")

    tenant = db.get(TenantORM, company_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")

    if body.name is not None:
        tenant.name = body.name
    if body.is_active is not None:
        # Only platform admin can deactivate a company
        if not is_platform_admin(identity):
            raise HTTPException(status_code=403, detail="Only Platform Admins can change company active status")
        tenant.is_active = body.is_active

    db.commit()
    db.refresh(tenant)

    user_count = db.query(UserORM).filter(UserORM.tenant_id == tenant.id).count()
    workload_count = db.query(JobORM).filter(JobORM.tenant_id == tenant.id).count()
    return CompanyResponse(
        id=tenant.id,
        name=tenant.name,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        user_count=user_count,
        workload_count=workload_count,
    )


# ─── User Management ──────────────────────────────────────────────────────────

@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
)
def create_user(
    body: UserCreateRequest,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(require_company_admin),
):
    """
    Creates a user.
    - Platform Admin can create users for any company.
    - Company Admin can only create users within their own company.
    - Company Admin cannot create PLATFORM_ADMIN or ADMIN users.
    """
    if body.role == UserRole.PLATFORM_ADMIN and not is_platform_admin(identity):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Platform Admins can assign the PLATFORM_ADMIN role",
        )

    username = body.username or body.email.split("@")[0]

    existing = db.query(UserORM).filter(
        (UserORM.email == body.email) | (UserORM.username == username)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email '{body.email}' or username '{username}' already exists",
        )

    if is_platform_admin(identity):
        target_tenant = getattr(body, "tenant_id", None) or (identity.tenant_id if identity else None)
    else:
        if getattr(body, "tenant_id", None) and identity and body.tenant_id != identity.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Company Admins cannot create users in other tenants",
            )
        target_tenant = identity.tenant_id if identity else None

    # Resolve company name if tenant is set
    company_name = None
    if target_tenant:
        t = db.get(TenantORM, target_tenant)
        if t:
            company_name = t.name

    user = UserORM(
        username=username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
        team_id=body.team_id,
        tenant_id=target_tenant,
        company_name=company_name,
        approval_status=UserApprovalStatus.APPROVED.value,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    try:
        record_user_registered(
            db,
            username=user.username,
            role=role_str,
            team_id=user.team_id,
            status=UserApprovalStatus.APPROVED.value,
            tenant_id=user.tenant_id,
            actor=identity,
        )
    except Exception:
        pass

    return user


@router.get(
    "/users",
    response_model=List[UserResponse],
    summary="List users",
)
def list_users(
    tenant_id: Optional[str] = None,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(require_company_admin),
):
    """
    Lists users:
    - Platform Admin can list all users or filter by tenant_id.
    - Company Admin lists only users in their own company.
    """
    query = db.query(UserORM)
    if is_platform_admin(identity):
        if tenant_id:
            query = query.filter(UserORM.tenant_id == tenant_id)
    else:
        if tenant_id and identity and tenant_id != identity.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Company Admins cannot view users in other tenants",
            )
        query = query.filter(UserORM.tenant_id == (identity.tenant_id if identity else None))

    return query.order_by(UserORM.created_at.desc()).all()


@router.patch(
    "/users/{user_id}/status",
    response_model=UserResponse,
    summary="Update user approval, active state, or role",
)
@router.put(
    "/users/{user_id}/status",
    response_model=UserResponse,
    include_in_schema=False,
)
def update_user_status(
    user_id: int,
    body: UserStatusUpdateRequest,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(require_company_admin),
):
    """
    Approve, reject, activate, deactivate, or assign roles to users.
    Company Admin can only manage users in their own company.
    """
    user = db.get(UserORM, user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    if not is_platform_admin(identity) and user.tenant_id != identity.tenant_id:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    is_self = str(getattr(identity, "user_id", "")) == str(user_id)
    if is_self and body.role is not None:
        raise HTTPException(status_code=403, detail="You cannot change your own role")

    old_active = user.is_active
    old_approval = user.approval_status

    if body.approval_status is not None:
        status_norm = body.approval_status.upper()
        if status_norm not in ("APPROVED", "PENDING", "REJECTED"):
            raise HTTPException(status_code=400, detail="Invalid approval status. Must be APPROVED, PENDING, or REJECTED")
        user.approval_status = status_norm
        if status_norm == "APPROVED":
            user.is_active = True
        elif status_norm == "REJECTED":
            user.is_active = False

    if body.is_active is not None:
        user.is_active = body.is_active

    if body.role is not None:
        # Only platform admin can grant PLATFORM_ADMIN
        if body.role == UserRole.PLATFORM_ADMIN and not is_platform_admin(identity):
            raise HTTPException(status_code=403, detail="Only Platform Admins can assign the PLATFORM_ADMIN role")
        user.role = body.role

    db.commit()
    db.refresh(user)

    admin_username = getattr(identity, "username", "admin") if identity else "admin"
    became_active = (not old_active or old_approval == "PENDING") and user.is_active and user.approval_status == "APPROVED"
    became_inactive = old_active and not user.is_active
    try:
        if became_active:
            record_user_activated(db, username=user.username, activated_by=admin_username, tenant_id=user.tenant_id, actor=identity)
        elif became_inactive:
            record_user_deactivated(db, username=user.username, deactivated_by=admin_username, tenant_id=user.tenant_id, actor=identity)
    except Exception:
        pass

    if became_active or became_inactive:
        try:
            from app.notify.service import create_notification
            from app.shared.models import EventType
            create_notification(
                db,
                recipient_user_id=user.id,
                event_type=EventType.AUTH_USER_ACTIVATED if became_active else EventType.AUTH_USER_DEACTIVATED,
                category="ACCOUNT",
                severity="INFO" if became_active else "WARNING",
                title="Account activated" if became_active else "Account deactivated",
                message=(
                    f"Your GreenShift account was activated by {admin_username}."
                    if became_active
                    else f"Your GreenShift account was deactivated by {admin_username}."
                ),
                tenant_id=user.tenant_id,
                dedup_suffix=str(user.updated_at),
                email_required=True,
            )
        except Exception:
            pass

    return user


@router.delete(
    "/users/{user_id}",
    response_model=dict,
    summary="Deactivate a user",
)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(require_company_admin),
):
    """Deactivates a user. Cross-tenant -> 404."""
    user = db.get(UserORM, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    if not is_platform_admin(identity) and user.tenant_id != identity.tenant_id:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is already inactive")

    user.is_active = False
    db.commit()

    admin_username = getattr(identity, "username", "admin") if identity else "admin"
    try:
        record_user_deactivated(db, username=user.username, deactivated_by=admin_username, tenant_id=user.tenant_id, actor=identity)
    except Exception:
        pass

    return {"user_id": user_id, "status": "deactivated"}


# ─── API Key Management ────────────────────────────────────────────────────────

@router.post(
    "/api-keys",
    response_model=APIKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a new API key (raw key shown ONCE)",
)
def create_api_key(
    body: APIKeyCreateRequest,
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(require_company_admin),
):
    """
    Creates an API key for the admin's tenant.
    Platform Admin can specify any tenant; Company Admin is locked to own tenant.

    RULE 3: Role cannot be administrative (PLATFORM_ADMIN, COMPANY_ADMIN) — API keys are for automation only.
    Raw key is returned once and never stored; store it securely.
    """
    # RULE 3 enforcement
    if body.role in (UserRole.PLATFORM_ADMIN, UserRole.COMPANY_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "API keys cannot have administrative roles (PLATFORM_ADMIN, COMPANY_ADMIN). "
                "Use COMPANY_USER for service accounts."
            ),
        )

    if body.role not in API_KEY_ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role for API key. Allowed: {[r.value for r in API_KEY_ALLOWED_ROLES]}",
        )

    if is_platform_admin(identity):
        target_tenant = getattr(body, "tenant_id", None) or (identity.tenant_id if identity else None) or "tenant-default"
    else:
        if getattr(body, "tenant_id", None) and identity and body.tenant_id != identity.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Company Admins cannot create API keys for other tenants",
            )
        target_tenant = (identity.tenant_id if identity else None) or "tenant-default"

    # Verify tenant exists
    if not db.get(TenantORM, target_tenant):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tenant '{target_tenant}' does not exist.",
        )

    # Generate secure random key
    raw_key = f"gs_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    api_key_orm = APIKeyORM(
        id=key_id,
        key_hash=key_hash,
        tenant_id=target_tenant,
        role=body.role,
        label=body.label,
        is_active=True,
    )
    db.add(api_key_orm)
    db.commit()

    return APIKeyCreateResponse(
        key_id=key_id,
        api_key=raw_key,   # Shown ONCE — never stored
        tenant_id=target_tenant,
        role=body.role.value if hasattr(body.role, "value") else str(body.role),
        label=body.label,
        created_at=now,
    )


@router.get(
    "/api-keys",
    summary="List API keys for the admin's tenant",
)
def list_api_keys(
    tenant_id: Optional[str] = None,
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(require_company_admin),
):
    """ADMIN only. Lists all API keys for the admin's tenant (hashes never returned)."""
    query = db.query(APIKeyORM)
    if is_platform_admin(identity):
        if tenant_id:
            query = query.filter(APIKeyORM.tenant_id == tenant_id)
    else:
        if tenant_id and identity and tenant_id != identity.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Company Admins cannot view API keys in other tenants",
            )
        target_tenant = (identity.tenant_id if identity else None) or "tenant-default"
        query = query.filter(APIKeyORM.tenant_id == target_tenant)

    keys = query.order_by(APIKeyORM.created_at.desc()).all()
    return [
        {
            "id": k.id,
            "tenant_id": k.tenant_id,
            "role": k.role.value if hasattr(k.role, "value") else k.role,
            "label": k.label,
            "is_active": k.is_active,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used": k.last_used.isoformat() if k.last_used else None,
        }
        for k in keys
    ]


@router.delete(
    "/api-keys/{key_id}",
    response_model=dict,
    summary="Revoke an API key",
)
def revoke_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(require_company_admin),
):
    """ADMIN only. Revokes (deactivates) an API key. Cross-tenant -> 404."""
    api_key = db.get(APIKeyORM, key_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")

    # Tenant isolation
    if not is_platform_admin(identity) and identity and api_key.tenant_id != identity.tenant_id:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")

    if not api_key.is_active:
        raise HTTPException(status_code=400, detail="API key is already revoked")

    api_key.is_active = False
    db.commit()
    return {"key_id": key_id, "status": "revoked"}
