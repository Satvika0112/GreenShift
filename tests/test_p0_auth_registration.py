"""
GreenShift — Tests for P0-BE-1 & P0-BE-4:
P0-BE-1: Remove Public Self-Registration as Immediate-Login Path
P0-BE-4: Consolidate User Creation into Authoritative POST /admin/users
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.main import app
from app.shared.config import settings
from app.shared.database import SessionLocal, engine
from app.shared.models import (
    AuditEventORM,
    EventType,
    TenantORM,
    UserORM,
    UserRole,
    UserApprovalStatus,
)
from app.shared.auth import hash_password, create_access_token


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(AuditEventORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()
        # Seed test tenants
        db.add(TenantORM(id="tenant-alpha", name="Alpha Corp", is_active=True))
        db.add(TenantORM(id="tenant-beta", name="Beta Corp", is_active=True))
        db.commit()
    yield
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(AuditEventORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()
        db.commit()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_admins():
    with SessionLocal() as db:
        # Platform Admin (no tenant)
        p_admin = UserORM(
            username="p_admin",
            email="padmin@greenshift.dev",
            hashed_password=hash_password("PlatformAdmin123!"),
            role=UserRole.PLATFORM_ADMIN,
            is_active=True,
            approval_status=UserApprovalStatus.APPROVED.value,
        )
        # Company Admin for tenant-alpha
        c_admin = UserORM(
            username="alpha_admin",
            email="admin@alpha.com",
            hashed_password=hash_password("CompanyAdmin123!"),
            role=UserRole.ADMIN,
            tenant_id="tenant-alpha",
            is_active=True,
            approval_status=UserApprovalStatus.APPROVED.value,
        )
        db.add_all([p_admin, c_admin])
        db.commit()
        db.refresh(p_admin)
        db.refresh(c_admin)

        return {
            "platform_admin_token": create_access_token(
                user_id=p_admin.id,
                username=p_admin.username,
                role=UserRole.PLATFORM_ADMIN.value,
            ),
            "company_admin_token": create_access_token(
                user_id=c_admin.id,
                username=c_admin.username,
                role=UserRole.ADMIN.value,
                tenant_id="tenant-alpha",
            ),
            "company_admin_id": c_admin.id,
        }


# ==============================================================================
# P0-BE-1: Public Registration Gating & Pending Approval Lifecycle
# ==============================================================================

def test_public_registration_creates_inactive_pending_user_when_auth_enabled(client, monkeypatch):
    """When AUTH_ENABLED=true, public registration MUST create inactive user with PENDING approval."""
    monkeypatch.setattr(settings, "auth_enabled", True)

    resp = client.post("/auth/register", json={
        "username": "candidate_alice",
        "email": "alice@external.com",
        "password": "Password123!",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "candidate_alice"
    assert data["role"] == "VIEWER"
    assert data["is_active"] is False
    assert data["approval_status"] == "PENDING"

    # Verify in DB
    with SessionLocal() as db:
        user = db.query(UserORM).filter(UserORM.username == "candidate_alice").first()
        assert user is not None
        assert user.is_active is False
        assert user.approval_status == "PENDING"

        # Verify audit event emitted
        events = db.query(AuditEventORM).filter(AuditEventORM.event_type == EventType.AUTH_USER_REGISTERED).all()
        assert len(events) >= 1
        assert any("candidate_alice" in (e.payload_json or "") for e in events)


def test_pending_user_cannot_login(client, monkeypatch):
    """Pending user attempting to log in must be rejected with 403 'Account pending approval'."""
    monkeypatch.setattr(settings, "auth_enabled", True)

    # 1. Register candidate
    client.post("/auth/register", json={
        "username": "candidate_bob",
        "email": "bob@external.com",
        "password": "Password123!",
    })

    # 2. Attempt login via /auth/login
    resp = client.post("/auth/login", json={
        "username": "candidate_bob",
        "password": "Password123!",
    })
    assert resp.status_code == 403
    assert "pending approval" in resp.json()["detail"].lower()

    # 3. Attempt login via /auth/login-email
    resp_email = client.post("/auth/login-email", json={
        "email": "bob@external.com",
        "password": "Password123!",
    })
    assert resp_email.status_code == 403
    assert "pending approval" in resp_email.json()["detail"].lower()


def test_admin_activates_user_and_user_can_then_login(client, seed_admins, monkeypatch):
    """Admin activates pending user via /admin/users/{id}/status; user can then log in successfully."""
    monkeypatch.setattr(settings, "auth_enabled", True)

    # 1. Register candidate user
    reg = client.post("/auth/register", json={
        "username": "candidate_charlie",
        "email": "charlie@alpha.com",
        "password": "SecurePassword123!",
    })
    user_id = reg.json()["id"]

    # Assign user to tenant-alpha in DB so company admin can manage
    with SessionLocal() as db:
        u = db.get(UserORM, user_id)
        u.tenant_id = "tenant-alpha"
        db.commit()

    # 2. Company Admin approves and activates user
    headers = {"Authorization": f"Bearer {seed_admins['company_admin_token']}"}
    patch_resp = client.patch(f"/api/v1/admin/users/{user_id}/status", headers=headers, json={
        "approval_status": "APPROVED",
        "is_active": True,
    })
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_active"] is True
    assert patch_resp.json()["approval_status"] == "APPROVED"

    # 3. User can now log in
    login_resp = client.post("/auth/login", json={
        "username": "candidate_charlie",
        "password": "SecurePassword123!",
    })
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()

    # 4. Verify AUTH_USER_ACTIVATED audit event
    with SessionLocal() as db:
        activated_events = db.query(AuditEventORM).filter(AuditEventORM.event_type == EventType.AUTH_USER_ACTIVATED).all()
        assert len(activated_events) >= 1
        assert any("candidate_charlie" in (e.payload_json or "") for e in activated_events)


def test_deactivated_user_login_rejected_with_clear_message(client, seed_admins, monkeypatch):
    """Deactivated user login rejected with 403 'User account is deactivated'."""
    monkeypatch.setattr(settings, "auth_enabled", True)

    with SessionLocal() as db:
        user = UserORM(
            username="deact_user",
            email="deact@alpha.com",
            hashed_password=hash_password("Password123!"),
            role=UserRole.VIEWER,
            tenant_id="tenant-alpha",
            is_active=False,
            approval_status=UserApprovalStatus.APPROVED.value,
        )
        db.add(user)
        db.commit()

    resp = client.post("/auth/login", json={
        "username": "deact_user",
        "password": "Password123!",
    })
    assert resp.status_code == 403
    assert "deactivated" in resp.json()["detail"].lower()


# ==============================================================================
# P0-BE-4: Authoritative User Creation Flow (POST /admin/users)
# ==============================================================================

def test_company_admin_creates_user_within_own_tenant(client, seed_admins):
    """Authoritative POST /admin/users creates active user within admin's tenant."""
    headers = {"Authorization": f"Bearer {seed_admins['company_admin_token']}"}

    resp = client.post("/api/v1/admin/users", headers=headers, json={
        "username": "alpha_operator",
        "email": "op@alpha.com",
        "password": "SecurePassword123!",
        "role": "OPERATOR",
        "team_id": "core-team",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "alpha_operator"
    assert data["email"] == "op@alpha.com"
    assert data["role"] == "OPERATOR"
    assert data["tenant_id"] == "tenant-alpha"
    assert data["is_active"] is True
    assert data["approval_status"] == "APPROVED"

    # User can immediately log in
    login_resp = client.post("/auth/login", json={
        "username": "alpha_operator",
        "password": "SecurePassword123!",
    })
    assert login_resp.status_code == 200


def test_company_admin_cannot_create_platform_admin_or_admin(client, seed_admins):
    """Company Admin cannot escalate privileges by creating PLATFORM_ADMIN or ADMIN."""
    headers = {"Authorization": f"Bearer {seed_admins['company_admin_token']}"}

    # Attempt to create PLATFORM_ADMIN
    r1 = client.post("/api/v1/admin/users", headers=headers, json={
        "username": "escalated_padmin",
        "email": "esc_p@alpha.com",
        "password": "SecurePassword123!",
        "role": "PLATFORM_ADMIN",
    })
    assert r1.status_code == 403
    assert "platform admin" in r1.json()["detail"].lower()

    # Attempt to create ADMIN
    r2 = client.post("/api/v1/admin/users", headers=headers, json={
        "username": "escalated_admin",
        "email": "esc_a@alpha.com",
        "password": "SecurePassword123!",
        "role": "ADMIN",
    })
    assert r2.status_code == 403
    assert "platform admin" in r2.json()["detail"].lower()


def test_company_admin_cannot_create_user_in_other_tenant(client, seed_admins):
    """Company Admin cannot specify a different tenant_id to create users in other tenants."""
    headers = {"Authorization": f"Bearer {seed_admins['company_admin_token']}"}

    resp = client.post("/api/v1/admin/users", headers=headers, json={
        "username": "infiltrator",
        "email": "infiltrator@beta.com",
        "password": "SecurePassword123!",
        "role": "OPERATOR",
        "tenant_id": "tenant-beta",  # Other tenant!
    })
    assert resp.status_code == 403
    assert "other tenant" in resp.json()["detail"].lower()


def test_platform_admin_can_create_user_in_any_tenant(client, seed_admins):
    """Platform Admin can specify any tenant_id when creating a user."""
    headers = {"Authorization": f"Bearer {seed_admins['platform_admin_token']}"}

    resp = client.post("/api/v1/admin/users", headers=headers, json={
        "username": "beta_admin",
        "email": "admin@beta.com",
        "password": "SecurePassword123!",
        "role": "ADMIN",
        "tenant_id": "tenant-beta",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "beta_admin"
    assert data["tenant_id"] == "tenant-beta"
    assert data["role"] == "ADMIN"
