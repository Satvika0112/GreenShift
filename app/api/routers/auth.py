"""
GreenShift — Authentication API Router

Endpoints:
- POST /auth/register: User account creation
- POST /auth/login: JWT token authentication
- GET  /auth/me: Retrieve authenticated profile
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.shared.config import settings
from app.shared.database import get_db
from app.shared.models import (
    UserORM,
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
)

router = APIRouter(tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
def register(request: UserRegisterRequest, db: Session = Depends(get_db)):
    """Create a new user with secure bcrypt password hashing."""
    # Check if username or email already exists
    existing = db.query(UserORM).filter(
        or_(UserORM.username == request.username, UserORM.email == request.email)
    ).first()

    if existing:
        if existing.username == request.username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{request.username}' is already taken",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{request.email}' is already registered",
            )

    hashed_pw = hash_password(request.password)
    user = UserORM(
        username=request.username,
        email=request.email,
        hashed_password=hashed_pw,
        role=request.role,
        team_id=request.team_id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate user and obtain JWT token",
)
def login(request: UserLoginRequest, db: Session = Depends(get_db)):
    """Authenticate with username/email and password to receive a JWT access token."""
    user = db.query(UserORM).filter(
        or_(UserORM.username == request.username, UserORM.email == request.username)
    ).first()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        team_id=user.team_id,
    )

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
    summary="List all users",
)
def list_users(db: Session = Depends(get_db)):
    """Return all registered user profiles."""
    users = db.query(UserORM).all()
    return users
