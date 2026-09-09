"""
GreenShift — Authentication & JWT Security Layer

Provides bcrypt password hashing, JWT token creation/decoding,
and FastAPI dependency extractors for role-based access control.

Multi-tenant dual-channel auth (Phase 1):
  1. Authorization: Bearer <JWT>  → JWT decode → user lookup
  2. X-API-Key: <key>             → SHA-256 hash → api_key lookup
  3. AUTH_ENABLED=false            → return None  (dev mode only)
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Callable, Any
import secrets
import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Security, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.database import get_db
from app.shared.models import UserORM, UserRole, APIKeyORM

# OAuth2 / HTTPBearer scheme
http_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a plaintext password securely using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(
    user_id: int,
    username: str,
    role: str,
    team_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    company_name: Optional[str] = None,
    approval_status: str = "APPROVED",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token containing identity, role, and company information."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.jwt_expire_minutes)

    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "username": username,
        "role": role,
        "team_id": team_id,
        "tenant_id": tenant_id,
        "company_name": company_name,
        "approval_status": approval_status,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }

    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─────────────────────────────────────────────────────────────────────────────
# AuthenticatedIdentity — unified identity from JWT or API key
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AuthenticatedIdentity:
    """Resolved identity for the current request, regardless of auth method."""
    user_id: str
    username: str = ""
    tenant_id: Optional[str] = None
    company_name: Optional[str] = None
    role: UserRole = UserRole.USER
    approval_status: str = "APPROVED"
    auth_method: str = "jwt"   # "jwt" or "api_key"


def is_platform_admin(identity_or_user: Any) -> bool:
    """True if entity is a Platform Admin (global admin)."""
    if not identity_or_user:
        return False
    role = getattr(identity_or_user, "role", None)
    role_val = role.value if hasattr(role, "value") else str(role)
    tenant_id = getattr(identity_or_user, "tenant_id", None)
    return role_val in (UserRole.PLATFORM_ADMIN.value, UserRole.ADMIN.value) and (
        tenant_id is None or role_val == UserRole.PLATFORM_ADMIN.value
    )


def is_company_admin(identity_or_user: Any) -> bool:
    """True if entity is a Company Admin or Platform Admin."""
    if not identity_or_user:
        return False
    if is_platform_admin(identity_or_user):
        return True
    role = getattr(identity_or_user, "role", None)
    role_val = role.value if hasattr(role, "value") else str(role)
    return role_val in (
        UserRole.COMPANY_ADMIN.value,
        UserRole.ADMIN.value,
    )


def is_company_member(identity_or_user: Any) -> bool:
    """True if entity is a member of the company (or Platform Admin)."""
    if not identity_or_user:
        return False
    if is_platform_admin(identity_or_user):
        return True
    role = getattr(identity_or_user, "role", None)
    role_val = role.value if hasattr(role, "value") else str(role)
    return role_val in (
        UserRole.COMPANY_USER.value,
        UserRole.USER.value,
        UserRole.OPERATOR.value,
        UserRole.VIEWER.value,
        UserRole.COMPANY_ADMIN.value,
        UserRole.TEAM_LEAD.value,
        UserRole.ADMIN.value,
    )


async def get_current_identity(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(http_bearer),
    db: Session = Depends(get_db),
) -> Optional[AuthenticatedIdentity]:
    """
    Resolve AuthenticatedIdentity from request. Tried in order:
      1. Authorization: Bearer <JWT> → decode → user lookup
      2. X-API-Key: <key>            → SHA-256 hash → api_key lookup
      3. AUTH_ENABLED=false          → return None (dev mode passthrough)

    Returns AuthenticatedIdentity or raises 401/403.
    """
    if not settings.auth_enabled:
        return None  # Dev mode: all endpoints open

    # 1. Try JWT Bearer token
    if credentials and credentials.credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            user_id = payload.get("user_id")
            if user_id is not None:
                user = db.get(UserORM, int(user_id))
                if user:
                    if not user.is_active:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="User account is deactivated",
                        )
                    appr_status = getattr(user, "approval_status", "APPROVED") or "APPROVED"
                    if appr_status == "PENDING":
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="User account is pending approval",
                        )
                    if appr_status == "REJECTED":
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="User account registration was declined",
                        )

                    role_enum = user.role if isinstance(user.role, UserRole) else UserRole(str(user.role))
                    return AuthenticatedIdentity(
                        user_id=str(user.id),
                        username=user.username,
                        tenant_id=getattr(user, "tenant_id", None),
                        company_name=user.company_name if hasattr(user, "company_name") else None,
                        role=role_enum,
                        approval_status=appr_status,
                        auth_method="jwt",
                    )
        except HTTPException:
            raise
        except Exception:
            pass

    # 2. Try X-API-Key header
    api_key_raw = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if api_key_raw:
        key_hash = hashlib.sha256(api_key_raw.encode()).hexdigest()
        api_key = db.query(APIKeyORM).filter(
            APIKeyORM.key_hash == key_hash,
            APIKeyORM.is_active == True,  # noqa: E712
        ).first()
        if api_key:
            api_key.last_used = datetime.now(timezone.utc)
            try:
                db.commit()
            except Exception:
                db.rollback()
            role_enum = api_key.role if isinstance(api_key.role, UserRole) else UserRole(str(api_key.role))
            return AuthenticatedIdentity(
                user_id=api_key.id,
                username=f"api_key_{api_key.id[:8]}",
                tenant_id=api_key.tenant_id,
                company_name=api_key.tenant.name if getattr(api_key, "tenant", None) else None,
                role=role_enum,
                approval_status="APPROVED",
                auth_method="api_key",
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication token required",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Centralized Reusable Authorization Dependencies
# ─────────────────────────────────────────────────────────────────────────────

async def require_platform_admin(
    identity: Optional[AuthenticatedIdentity] = Depends(get_current_identity),
) -> Optional[AuthenticatedIdentity]:
    """Dependency: Requires Platform Admin privileges."""
    if identity is None:
        return None
    if not is_platform_admin(identity):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform Admin privileges required for this operation",
        )
    return identity


async def require_company_admin(
    identity: Optional[AuthenticatedIdentity] = Depends(get_current_identity),
) -> Optional[AuthenticatedIdentity]:
    """Dependency: Requires Company Admin or Platform Admin privileges."""
    if identity is None:
        return None
    if not is_company_admin(identity):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company Admin or Platform Admin privileges required",
        )
    return identity


async def require_company_member(
    identity: Optional[AuthenticatedIdentity] = Depends(get_current_identity),
) -> Optional[AuthenticatedIdentity]:
    """Dependency: Requires active company membership."""
    if identity is None:
        return None
    if not is_company_member(identity):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company membership required for this operation",
        )
    return identity


def require_role(*allowed_roles: UserRole):
    """
    Dependency factory enforcing role-based access control via AuthenticatedIdentity.
    Returns None in dev mode (AUTH_ENABLED=false).
    """
    allowed_values = {r.value if isinstance(r, UserRole) else str(r) for r in allowed_roles}

    async def checker(
        identity: Optional[AuthenticatedIdentity] = Depends(get_current_identity),
    ) -> Optional[AuthenticatedIdentity]:
        if identity is None:
            return None  # Dev mode passthrough

        role_val = identity.role.value if hasattr(identity.role, "value") else str(identity.role)

        # Platform admin always passes
        if is_platform_admin(identity):
            return identity

        # Company admin passes company admin and user checks
        if is_company_admin(identity) and any(
            r in allowed_values
            for r in (
                UserRole.COMPANY_ADMIN.value,
                UserRole.TEAM_LEAD.value,
                UserRole.COMPANY_USER.value,
                UserRole.USER.value,
                UserRole.OPERATOR.value,
                UserRole.VIEWER.value,
            )
        ):
            return identity

        # Company user passes user and viewer checks
        if is_company_member(identity) and any(
            r in allowed_values
            for r in (
                UserRole.COMPANY_USER.value,
                UserRole.USER.value,
                UserRole.VIEWER.value,
            )
        ):
            return identity

        if role_val not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{role_val}' is not authorized. "
                    f"Required: {[r.value if hasattr(r, 'value') else str(r) for r in allowed_roles]}"
                ),
            )
        return identity

    return checker


# Convenience role dependency singletons
require_admin    = require_role(UserRole.ADMIN, UserRole.PLATFORM_ADMIN)
require_operator = require_role(UserRole.ADMIN, UserRole.PLATFORM_ADMIN, UserRole.OPERATOR, UserRole.COMPANY_ADMIN)
require_user     = require_role(UserRole.ADMIN, UserRole.PLATFORM_ADMIN, UserRole.COMPANY_ADMIN, UserRole.COMPANY_USER, UserRole.OPERATOR, UserRole.USER, UserRole.TEAM_LEAD)
require_viewer   = require_role(UserRole.ADMIN, UserRole.PLATFORM_ADMIN, UserRole.COMPANY_ADMIN, UserRole.COMPANY_USER, UserRole.OPERATOR, UserRole.USER, UserRole.TEAM_LEAD, UserRole.VIEWER)


# ─────────────────────────────────────────────────────────────────────────────
# Legacy dependencies — preserved for backward compatibility
# ─────────────────────────────────────────────────────────────────────────────

def get_current_user(
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> UserORM:
    """FastAPI dependency: Extract and validate the currently authenticated user."""
    if not auth_header or not auth_header.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header.credentials
    payload = decode_access_token(token)
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(UserORM, int(user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    appr_status = getattr(user, "approval_status", "APPROVED") or "APPROVED"
    if appr_status == "PENDING":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is pending approval",
        )
    if appr_status == "REJECTED":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account registration was declined",
        )

    return user


def get_current_active_user(
    current_user: UserORM = Depends(get_current_user),
) -> UserORM:
    """Dependency that guarantees the current user is active."""
    return current_user


def require_roles(*allowed_roles: UserRole) -> Callable:
    """Legacy dependency factory enforcing role-based access control (RBAC)."""
    allowed_values = {r.value if isinstance(r, UserRole) else str(r) for r in allowed_roles}

    def role_checker(
        current_user: UserORM = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> UserORM:
        user_role_val = current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role)

        # Platform Admin always passes
        if is_platform_admin(current_user):
            return current_user

        # Company Admin passes company admin and user checks
        if is_company_admin(current_user) and any(
            r in allowed_values
            for r in (
                UserRole.COMPANY_ADMIN.value,
                UserRole.TEAM_LEAD.value,
                UserRole.COMPANY_USER.value,
                UserRole.USER.value,
                UserRole.OPERATOR.value,
                UserRole.VIEWER.value,
            )
        ):
            return current_user

        # Company user passes user and viewer checks
        if is_company_member(current_user) and any(
            r in allowed_values
            for r in (
                UserRole.COMPANY_USER.value,
                UserRole.USER.value,
                UserRole.VIEWER.value,
            )
        ):
            return current_user

        if user_role_val not in allowed_values:
            try:
                from app.trust.service import record_access_denied
                record_access_denied(
                    db,
                    username=current_user.username,
                    role=user_role_val,
                    endpoint="RBAC_CHECK",
                    reason=f"Role '{user_role_val}' not in allowed roles: {list(allowed_values)}",
                    team_id=current_user.team_id,
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role '{user_role_val}'. Required: {list(allowed_values)}",
            )
        return current_user

    return role_checker


def verify_internal_service_token(token: Optional[str]) -> bool:
    """
    Validate a provided internal service token against the configured INTERNAL_SERVICE_KEY.
    Uses constant-time comparison to prevent timing attacks.
    """
    configured_key = settings.internal_service_key
    if not configured_key or not token:
        return False
    return secrets.compare_digest(token, configured_key)


def require_internal_service_token(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Service-Key"),
) -> str:
    """
    FastAPI dependency for internal microservice-to-microservice authentication.
    Requires a valid 'X-Internal-Service-Key' matching settings.internal_service_key.
    """
    if not settings.internal_service_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal service authentication is not enabled or configured",
        )
    if not x_internal_key or not verify_internal_service_token(x_internal_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal service token",
            headers={"WWW-Authenticate": "Internal-Key"},
        )
    return x_internal_key


def seed_default_users(db: Session) -> None:
    """Ensure standard system companies and users exist for immediate authentication."""
    from app.shared.models import TenantORM
    default_tenants = [
        ("tenant-default", "GreenShift Platform"),
        ("tenant-acme", "Acme Compute Corp"),
        ("tenant-globex", "Globex Cloud Services"),
    ]
    for tid, tname in default_tenants:
        if not db.query(TenantORM).filter(TenantORM.id == tid).first():
            db.add(TenantORM(id=tid, name=tname, is_active=True))
    try:
        db.commit()
    except Exception:
        db.rollback()

    default_users = [
        ("admin", "admin@greenshift.io", "admin123", UserRole.PLATFORM_ADMIN, "platform", None),
        ("company_admin", "company_admin@acme.com", "admin123", UserRole.COMPANY_ADMIN, "team-acme", "tenant-acme"),
        ("company_user", "company_user@acme.com", "user123", UserRole.COMPANY_USER, "team-acme", "tenant-acme"),
        ("lead_a", "lead_a@greenshift.io", "lead123", UserRole.COMPANY_ADMIN, "team-a", "tenant-default"),
        ("lead_b", "lead_b@greenshift.io", "lead123", UserRole.COMPANY_ADMIN, "team-b", "tenant-default"),
        ("operator", "operator@greenshift.io", "operator123", UserRole.OPERATOR, "operations", "tenant-default"),
        ("viewer", "viewer@greenshift.io", "viewer123", UserRole.VIEWER, "general", "tenant-default"),
    ]
    for username, email, pwd, role, team, tenant_id in default_users:
        existing = db.query(UserORM).filter(UserORM.username == username).first()
        if not existing:
            db.add(
                UserORM(
                    username=username,
                    email=email,
                    hashed_password=hash_password(pwd),
                    role=role,
                    team_id=team,
                    tenant_id=tenant_id,
                    approval_status="APPROVED",
                    is_active=True,
                )
            )
        else:
            # Backfill approval_status and tenant_id if missing
            if not getattr(existing, "approval_status", None):
                existing.approval_status = "APPROVED"
            if tenant_id and not existing.tenant_id:
                existing.tenant_id = tenant_id
    try:
        db.commit()
    except Exception:
        db.rollback()
