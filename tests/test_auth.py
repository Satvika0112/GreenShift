"""
Tests for GreenShift Authentication & RBAC Foundation

Covers:
- Password hashing & verification
- User registration (POST /auth/register and /api/v1/auth/register)
- Duplicate handling (username and email conflicts)
- User login with password verification (POST /auth/login)
- Invalid credentials & deactivated user handling
- JWT generation, decoding, expiry, and secret handling
- Protected endpoints (/auth/me) with valid, missing, invalid, and expired tokens
- Role-based access control (RBAC) dependency verification
"""

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends, status
import jwt

from app.api.main import app
from app.shared.config import settings
from app.shared.database import init_db, get_db, SessionLocal
from app.shared.models import UserORM, UserRole
from app.shared.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    get_current_user,
    get_current_active_user,
    require_roles,
)


@pytest.fixture(autouse=True)
def setup_auth_db():
    """Ensure database tables exist and clean up users table before/after each test."""
    init_db()
    db = SessionLocal()
    try:
        db.query(UserORM).delete()
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        db.query(UserORM).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def client():
    return TestClient(app)


# ====================================================================
# 1. Password Hashing Security Unit Tests
# ====================================================================

def test_password_hashing_and_salting():
    pwd = "SecurePassword123!"
    hash1 = hash_password(pwd)
    hash2 = hash_password(pwd)

    # Different salts must produce distinct hashes
    assert hash1 != hash2
    assert hash1 != pwd
    assert hash2 != pwd

    # Both must verify successfully
    assert verify_password(pwd, hash1) is True
    assert verify_password(pwd, hash2) is True

    # Incorrect password must fail verification
    assert verify_password("WrongPassword!", hash1) is False
    assert verify_password("", hash1) is False


# ====================================================================
# 2. Registration Tests
# ====================================================================

def test_user_registration_success(client):
    payload = {
        "username": "alice_admin",
        "email": "alice@greenshift.io",
        "password": "SuperSecretPassword123!",
        "role": "PLATFORM_ADMIN",
        "team_id": "team-core",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["username"] == "alice_admin"
    assert data["email"] == "alice@greenshift.io"
    assert data["role"] == "COMPANY_USER"  # Fixed: public registration always assigns COMPANY_USER
    assert data["team_id"] == "team-core"
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data

    # Security check: Password or password hash must NEVER be exposed in response
    assert "password" not in data
    assert "hashed_password" not in data


def test_user_registration_api_v1_prefix(client):
    payload = {
        "username": "bob_operator",
        "email": "bob@greenshift.io",
        "password": "OperatorSecretPassword123!",
        "role": "COMPANY_ADMIN",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "bob_operator"
    assert data["role"] == "COMPANY_USER"  # Fixed: public registration always assigns COMPANY_USER


def test_user_registration_duplicate_username(client):
    payload = {
        "username": "charlie_lead",
        "email": "charlie1@greenshift.io",
        "password": "Password123!",
        "role": "COMPANY_ADMIN",
    }
    res1 = client.post("/auth/register", json=payload)
    assert res1.status_code == 201

    # Attempt same username with different email
    payload_dup = {
        "username": "charlie_lead",
        "email": "charlie2@greenshift.io",
        "password": "Password456!",
        "role": "COMPANY_ADMIN",
    }
    res2 = client.post("/auth/register", json=payload_dup)
    assert res2.status_code == 409
    assert "already taken" in res2.json()["detail"].lower()


def test_user_registration_duplicate_email(client):
    payload = {
        "username": "david_user",
        "email": "david@greenshift.io",
        "password": "Password123!",
        "role": "COMPANY_USER",
    }
    res1 = client.post("/auth/register", json=payload)
    assert res1.status_code == 201

    # Attempt different username with same email
    payload_dup = {
        "username": "david_alternate",
        "email": "david@greenshift.io",
        "password": "Password456!",
        "role": "COMPANY_USER",
    }
    res2 = client.post("/auth/register", json=payload_dup)
    assert res2.status_code == 409
    assert "already registered" in res2.json()["detail"].lower()


def test_user_registration_invalid_role(client):
    payload = {
        "username": "invalid_role_user",
        "email": "invalid@greenshift.io",
        "password": "Password123!",
        "role": "SUPER_USER_NONEXISTENT",
    }
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 422


# ====================================================================
# 3. Login Tests
# ====================================================================

def test_user_login_success_with_username(client):
    # Register user
    client.post("/auth/register", json={
        "username": "eva_viewer",
        "email": "eva@greenshift.io",
        "password": "ViewerPassword123!",
        "role": "COMPANY_USER",
        "team_id": "analytics",
    })

    # Login with username
    login_res = client.post("/auth/login", json={
        "username": "eva_viewer",
        "password": "ViewerPassword123!",
    })
    assert login_res.status_code == 200
    data = login_res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == settings.jwt_expire_minutes * 60
    assert data["user"]["username"] == "eva_viewer"
    assert data["user"]["role"] == "COMPANY_USER"

    # Decode and verify JWT payload
    payload = jwt.decode(
        data["access_token"],
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert payload["username"] == "eva_viewer"
    assert payload["role"] == "COMPANY_USER"
    assert payload["team_id"] == "analytics"
    assert "user_id" in payload


def test_user_login_success_with_email(client):
    client.post("/auth/register", json={
        "username": "frank_lead",
        "email": "frank@greenshift.io",
        "password": "FrankPassword123!",
        "role": "COMPANY_ADMIN",
    })

    # Login using email as identifier
    login_res = client.post("/auth/login", json={
        "username": "frank@greenshift.io",
        "password": "FrankPassword123!",
    })
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()


def test_user_login_invalid_password(client):
    client.post("/auth/register", json={
        "username": "grace_op",
        "email": "grace@greenshift.io",
        "password": "CorrectPassword123!",
        "role": "COMPANY_USER",
    })

    login_res = client.post("/auth/login", json={
        "username": "grace_op",
        "password": "WrongPassword999!",
    })
    assert login_res.status_code == 401
    assert "invalid username or password" in login_res.json()["detail"].lower()


def test_user_login_nonexistent_user(client):
    login_res = client.post("/auth/login", json={
        "username": "does_not_exist",
        "password": "AnyPassword123!",
    })
    assert login_res.status_code == 401
    assert "invalid username or password" in login_res.json()["detail"].lower()


def test_user_login_deactivated_user(client):
    # Register user
    reg = client.post("/auth/register", json={
        "username": "inactive_user",
        "email": "inactive@greenshift.io",
        "password": "Password123!",
        "role": "COMPANY_USER",
    })
    user_id = reg.json()["id"]

    # Deactivate in database
    db = SessionLocal()
    try:
        user = db.get(UserORM, user_id)
        user.is_active = False
        db.commit()
    finally:
        db.close()

    # Login should be rejected
    login_res = client.post("/auth/login", json={
        "username": "inactive_user",
        "password": "Password123!",
    })
    assert login_res.status_code == 403
    assert "deactivated" in login_res.json()["detail"].lower()


# ====================================================================
# 4. Protected Endpoints & JWT Security Tests
# ====================================================================

def test_protected_endpoint_with_valid_token(client):
    # Register & Login
    client.post("/auth/register", json={
        "username": "helen_admin",
        "email": "helen@greenshift.io",
        "password": "AdminPassword123!",
        "role": "PLATFORM_ADMIN",
    })
    login_res = client.post("/auth/login", json={
        "username": "helen_admin",
        "password": "AdminPassword123!",
    })
    token = login_res.json()["access_token"]

    # Call /auth/me
    headers = {"Authorization": f"Bearer {token}"}
    me_res = client.get("/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "helen_admin"
    assert me_res.json()["role"] == "COMPANY_USER"

    # Call /api/v1/auth/me
    me_res_v1 = client.get("/api/v1/auth/me", headers=headers)
    assert me_res_v1.status_code == 200
    assert me_res_v1.json()["username"] == "helen_admin"


def test_protected_endpoint_without_token(client):
    me_res = client.get("/auth/me")
    assert me_res.status_code == 401
    assert "authentication token required" in me_res.json()["detail"].lower()


def test_protected_endpoint_with_invalid_token(client):
    headers = {"Authorization": "Bearer totally_bogus_token_12345"}
    me_res = client.get("/auth/me", headers=headers)
    assert me_res.status_code == 401
    assert "invalid" in me_res.json()["detail"].lower()


def test_protected_endpoint_with_expired_token(client):
    # Register user
    reg = client.post("/auth/register", json={
        "username": "ian_exp",
        "email": "ian@greenshift.io",
        "password": "Password123!",
        "role": "COMPANY_USER",
    })
    user_id = reg.json()["id"]

    # Create an intentionally expired token (-10 minutes)
    expired_token = create_access_token(
        user_id=user_id,
        username="ian_exp",
        role="COMPANY_USER",
        expires_delta=timedelta(minutes=-10),
    )

    headers = {"Authorization": f"Bearer {expired_token}"}
    me_res = client.get("/auth/me", headers=headers)
    assert me_res.status_code == 401
    assert "expired" in me_res.json()["detail"].lower()


# ====================================================================
# 5. Role-Based Access Control (RBAC) Dependency Tests
# ====================================================================

def test_role_based_access_control_dependency(client):
    # Seed a PLATFORM_ADMIN in database, and register a COMPANY_USER publicly
    with SessionLocal() as db:
        db.add(UserORM(
            username="admin_role_user",
            email="admin_role@greenshift.io",
            hashed_password=hash_password("Password123!"),
            role=UserRole.PLATFORM_ADMIN,
            is_active=True,
        ))
        db.commit()

    client.post("/auth/register", json={
        "username": "viewer_role_user",
        "email": "viewer_role@greenshift.io",
        "password": "Password123!",
        "role": "COMPANY_USER",
    })

    admin_token = client.post("/auth/login", json={
        "username": "admin_role_user",
        "password": "Password123!",
    }).json()["access_token"]

    viewer_token = client.post("/auth/login", json={
        "username": "viewer_role_user",
        "password": "Password123!",
    }).json()["access_token"]

    # Create a temporary test router with RBAC enforcement
    test_rbac_app = FastAPI()

    @test_rbac_app.get("/admin-only")
    def admin_endpoint(user: UserORM = Depends(require_roles(UserRole.PLATFORM_ADMIN))):
        return {"message": "hello admin", "user": user.username}

    rbac_client = TestClient(test_rbac_app)

    # Admin should succeed (200)
    admin_res = rbac_client.get("/admin-only", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_res.status_code == 200
    assert admin_res.json()["user"] == "admin_role_user"

    # Viewer should be forbidden (403)
    viewer_res = rbac_client.get("/admin-only", headers={"Authorization": f"Bearer {viewer_token}"})
    assert viewer_res.status_code == 403
    assert "operation not permitted" in viewer_res.json()["detail"].lower()
