"""
GreenShift — Authentication & JWT Security Layer

Provides bcrypt password hashing, JWT token creation/decoding,
and FastAPI dependency extractors for role-based access control.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List, Callable
import secrets
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.database import get_db
from app.shared.models import UserORM, UserRole

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
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token containing minimal identity information."""
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

    return user


def get_current_active_user(
    current_user: UserORM = Depends(get_current_user),
) -> UserORM:
    """Dependency that guarantees the current user is active."""
    return current_user


def require_roles(*allowed_roles: UserRole) -> Callable:
    """Dependency factory enforcing role-based access control (RBAC)."""
    allowed_values = {r.value if isinstance(r, UserRole) else str(r) for r in allowed_roles}

    def role_checker(
        current_user: UserORM = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> UserORM:
        user_role_val = current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role)
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
    """Ensure standard system users exist for immediate authentication."""
    default_users = [
        ("admin", "admin@greenshift.io", "admin123", UserRole.ADMIN, "engineering"),
        ("lead_a", "lead_a@greenshift.io", "lead123", UserRole.TEAM_LEAD, "team-a"),
        ("lead_b", "lead_b@greenshift.io", "lead123", UserRole.TEAM_LEAD, "team-b"),
        ("operator", "operator@greenshift.io", "operator123", UserRole.OPERATOR, "operations"),
        ("viewer", "viewer@greenshift.io", "viewer123", UserRole.VIEWER, "general"),
    ]
    for username, email, pwd, role, team in default_users:
        if not db.query(UserORM).filter(UserORM.username == username).first():
            db.add(
                UserORM(
                    username=username,
                    email=email,
                    hashed_password=hash_password(pwd),
                    role=role,
                    team_id=team,
                    is_active=True,
                )
            )
    try:
        db.commit()
    except Exception:
        db.rollback()

