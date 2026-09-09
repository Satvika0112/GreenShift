"""
Tests for P0-BE-2: Platform Admin vs Company Admin vs Company User Authorization.

Verifies:
1. Platform Admin has global access across all tenants and full company/user/key management.
2. Company Admin is strictly locked to identity.tenant_id:
   - Can only view/manage users, API keys, and company details within own tenant.
   - Cross-tenant access returns 404 (or 403 where appropriate).
   - Cannot create/assign PLATFORM_ADMIN or ADMIN roles (403).
   - Cannot deactivate company (403).
   - Cannot create companies (403).
   - Rule 3: API keys cannot be granted ADMIN, PLATFORM_ADMIN, or COMPANY_ADMIN (400).
3. Non-admins (COMPANY_USER, OPERATOR, VIEWER, TEAM_LEAD) are forbidden from all /admin/* endpoints (403).
"""

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import (
    APIKeyORM,
    AuditEventORM,
    JobORM,
    TenantORM,
    UserApprovalStatus,
    UserORM,
    UserRole,
)
from app.shared.auth import create_access_token, hash_password


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    """Ensure clean database and auth enabled for testing."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(APIKeyORM).delete()
        db.query(AuditEventORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()
        db.add(TenantORM(id="tenant-acme", name="Acme Corp", is_active=True))
        db.add(TenantORM(id="tenant-globex", name="Globex Corp", is_active=True))
        db.commit()
    yield
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(APIKeyORM).delete()
        db.query(AuditEventORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()
        db.commit()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_setup():
    """Seed test users for Platform Admin, Company Admin, and Company User."""
    with SessionLocal() as db:
        def make_user(username, email, role, tenant_id=None):
            u = UserORM(
                username=username,
                email=email,
                hashed_password=hash_password("Pass123!"),
                role=role,
                tenant_id=tenant_id,
                approval_status=UserApprovalStatus.APPROVED.value,
                is_active=True,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
            token = create_access_token(
                user_id=u.id,
                username=u.username,
                role=u.role.value if hasattr(u.role, "value") else str(u.role),
                tenant_id=u.tenant_id,
            )
            return u.id, {"Authorization": f"Bearer {token}"}

        p_id, plat_headers = make_user("plat_adm", "plat_adm@test.io", UserRole.PLATFORM_ADMIN, None)
        a_id, acme_admin_headers = make_user("acme_adm", "acme_adm@acme.com", UserRole.COMPANY_ADMIN, "tenant-acme")
        g_id, globex_admin_headers = make_user("globex_adm", "globex_adm@globex.com", UserRole.COMPANY_ADMIN, "tenant-globex")
        u_id, acme_user_headers = make_user("acme_usr", "acme_usr@acme.com", UserRole.COMPANY_USER, "tenant-acme")
        o_id, operator_headers = make_user("oper_usr", "oper_usr@acme.com", UserRole.OPERATOR, "tenant-acme")
        l_id, team_lead_headers = make_user("lead_usr", "lead_usr@acme.com", UserRole.TEAM_LEAD, "tenant-acme")

    return {
        "plat_id": p_id,
        "plat_headers": plat_headers,
        "acme_admin_id": a_id,
        "acme_admin_headers": acme_admin_headers,
        "globex_admin_id": g_id,
        "globex_admin_headers": globex_admin_headers,
        "acme_user_id": u_id,
        "acme_user_headers": acme_user_headers,
        "operator_headers": operator_headers,
        "team_lead_headers": team_lead_headers,
    }


# ─── 1. Company Management Tests ──────────────────────────────────────────────

def test_platform_admin_can_list_all_companies(client, test_setup):
    resp = client.get("/api/v1/admin/companies", headers=test_setup["plat_headers"])
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert "tenant-acme" in ids
    assert "tenant-globex" in ids


def test_company_admin_sees_only_own_company_in_companies_list(client, test_setup):
    resp = client.get("/api/v1/admin/companies", headers=test_setup["acme_admin_headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "tenant-acme"


def test_company_admin_cross_tenant_company_get_returns_404(client, test_setup):
    # Rule 5: Access to other tenant resource returns 404
    resp = client.get("/api/v1/admin/companies/tenant-globex", headers=test_setup["acme_admin_headers"])
    assert resp.status_code == 404


def test_company_admin_cannot_create_company(client, test_setup):
    resp = client.post(
        "/api/v1/admin/companies",
        json={"name": "Initech Corp"},
        headers=test_setup["acme_admin_headers"],
    )
    assert resp.status_code == 403


def test_platform_admin_can_create_company(client, test_setup):
    resp = client.post(
        "/api/v1/admin/companies",
        json={"id": "tenant-initech", "name": "Initech Corp", "is_active": True},
        headers=test_setup["plat_headers"],
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == "tenant-initech"


def test_company_admin_cannot_deactivate_own_company(client, test_setup):
    resp = client.put(
        "/api/v1/admin/companies/tenant-acme",
        json={"is_active": False},
        headers=test_setup["acme_admin_headers"],
    )
    assert resp.status_code == 403


def test_platform_admin_can_deactivate_company(client, test_setup):
    resp = client.put(
        "/api/v1/admin/companies/tenant-acme",
        json={"is_active": False},
        headers=test_setup["plat_headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# ─── 2. User Management Tests ──────────────────────────────────────────────────

def test_company_admin_cannot_view_users_of_other_tenant(client, test_setup):
    resp = client.get(
        "/api/v1/admin/users?tenant_id=tenant-globex",
        headers=test_setup["acme_admin_headers"],
    )
    assert resp.status_code == 403


def test_company_admin_cross_tenant_user_status_update_returns_404(client, test_setup):
    globex_id = test_setup["globex_admin_id"]
    resp = client.patch(
        f"/api/v1/admin/users/{globex_id}/status",
        json={"is_active": False},
        headers=test_setup["acme_admin_headers"],
    )
    assert resp.status_code == 404


def test_company_admin_cross_tenant_user_deactivate_returns_404(client, test_setup):
    globex_id = test_setup["globex_admin_id"]
    resp = client.delete(
        f"/api/v1/admin/users/{globex_id}",
        headers=test_setup["acme_admin_headers"],
    )
    assert resp.status_code == 404


# ─── 3. API Key Management Tests ───────────────────────────────────────────────

def test_company_admin_can_create_api_key_for_own_tenant(client, test_setup):
    resp = client.post(
        "/api/v1/admin/api-keys",
        json={"role": "OPERATOR", "label": "Acme CI"},
        headers=test_setup["acme_admin_headers"],
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["tenant_id"] == "tenant-acme"
    assert data["role"] == "OPERATOR"
    assert "api_key" in data


def test_company_admin_cannot_create_api_key_for_other_tenant(client, test_setup):
    resp = client.post(
        "/api/v1/admin/api-keys",
        json={"role": "OPERATOR", "label": "Injected Key", "tenant_id": "tenant-globex"},
        headers=test_setup["acme_admin_headers"],
    )
    assert resp.status_code == 403


def test_api_key_cannot_be_granted_admin_or_platform_admin_or_company_admin(client, test_setup):
    # Rule 3
    for bad_role in ["ADMIN", "PLATFORM_ADMIN", "COMPANY_ADMIN"]:
        resp = client.post(
            "/api/v1/admin/api-keys",
            json={"role": bad_role, "label": f"Bad {bad_role}"},
            headers=test_setup["plat_headers"],
        )
        assert resp.status_code == 400


def test_company_admin_list_api_keys_scoped_to_tenant(client, test_setup):
    with SessionLocal() as db:
        k_globex = APIKeyORM(
            id="globex-key-1",
            key_hash="dummy_hash_1",
            tenant_id="tenant-globex",
            role=UserRole.OPERATOR,
            label="Globex Key",
            is_active=True,
        )
        db.add(k_globex)
        db.commit()

    resp = client.get("/api/v1/admin/api-keys", headers=test_setup["acme_admin_headers"])
    assert resp.status_code == 200
    ids = [k["id"] for k in resp.json()]
    assert "globex-key-1" not in ids


def test_company_admin_cannot_query_other_tenant_api_keys(client, test_setup):
    resp = client.get(
        "/api/v1/admin/api-keys?tenant_id=tenant-globex",
        headers=test_setup["acme_admin_headers"],
    )
    assert resp.status_code == 403


def test_company_admin_cross_tenant_revoke_api_key_returns_404(client, test_setup):
    with SessionLocal() as db:
        k_globex = APIKeyORM(
            id="globex-key-revoke-test",
            key_hash="dummy_hash_revoke",
            tenant_id="tenant-globex",
            role=UserRole.OPERATOR,
            label="Globex Key",
            is_active=True,
        )
        db.add(k_globex)
        db.commit()

    resp = client.delete(
        "/api/v1/admin/api-keys/globex-key-revoke-test",
        headers=test_setup["acme_admin_headers"],
    )
    assert resp.status_code == 404


def test_platform_admin_can_revoke_any_api_key(client, test_setup):
    with SessionLocal() as db:
        k_globex = APIKeyORM(
            id="globex-key-plat-revoke",
            key_hash="dummy_hash_plat_revoke",
            tenant_id="tenant-globex",
            role=UserRole.OPERATOR,
            label="Globex Key",
            is_active=True,
        )
        db.add(k_globex)
        db.commit()

    resp = client.delete(
        "/api/v1/admin/api-keys/globex-key-plat-revoke",
        headers=test_setup["plat_headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


# ─── 4. Non-Admin / Company User Forbidden Tests ───────────────────────────────

def test_company_user_forbidden_from_admin_endpoints(client, test_setup):
    headers = test_setup["acme_user_headers"]
    assert client.get("/api/v1/admin/companies", headers=headers).status_code == 403
    assert client.post("/api/v1/admin/companies", json={"name": "X"}, headers=headers).status_code == 403
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403
    assert client.post("/api/v1/admin/users", json={"email": "x@x.com", "password": "p", "role": "USER"}, headers=headers).status_code == 403
    assert client.get("/api/v1/admin/api-keys", headers=headers).status_code == 403
    assert client.post("/api/v1/admin/api-keys", json={"role": "OPERATOR"}, headers=headers).status_code == 403


def test_team_lead_and_operator_forbidden_from_admin_endpoints(client, test_setup):
    for h in [test_setup["team_lead_headers"], test_setup["operator_headers"]]:
        assert client.get("/api/v1/admin/companies", headers=h).status_code == 403
        assert client.get("/api/v1/admin/users", headers=h).status_code == 403
        assert client.get("/api/v1/admin/api-keys", headers=h).status_code == 403
