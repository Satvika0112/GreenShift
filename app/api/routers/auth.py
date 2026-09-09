"""
GreenShift — Authentication API Router

Endpoints:
- POST /auth/register: User account creation
- POST /auth/login: JWT token authentication
- GET  /auth/me: Retrieve authenticated profile
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.shared.config import settings
from app.shared.database import get_db
from app.shared.rate_limiter import limiter
from app.shared.models import (
    UserORM,
    UserRole,
    UserRegisterRequest,
    UserLoginRequest,
    UserResponse,
    TokenResponse,
    LoginRequest,
    LoginResponse,
)
from app.shared.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_roles,
    is_platform_admin,
    is_company_admin,
)
from app.trust.service import (
    record_login_success,
    record_login_failure,
    record_user_registered,
)
from app.shared.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
@limiter.limit("10/minute")
def register(
    request: Request,
    body: UserRegisterRequest,
    db: Session = Depends(get_db),
):
    """Create a new user with secure bcrypt password hashing."""
    # Check if username or email already exists
    existing = db.query(UserORM).filter(
        or_(UserORM.username == body.username, UserORM.email == body.email)
    ).first()

    if existing:
        if existing.username == body.username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{body.username}' is already taken",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{body.email}' is already registered",
            )

    hashed_pw = hash_password(body.password)
    # When auth is enabled (production), self-registration creates inactive users pending approval
    # When auth is disabled (local dev), user is immediately active
    is_active = not settings.auth_enabled
    approval_status = "PENDING" if settings.auth_enabled else "APPROVED"

    user = UserORM(
        username=body.username,
        email=body.email,
        hashed_password=hashed_pw,
        role=UserRole.VIEWER,
        team_id=body.team_id,
        is_active=is_active,
        approval_status=approval_status,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    role_str = UserRole.VIEWER.value
    try:
        record_user_registered(
            db,
            username=user.username,
            role=role_str,
            team_id=user.team_id,
            status=approval_status,
            tenant_id=user.tenant_id,
        )
    except Exception:
        pass

    if approval_status == "PENDING":
        try:
            from app.notify.service import create_notification, resolve_platform_admin_user_ids
            from app.shared.models import EventType
            for admin_id in resolve_platform_admin_user_ids(db):
                create_notification(
                    db,
                    recipient_user_id=admin_id,
                    event_type=EventType.AUTH_USER_REGISTERED,
                    category="ACCOUNT",
                    severity="INFO",
                    title="New access request pending review",
                    message=f"User '{user.username}' ({user.email}) has requested access and is awaiting approval.",
                    dedup_suffix=user.username,
                    email_required=False,
                )
        except Exception as exc:
            logger.warning("Notification failed for pending registration %s: %s", user.username, exc)

    return user


@router.post(
    "/admin/create-user",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user with an assigned role (Admin only)",
    deprecated=True,
)
@limiter.limit("30/minute")
def admin_create_user(
    request: Request,
    body: UserRegisterRequest,
    current_admin: UserORM = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Deprecated, tenant-safe alias of the authoritative `POST /admin/users`.
    A Company Admin may only create users within their own tenant and may
    never assign PLATFORM_ADMIN/ADMIN. A Platform Admin (role=ADMIN or
    PLATFORM_ADMIN with no tenant) may assign any role for any tenant.
    """
    if not is_company_admin(current_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company Admin or Platform Admin privileges required",
        )

    existing = db.query(UserORM).filter(
        or_(UserORM.username == body.username, UserORM.email == body.email)
    ).first()

    if existing:
        if existing.username == body.username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{body.username}' is already taken",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{body.email}' is already registered",
            )

    assigned_role = body.role if body.role is not None else UserRole.VIEWER
    caller_is_platform_admin = is_platform_admin(current_admin)

    if assigned_role in (UserRole.PLATFORM_ADMIN, UserRole.ADMIN) and not caller_is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Platform Admins can assign PLATFORM_ADMIN or ADMIN roles",
        )

    requested_tenant = getattr(body, "tenant_id", None)
    if caller_is_platform_admin:
        target_tenant = requested_tenant or getattr(current_admin, "tenant_id", None)
    else:
        if requested_tenant and requested_tenant != current_admin.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Company Admins cannot create users in other tenants",
            )
        target_tenant = current_admin.tenant_id

    hashed_pw = hash_password(body.password)
    user = UserORM(
        username=body.username,
        email=body.email,
        hashed_password=hashed_pw,
        role=assigned_role,
        team_id=body.team_id,
        tenant_id=target_tenant,
        approval_status="APPROVED",
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
            status="APPROVED",
            tenant_id=user.tenant_id,
        )
    except Exception:
        pass

    return user



@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate user and obtain JWT token",
)
@limiter.limit("10/minute")
def login(
    request: Request,
    body: UserLoginRequest,
    db: Session = Depends(get_db),
):
    """Authenticate with username/email and password to receive a JWT access token."""
    client_ip = getattr(request.client, "host", None) if request.client else None
    user = db.query(UserORM).filter(
        or_(UserORM.username == body.username, UserORM.email == body.username)
    ).first()

    if not user or not verify_password(body.password, user.hashed_password):
        try:
            record_login_failure(db, username_attempted=body.username, ip_address=client_ip)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    appr_status = getattr(user, "approval_status", "APPROVED") or "APPROVED"

    if not user.is_active or appr_status == "PENDING":
        if not user.is_active and appr_status == "APPROVED":
            reason = "User account is deactivated"
        else:
            reason = "Account pending approval"
        try:
            record_login_failure(db, username_attempted=body.username, reason=reason, ip_address=client_ip)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=reason,
        )

    if appr_status == "REJECTED":
        try:
            record_login_failure(db, username_attempted=body.username, reason="User account was rejected", ip_address=client_ip)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account registration was declined",
        )

    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    tenant_id = getattr(user, "tenant_id", None)
    company_name = user.company_name if hasattr(user, "company_name") else None
    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=role_str,
        team_id=user.team_id,
        tenant_id=tenant_id,
        company_name=company_name,
        approval_status=appr_status,
    )

    try:
        record_login_success(db, username=user.username, role=role_str, team_id=user.team_id, ip_address=client_ip)
    except Exception:
        pass

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60,
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
def get_me(current_user: UserORM = Depends(get_current_user)):
    """Return the profile of the currently authenticated user."""
    return current_user


@router.get(
    "/users",
    response_model=List[UserResponse],
    summary="List all users (Legacy alias -> redirects to /api/v1/admin/users)",
    deprecated=True,
)
def list_users_legacy(
    db: Session = Depends(get_db),
    current_admin: UserORM = Depends(require_roles(UserRole.ADMIN, UserRole.PLATFORM_ADMIN, UserRole.COMPANY_ADMIN)),
):
    """Deprecated legacy endpoint: please use /api/v1/admin/users."""
    query = db.query(UserORM)
    if current_admin.tenant_id and current_admin.role not in (UserRole.ADMIN, UserRole.PLATFORM_ADMIN):
        query = query.filter(UserORM.tenant_id == current_admin.tenant_id)
    return query.all()


@router.post(
    "/login-email",
    response_model=LoginResponse,
    summary="Authenticate via email + password (multi-tenant)",
)
def login_email(
    request: Request,
    body: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Email-based login for multi-tenant auth.
    Returns JWT with tenant_id embedded for downstream tenant-scoping.
    """
    client_ip = getattr(request.client, "host", None) if request.client else None
    user = db.query(UserORM).filter(UserORM.email == body.email).first()

    if not user or not verify_password(body.password, user.hashed_password):
        try:
            record_login_failure(db, username_attempted=body.email, ip_address=client_ip)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    appr_status = getattr(user, "approval_status", "APPROVED") or "APPROVED"

    if not user.is_active or appr_status == "PENDING":
        if not user.is_active and appr_status == "APPROVED":
            reason = "User account is deactivated"
        else:
            reason = "Account pending approval"
        try:
            record_login_failure(db, username_attempted=body.email, reason=reason, ip_address=client_ip)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=reason,
        )

    if appr_status == "REJECTED":
        try:
            record_login_failure(db, username_attempted=body.email, reason="User account was rejected", ip_address=client_ip)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account registration was declined",
        )

    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    tenant_id = getattr(user, "tenant_id", None)
    company_name = user.company_name if hasattr(user, "company_name") else None
    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=role_str,
        team_id=user.team_id,
        tenant_id=tenant_id,
        company_name=company_name,
        approval_status=appr_status,
    )

    try:
        record_login_success(db, username=user.username, role=role_str, team_id=user.team_id, ip_address=client_ip)
    except Exception:
        pass

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        tenant_id=tenant_id,
        role=role_str,
        expires_in=settings.jwt_expire_minutes * 60,
    )
