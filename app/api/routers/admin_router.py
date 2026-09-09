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
    hash_password,
    require_admin,
)
from app.shared.database import get_db
from app.shared.models import (
    API_KEY_ALLOWED_ROLES,
    APIKeyCreateRequest,
    APIKeyCreateResponse,
    APIKeyListItem,
    APIKeyORM,
    TenantUserResponse,
    UserCreateRequest,
    UserORM,
    UserRole,
)

router = APIRouter(tags=["Admin"])


# ─── User Management ──────────────────────────────────────────────────────────

@router.post(
    "/users",
    response_model=TenantUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user within the admin's tenant",
)
def create_user(
    body: UserCreateRequest,
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(require_admin),
):
    """
    ADMIN only. Creates a user scoped to the admin's own tenant.
    RULE 4: Cannot create users in other tenants.
    """
    # Derive username from email prefix if not provided
    username = body.username or body.email.split("@")[0]

    # Check uniqueness
    existing = db.query(UserORM).filter(
        (UserORM.email == body.email) | (UserORM.username == username)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email '{body.email}' or username '{username}' already exists",
        )

    tenant_id = identity.tenant_id if identity else None

    user = UserORM(
        username=username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
        team_id=body.team_id,
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get(
    "/users",
    response_model=List[TenantUserResponse],
    summary="List users in the admin's tenant",
)
def list_users(
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(require_admin),
):
    """ADMIN only. Lists all users in the admin's own tenant."""
    query = db.query(UserORM)
    if identity and identity.tenant_id:
        query = query.filter(UserORM.tenant_id == identity.tenant_id)
    return query.order_by(UserORM.created_at.desc()).all()


@router.delete(
    "/users/{user_id}",
    response_model=dict,
    summary="Deactivate a user in the admin's tenant",
)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(require_admin),
):
    """ADMIN only. Deactivates (soft-deletes) a user. Cross-tenant → 404."""
    user = db.get(UserORM, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    # Tenant isolation: 404 for cross-tenant
    if identity and user.tenant_id and user.tenant_id != identity.tenant_id:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is already inactive")

    user.is_active = False
    db.commit()
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
    identity: Optional[AuthenticatedIdentity] = Depends(require_admin),
):
    """
    ADMIN only. Creates an API key for the admin's tenant.

    RULE 3: Role cannot be ADMIN — API keys are for automation only.
    Raw key is returned once and never stored; store it securely.
    """
    # RULE 3 enforcement
    if body.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "API keys cannot have ADMIN role. "
                "Use OPERATOR, USER, or VIEWER for service accounts."
            ),
        )

    if body.role not in API_KEY_ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role for API key. Allowed: {[r.value for r in API_KEY_ALLOWED_ROLES]}",
        )

    tenant_id = identity.tenant_id if identity else "tenant-default"
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin user has no associated tenant. Run the seed script first.",
        )

    # Generate secure random key
    raw_key = f"gs_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    api_key_orm = APIKeyORM(
        id=key_id,
        key_hash=key_hash,
        tenant_id=tenant_id,
        role=body.role,
        label=body.label,
        is_active=True,
    )
    db.add(api_key_orm)
    db.commit()

    return APIKeyCreateResponse(
        key_id=key_id,
        api_key=raw_key,   # Shown ONCE — never stored
        tenant_id=tenant_id,
        role=body.role.value,
        label=body.label,
        created_at=now,
    )


@router.get(
    "/api-keys",
    summary="List API keys for the admin's tenant",
)
def list_api_keys(
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(require_admin),
):
    """ADMIN only. Lists all API keys for the admin's tenant (hashes never returned)."""
    query = db.query(APIKeyORM)
    if identity and identity.tenant_id:
        query = query.filter(APIKeyORM.tenant_id == identity.tenant_id)
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
    identity: Optional[AuthenticatedIdentity] = Depends(require_admin),
):
    """ADMIN only. Revokes (deactivates) an API key. Cross-tenant → 404."""
    api_key = db.get(APIKeyORM, key_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")

    # Tenant isolation
    if identity and api_key.tenant_id != identity.tenant_id:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")

    if not api_key.is_active:
        raise HTTPException(status_code=400, detail="API key is already revoked")

    api_key.is_active = False
    db.commit()
    return {"key_id": key_id, "status": "revoked"}
