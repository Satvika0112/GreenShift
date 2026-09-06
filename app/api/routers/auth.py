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
)
from app.shared.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_roles,
)
from app.trust.service import (
    record_login_success,
    record_login_failure,
    record_user_registered,
)

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
    user = UserORM(
        username=body.username,
        email=body.email,
        hashed_password=hashed_pw,
        role=body.role,
        team_id=body.team_id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    try:
        record_user_registered(db, username=user.username, role=role_str, team_id=user.team_id)
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

    if not user.is_active:
        try:
            record_login_failure(db, username_attempted=body.username, reason="User account is deactivated", ip_address=client_ip)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=role_str,
        team_id=user.team_id,
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
    summary="List all users (Admin only)",
)
def list_users(
    db: Session = Depends(get_db),
    current_admin: UserORM = Depends(require_roles(UserRole.ADMIN)),
):
    """Return all registered user profiles. Restricted to ADMIN role only."""
    users = db.query(UserORM).all()
    return users
