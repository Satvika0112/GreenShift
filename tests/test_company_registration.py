"""
GreenShift — Company / Organization Onboarding tests.

Covers the mandatory registration/security/isolation/audit test matrix:
valid registration, security (role/tenant/team/company spoofing, duplicates,
weak passwords, invalid email), tenant isolation across two real companies,
and audit integration (COMPANY_CREATED/COMPANY_ADMIN_CREATED with correct
server-derived context).

Uses the same real file-backed test DB + TestClient pattern already
established by tests/test_p0_tenant_isolation.py and
tests/test_trust_audit_security.py — audit_events is append-only and is
never deleted in cleanup; assertions filter by this file's own unique
company names/tenant ids, so accumulation across test runs is safe.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.auth import create_access_token, hash_password
from app.shared.models import (
    AuditEventORM,
    EventType,
    JobORM,
    TeamORM,
    TenantORM,
    UserApprovalStatus,
    UserORM,
    UserRole,
)

COMPANY_A_NAME = "Onboard Test Alpha Inc"
COMPANY_B_NAME = "Onboard Test Beta Inc"
TENANT_A = "tenant-onboard-test-alpha-inc"
TENANT_B = "tenant-onboard-test-beta-inc"


def _base_registration_body(company_name: str, company_email: str, admin_email: str) -> dict:
    return {
        "company_name": company_name,
        "legal_name": f"{company_name} Pvt Ltd",
        "company_email": company_email,
        "website": "https://example.com",
        "industry": "Technology",
        "sector": "B2B SaaS",
        "country": "India",
        "address": "1 Example Street",
        "admin_name": "Test Admin",
        "admin_email": admin_email,
        "password": "StrongPass1",
        "confirm_password": "StrongPass1",
    }


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(JobORM).filter(JobORM.tenant_id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(TeamORM).filter(TeamORM.tenant_id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(UserORM).filter(UserORM.tenant_id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(TenantORM).filter(TenantORM.id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(TenantORM).filter(TenantORM.name.in_([COMPANY_A_NAME, COMPANY_B_NAME])).delete(synchronize_session=False)
        db.query(UserORM).filter(UserORM.username == "onboard_test_platadm").delete(synchronize_session=False)
        db.commit()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, username, password):
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _make_platform_admin(db) -> tuple:
    u = UserORM(
        username="onboard_test_platadm", email="platadm@onboardtest.io",
        hashed_password=hash_password("PlatPass1!"), role=UserRole.PLATFORM_ADMIN,
        approval_status=UserApprovalStatus.APPROVED.value, is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ─────────────────────────────────────────────────────────────────────────────
# Valid registration
# ─────────────────────────────────────────────────────────────────────────────

class TestValidRegistration:
    def test_registration_succeeds_and_creates_company_team_admin(self, client):
        body = _base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com")
        resp = client.post("/api/v1/companies/register", json=body)
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["company_id"] == TENANT_A
        assert data["company_name"] == COMPANY_A_NAME
        assert data["admin"]["role"] == "COMPANY_ADMIN"
        assert data["team_name"] == "General / Administration"
        assert data["message"] == "Company registered successfully"

        with SessionLocal() as db:
            tenant = db.get(TenantORM, TENANT_A)
            assert tenant is not None
            assert tenant.status == "ACTIVE"
            assert tenant.is_active is True
            assert tenant.industry == "Technology"

            team = db.get(TeamORM, data["team_id"])
            assert team is not None
            assert team.tenant_id == TENANT_A

            admin = db.query(UserORM).filter(UserORM.email == "admin@alpha-onboard.example.com").first()
            assert admin is not None
            assert admin.role == UserRole.COMPANY_ADMIN
            assert admin.tenant_id == TENANT_A
            assert admin.team_id == team.id
            assert admin.is_active is True
            assert admin.approval_status == "APPROVED"

    def test_registered_admin_can_login_and_gets_correct_jwt_claims(self, client):
        body = _base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com")
        reg = client.post("/api/v1/companies/register", json=body).json()

        token = _login(client, reg["admin"]["username"], "StrongPass1")
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["role"] == "COMPANY_ADMIN"
        assert me["tenant_id"] == TENANT_A
        assert me["team_id"] == reg["team_id"]
        assert me["company"]["id"] == TENANT_A
        assert me["company"]["name"] == COMPANY_A_NAME


# ─────────────────────────────────────────────────────────────────────────────
# Security — spoofing / privilege escalation
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistrationSecurity:
    def test_forged_role_is_ignored_admin_is_always_company_admin(self, client):
        body = {**_base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com"), "role": "PLATFORM_ADMIN"}
        resp = client.post("/api/v1/companies/register", json=body)
        assert resp.status_code == 201
        assert resp.json()["admin"]["role"] == "COMPANY_ADMIN"

    def test_forged_tenant_id_is_ignored(self, client):
        body = {**_base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com"), "tenant_id": "tenant-acme"}
        resp = client.post("/api/v1/companies/register", json=body)
        assert resp.status_code == 201
        assert resp.json()["company_id"] != "tenant-acme"
        assert resp.json()["company_id"] == TENANT_A

    def test_forged_team_id_is_ignored(self, client):
        body = {**_base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com"), "team_id": "team-acme"}
        resp = client.post("/api/v1/companies/register", json=body)
        assert resp.status_code == 201
        assert resp.json()["team_id"] != "team-acme"

    def test_forged_company_id_is_ignored(self, client):
        body = {**_base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com"), "company_id": "tenant-acme"}
        resp = client.post("/api/v1/companies/register", json=body)
        assert resp.status_code == 201
        assert resp.json()["company_id"] != "tenant-acme"

    def test_duplicate_company_name_rejected(self, client):
        body = _base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com")
        assert client.post("/api/v1/companies/register", json=body).status_code == 201
        dup = {**body, "company_email": "different@alpha-onboard.example.com", "admin_email": "different-admin@alpha-onboard.example.com"}
        resp = client.post("/api/v1/companies/register", json=dup)
        assert resp.status_code == 409

    def test_duplicate_admin_email_rejected(self, client):
        body = _base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com")
        assert client.post("/api/v1/companies/register", json=body).status_code == 201
        dup = {**_base_registration_body(COMPANY_B_NAME, "hq@beta-onboard.example.com", "admin@alpha-onboard.example.com")}
        resp = client.post("/api/v1/companies/register", json=dup)
        assert resp.status_code == 409

    def test_duplicate_company_email_rejected(self, client):
        body = _base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com")
        assert client.post("/api/v1/companies/register", json=body).status_code == 201
        dup = {**_base_registration_body(COMPANY_B_NAME, "hq@alpha-onboard.example.com", "admin@beta-onboard.example.com")}
        resp = client.post("/api/v1/companies/register", json=dup)
        assert resp.status_code == 409

    def test_invalid_admin_email_rejected(self, client):
        body = {**_base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "not-an-email"), }
        resp = client.post("/api/v1/companies/register", json=body)
        assert resp.status_code == 422

    def test_invalid_company_email_rejected(self, client):
        body = {**_base_registration_body(COMPANY_A_NAME, "not-an-email", "admin@alpha-onboard.example.com")}
        resp = client.post("/api/v1/companies/register", json=body)
        assert resp.status_code == 422

    def test_weak_password_rejected(self, client):
        body = {**_base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com"), "password": "weak", "confirm_password": "weak"}
        resp = client.post("/api/v1/companies/register", json=body)
        assert resp.status_code == 422

    def test_password_confirmation_mismatch_rejected(self, client):
        body = {**_base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com"), "confirm_password": "Different1"}
        resp = client.post("/api/v1/companies/register", json=body)
        assert resp.status_code == 422

    def test_missing_required_fields_rejected(self, client):
        resp = client.post("/api/v1/companies/register", json={"company_name": "Incomplete Co"})
        assert resp.status_code == 422

    def test_registration_never_creates_platform_admin_regardless_of_payload(self, client):
        """Even a maximally hostile payload can never produce a PLATFORM_ADMIN."""
        body = {
            **_base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com"),
            "role": "PLATFORM_ADMIN", "tenant_id": "tenant-acme", "team_id": "team-acme",
            "company_id": "tenant-acme", "is_platform_admin": True, "permission_level": "SUPERUSER",
        }
        resp = client.post("/api/v1/companies/register", json=body)
        assert resp.status_code == 201
        with SessionLocal() as db:
            admin = db.query(UserORM).filter(UserORM.email == "admin@alpha-onboard.example.com").first()
            assert admin.role == UserRole.COMPANY_ADMIN
            assert admin.role != UserRole.PLATFORM_ADMIN


# ─────────────────────────────────────────────────────────────────────────────
# Isolation between two real companies
# ─────────────────────────────────────────────────────────────────────────────

class TestCompanyIsolation:
    @pytest.fixture
    def two_companies(self, client):
        reg_a = client.post("/api/v1/companies/register", json=_base_registration_body(
            COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com",
        )).json()
        reg_b = client.post("/api/v1/companies/register", json=_base_registration_body(
            COMPANY_B_NAME, "hq@beta-onboard.example.com", "admin@beta-onboard.example.com",
        )).json()
        token_a = _login(client, reg_a["admin"]["username"], "StrongPass1")
        token_b = _login(client, reg_b["admin"]["username"], "StrongPass1")
        with SessionLocal() as db:
            plat = _make_platform_admin(db)
            plat_token = create_access_token(user_id=plat.id, username=plat.username, role="PLATFORM_ADMIN", tenant_id=None, team_id=None)
        return {
            "reg_a": reg_a, "reg_b": reg_b,
            "headers_a": {"Authorization": f"Bearer {token_a}"},
            "headers_b": {"Authorization": f"Bearer {token_b}"},
            "headers_plat": {"Authorization": f"Bearer {plat_token}"},
        }

    def test_company_a_admin_cannot_access_company_b_profile(self, client, two_companies):
        resp = client.get("/api/v1/companies/me", headers=two_companies["headers_a"])
        assert resp.json()["id"] == TENANT_A
        assert resp.json()["id"] != TENANT_B

    def test_company_a_admin_cannot_see_company_b_users(self, client, two_companies):
        resp = client.get("/api/v1/companies/me/users", headers=two_companies["headers_a"])
        usernames = [u["username"] for u in resp.json()]
        assert two_companies["reg_b"]["admin"]["username"] not in usernames
        assert two_companies["reg_a"]["admin"]["username"] in usernames

    def test_company_a_admin_cannot_see_company_b_teams(self, client, two_companies):
        resp = client.get("/api/v1/companies/me/teams", headers=two_companies["headers_a"])
        team_ids = [t["id"] for t in resp.json()]
        assert two_companies["reg_b"]["team_id"] not in team_ids
        assert two_companies["reg_a"]["team_id"] in team_ids

    def test_company_a_admin_cannot_see_company_b_jobs(self, client, two_companies):
        job_b = "JOB-ISOLATION-B-001"
        client.post("/api/v1/jobs", headers=two_companies["headers_b"], json={
            "job_id": job_b, "team_id": two_companies["reg_b"]["team_id"],
            "deadline": "2027-01-01T00:00:00Z", "runtime_minutes": 30, "power_kw": 1.0,
            "region": "IN-TG", "container_image": "python:3.10-slim",
        })
        resp = client.get(f"/api/v1/jobs/{job_b}", headers=two_companies["headers_a"])
        assert resp.status_code == 404

    def test_company_b_cannot_access_company_a(self, client, two_companies):
        resp = client.get("/api/v1/companies/me", headers=two_companies["headers_b"])
        assert resp.json()["id"] == TENANT_B
        resp2 = client.get("/api/v1/companies/me/users", headers=two_companies["headers_b"])
        usernames = [u["username"] for u in resp2.json()]
        assert two_companies["reg_a"]["admin"]["username"] not in usernames

    def test_company_a_admin_cannot_patch_company_b_by_guessing_tenant_id(self, client, two_companies):
        """PATCH /companies/me has no id in the URL/body at all — there is no
        way to even attempt to target another company's tenant_id."""
        resp = client.patch("/api/v1/companies/me", headers=two_companies["headers_a"], json={"tenant_id": TENANT_B, "id": TENANT_B, "website": "https://hacked.example.com"})
        assert resp.status_code == 200
        with SessionLocal() as db:
            tenant_b = db.get(TenantORM, TENANT_B)
            assert tenant_b.website != "https://hacked.example.com"

    def test_platform_admin_can_access_both_companies(self, client, two_companies):
        headers = two_companies["headers_plat"]
        resp_a = client.get("/api/v1/admin/companies/" + TENANT_A, headers=headers)
        resp_b = client.get("/api/v1/admin/companies/" + TENANT_B, headers=headers)
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_a.json()["id"] == TENANT_A
        assert resp_b.json()["id"] == TENANT_B


# ─────────────────────────────────────────────────────────────────────────────
# Audit integration
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistrationAudit:
    def test_company_created_and_admin_created_events_recorded_with_correct_context(self, client):
        body = _base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com")
        reg = client.post("/api/v1/companies/register", json=body, headers={"X-Request-ID": "11111111-1111-4111-8111-111111111111"}).json()

        with SessionLocal() as db:
            created = (
                db.query(AuditEventORM)
                .filter(AuditEventORM.event_type == EventType.COMPANY_CREATED, AuditEventORM.tenant_id == TENANT_A)
                .order_by(AuditEventORM.sequence.desc())
                .first()
            )
            assert created is not None
            assert created.team_id == reg["team_id"]
            assert created.source_service == "company_registration"
            # No authenticated actor exists yet at company-creation time —
            # server-derived SYSTEM, never a client-supplied identity.
            assert created.actor_type == "SYSTEM"
            assert created.actor_user_id is None
            assert created.request_id == "11111111-1111-4111-8111-111111111111"

            admin_created = (
                db.query(AuditEventORM)
                .filter(AuditEventORM.event_type == EventType.COMPANY_ADMIN_CREATED, AuditEventORM.tenant_id == TENANT_A)
                .order_by(AuditEventORM.sequence.desc())
                .first()
            )
            assert admin_created is not None
            assert admin_created.team_id == reg["team_id"]
            assert admin_created.actor_type == "SYSTEM"

    def test_no_client_supplied_actor_identity_is_trusted_in_audit_event(self, client):
        """A hostile payload trying to inject actor fields has no effect —
        CompanyRegisterRequest has no such fields, so they're silently
        dropped, and the resulting audit event's actor_* columns are exactly
        as they would be for a clean registration (SYSTEM, no user)."""
        body = {
            **_base_registration_body(COMPANY_A_NAME, "hq@alpha-onboard.example.com", "admin@alpha-onboard.example.com"),
            "actor_user_id": "999", "actor_username": "root", "actor_role": "PLATFORM_ADMIN", "actor_type": "USER",
        }
        client.post("/api/v1/companies/register", json=body)
        with SessionLocal() as db:
            created = (
                db.query(AuditEventORM)
                .filter(AuditEventORM.event_type == EventType.COMPANY_CREATED, AuditEventORM.tenant_id == TENANT_A)
                .order_by(AuditEventORM.sequence.desc())
                .first()
            )
            assert created.actor_username is None
            assert created.actor_role is None
            assert created.actor_type == "SYSTEM"


class TestPlatformAdminCannotInheritCompanyAdminMutationRights:
    """Consistency audit fix: app.companies.service.require_company_admin_of_own_company
    used to check `is_company_admin(user)`, which returns True for
    PLATFORM_ADMIN too. In the normal case a Platform Admin has no
    tenant_id and is already rejected by require_own_company(), but a
    Platform Admin account that happens to have a tenant_id set (not
    structurally prevented anywhere) would otherwise have been able to
    mutate that company's profile/users/teams through the "own company"
    surface. Fixed to explicitly, unconditionally exclude Platform Admin,
    matching the identical, already-correct guard in
    app.brsr.service.require_edit_access."""

    def test_platform_admin_with_a_tenant_id_still_cannot_edit_company_profile(self, client):
        with SessionLocal() as db:
            db.query(TenantORM).filter(TenantORM.id == "tenant-edge-case-platadm").delete(synchronize_session=False)
            db.query(UserORM).filter(UserORM.username == "edge_case_platadm").delete(synchronize_session=False)
            db.add(TenantORM(id="tenant-edge-case-platadm", name="Edge Case PlatAdm Co", is_active=True))
            db.commit()
            # An unusual but not structurally prevented state: PLATFORM_ADMIN with a tenant_id.
            u = UserORM(
                username="edge_case_platadm", email="edge@platadm.example.com",
                hashed_password=hash_password("PlatPass1!"), role=UserRole.PLATFORM_ADMIN,
                tenant_id="tenant-edge-case-platadm", approval_status="APPROVED", is_active=True,
            )
            db.add(u)
            db.commit()

        token = _login(client, "edge_case_platadm", "PlatPass1!")
        headers = {"Authorization": f"Bearer {token}"}

        r = client.patch("/api/v1/companies/me", headers=headers, json={"website": "https://hacked.example.com"})
        assert r.status_code == 403

        r2 = client.post("/api/v1/companies/me/teams", headers=headers, json={"name": "Rogue Team"})
        assert r2.status_code == 403

        r3 = client.post("/api/v1/companies/me/users", headers=headers, json={"email": "rogue@platadm.example.com", "password": "StrongPass1"})
        assert r3.status_code == 403

        with SessionLocal() as db:
            tenant = db.get(TenantORM, "tenant-edge-case-platadm")
            assert tenant.website != "https://hacked.example.com"
