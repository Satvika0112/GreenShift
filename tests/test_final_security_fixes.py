"""
GreenShift — End-to-End Tests for Final Security Fixes:
1. Fix 1: Public Registration Privilege Escalation Prevention & Admin User Creation
2. Fix 2: Remove Client-Controlled approved_by Identity Spoofing
3. Fix 3: Strict Multi-Tenant Team Isolation on Read Endpoints
"""

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.main import app
from app.shared.database import SessionLocal, engine
from app.shared.models import (
    ApprovalORM,
    ApprovalRequest,
    AuditEventORM,
    JobORM,
    JobStatus,
    KubernetesExecutionORM,
    ScheduleDecisionORM,
    UserORM,
    UserRole,
)
from app.shared.auth import hash_password, create_access_token
from app.shared.utils import utcnow


@pytest.fixture(autouse=True)
def clean_security_db():
    """Ensure a pristine database before and after each security test."""
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(KubernetesExecutionORM).delete()
        db.query(ApprovalORM).delete()
        # audit_events is append-only at the DB level (Trust/Audit P0) — never
        # deleted, including in test cleanup. Tests below filter by unique
        # job_id/username/event_type, so accumulated rows across the shared
        # file-backed test DB do not affect their assertions.
        db.query(ScheduleDecisionORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.commit()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))
    yield
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(KubernetesExecutionORM).delete()
        db.query(ApprovalORM).delete()
        # audit_events is append-only at the DB level (Trust/Audit P0) — never
        # deleted, including in test cleanup. Tests below filter by unique
        # job_id/username/event_type, so accumulated rows across the shared
        # file-backed test DB do not affect their assertions.
        db.query(ScheduleDecisionORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.commit()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_users(client):
    """Seed base users in database and return access tokens."""
    with SessionLocal() as db:
        admin_u = UserORM(
            username="sec_admin",
            email="admin@test.com",
            hashed_password=hash_password("AdminPass123!"),
            role=UserRole.PLATFORM_ADMIN,
            is_active=True,
        )
        lead_a_u = UserORM(
            username="sec_lead_a",
            email="lead_a@test.com",
            hashed_password=hash_password("LeadPass123!"),
            role=UserRole.COMPANY_ADMIN,
            team_id="team-a",
            is_active=True,
        )
        lead_b_u = UserORM(
            username="sec_lead_b",
            email="lead_b@test.com",
            hashed_password=hash_password("LeadPass123!"),
            role=UserRole.COMPANY_ADMIN,
            team_id="team-b",
            is_active=True,
        )
        operator_a_u = UserORM(
            username="sec_op_a",
            email="op_a@test.com",
            hashed_password=hash_password("OpPass123!"),
            role=UserRole.COMPANY_USER,
            team_id="team-a",
            is_active=True,
        )
        viewer_a_u = UserORM(
            username="sec_view_a",
            email="view_a@test.com",
            hashed_password=hash_password("ViewPass123!"),
            role=UserRole.COMPANY_USER,
            team_id="team-a",
            is_active=True,
        )
        db.add_all([admin_u, lead_a_u, lead_b_u, operator_a_u, viewer_a_u])
        db.commit()
        db.refresh(admin_u)
        db.refresh(lead_a_u)
        db.refresh(lead_b_u)
        db.refresh(operator_a_u)
        db.refresh(viewer_a_u)

        tokens = {
            "admin": create_access_token(user_id=admin_u.id, username=admin_u.username, role="PLATFORM_ADMIN"),
            "lead_a": create_access_token(user_id=lead_a_u.id, username=lead_a_u.username, role="COMPANY_ADMIN", team_id="team-a"),
            "lead_b": create_access_token(user_id=lead_b_u.id, username=lead_b_u.username, role="COMPANY_ADMIN", team_id="team-b"),
            "operator_a": create_access_token(user_id=operator_a_u.id, username=operator_a_u.username, role="COMPANY_USER", team_id="team-a"),
            "viewer_a": create_access_token(user_id=viewer_a_u.id, username=viewer_a_u.username, role="COMPANY_USER", team_id="team-a"),
        }
    return tokens


# ====================================================================
# FIX 1: REGISTRATION PRIVILEGE ESCALATION TESTS
# ====================================================================

def test_public_registration_with_platform_admin_role_assigned_company_user(client):
    """A. Public registration with role=PLATFORM_ADMIN must assign COMPANY_USER, not PLATFORM_ADMIN."""
    resp = client.post("/auth/register", json={
        "username": "attacker_admin",
        "email": "attacker@darkweb.org",
        "password": "Password123!",
        "role": "PLATFORM_ADMIN",
        "team_id": "core",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "attacker_admin"
    assert data["role"] == "COMPANY_USER"  # Forced to COMPANY_USER


def test_public_registration_with_company_admin_role_assigned_company_user(client):
    """B. Public registration with role=COMPANY_ADMIN must assign COMPANY_USER."""
    resp = client.post("/auth/register", json={
        "username": "self_promoter",
        "email": "promoter@company.com",
        "password": "Password123!",
        "role": "COMPANY_ADMIN",
    })
    assert resp.status_code == 201
    assert resp.json()["role"] == "COMPANY_USER"


def test_public_registration_with_legacy_role_string_rejected(client):
    """Legacy role values (removed from UserRole) must be rejected outright (422),
    not silently coerced — they are no longer valid input at all."""
    for legacy_role in ("ADMIN", "TEAM_LEAD", "OPERATOR", "VIEWER"):
        resp = client.post("/auth/register", json={
            "username": f"legacy_{legacy_role.lower()}",
            "email": f"{legacy_role.lower()}@company.com",
            "password": "Password123!",
            "role": legacy_role,
        })
        assert resp.status_code == 422, f"role={legacy_role} should be rejected by schema validation"


def test_unauthenticated_admin_create_user_returns_401(client):
    """C. Unauthenticated request to /auth/admin/create-user returns 401."""
    resp = client.post("/auth/admin/create-user", json={
        "username": "new_admin",
        "email": "new_admin@company.com",
        "password": "Password123!",
        "role": "PLATFORM_ADMIN",
    })
    assert resp.status_code == 401


def test_non_admin_calling_admin_create_user_returns_403(client, seed_users):
    """D. Non-Platform-Admin authenticated user calling /auth/admin/create-user returns 403.
    This deprecated endpoint is Platform-Admin-only — a Company Admin (lead_a) must
    use POST /admin/users instead."""
    headers_lead = {"Authorization": f"Bearer {seed_users['lead_a']}"}
    resp_lead = client.post("/auth/admin/create-user", headers=headers_lead, json={
        "username": "subordinate",
        "email": "sub@company.com",
        "password": "Password123!",
        "role": "COMPANY_USER",
    })
    assert resp_lead.status_code == 403

    headers_viewer = {"Authorization": f"Bearer {seed_users['viewer_a']}"}
    resp_viewer = client.post("/auth/admin/create-user", headers=headers_viewer, json={
        "username": "subordinate2",
        "email": "sub2@company.com",
        "password": "Password123!",
        "role": "COMPANY_USER",
    })
    assert resp_viewer.status_code == 403


def test_tenant_scoped_admin_cannot_mint_platform_admin_via_legacy_endpoint(client):
    """
    P0 regression: a Company Admin must NOT be able to use the deprecated
    /auth/admin/create-user endpoint at all — it is Platform-Admin-only. Also
    verifies any user a Platform Admin legitimately creates through it is
    scoped to the expected tenant.
    """
    from app.shared.models import TenantORM

    with SessionLocal() as db:
        db.add(TenantORM(id="tenant-escalation-test", name="Escalation Test Co", is_active=True))
        company_admin = UserORM(
            username="company_admin_escalation",
            email="company_admin_escalation@test.com",
            hashed_password=hash_password("CompanyAdminPass123!"),
            role=UserRole.COMPANY_ADMIN,
            tenant_id="tenant-escalation-test",
            is_active=True,
        )
        db.add(company_admin)
        db.commit()
        db.refresh(company_admin)
        token = create_access_token(
            user_id=company_admin.id, username=company_admin.username,
            role="COMPANY_ADMIN", tenant_id="tenant-escalation-test",
        )

    headers = {"Authorization": f"Bearer {token}"}

    # A Company Admin cannot use this Platform-Admin-only endpoint at all —
    # not even to mint a global Platform Admin.
    resp = client.post("/auth/admin/create-user", headers=headers, json={
        "username": "minted_platform_admin",
        "email": "minted_platform_admin@evil.example",
        "password": "Password123!",
        "role": "PLATFORM_ADMIN",
    })
    assert resp.status_code == 403

    # Nor even a harmless, non-privileged user.
    resp2 = client.post("/auth/admin/create-user", headers=headers, json={
        "username": "minted_company_user",
        "email": "minted_company_user@evil.example",
        "password": "Password123!",
        "role": "COMPANY_USER",
    })
    assert resp2.status_code == 403

    with SessionLocal() as db:
        assert db.query(UserORM).filter(UserORM.username == "minted_platform_admin").first() is None
        assert db.query(UserORM).filter(UserORM.username == "minted_company_user").first() is None

    with SessionLocal() as db:
        db.query(UserORM).filter(UserORM.tenant_id == "tenant-escalation-test").delete()
        db.query(TenantORM).filter(TenantORM.id == "tenant-escalation-test").delete()
        db.commit()


def test_platform_admin_can_create_users_with_allowed_roles(client, seed_users):
    """E. PLATFORM_ADMIN calling /auth/admin/create-user can create users with any canonical role."""
    headers_admin = {"Authorization": f"Bearer {seed_users['admin']}"}

    roles_to_test = [
        ("created_platform_admin", "cpa@test.com", "PLATFORM_ADMIN"),
        ("created_company_admin", "cca@test.com", "COMPANY_ADMIN"),
        ("created_company_user", "ccu@test.com", "COMPANY_USER"),
    ]

    for uname, email, role in roles_to_test:
        resp = client.post("/auth/admin/create-user", headers=headers_admin, json={
            "username": uname,
            "email": email,
            "password": "SecurePassword123!",
            "role": role,
            "team_id": "ops-team",
        })
        assert resp.status_code == 201, f"Failed for {role}: {resp.text}"
        data = resp.json()
        assert data["username"] == uname
        assert data["role"] == role
        assert data["team_id"] == "ops-team"
        assert "password" not in data
        assert "hashed_password" not in data


def test_duplicate_username_and_email_protections(client, seed_users):
    """F. Verify duplicate username/email protections still work on both endpoints."""
    # Public register duplicate username
    r1 = client.post("/auth/register", json={
        "username": "sec_admin",  # already exists from seed_users
        "email": "fresh_email@test.com",
        "password": "Password123!",
    })
    assert r1.status_code == 409
    assert "already taken" in r1.json()["detail"].lower()

    # Public register duplicate email
    r2 = client.post("/auth/register", json={
        "username": "fresh_user",
        "email": "admin@test.com",  # already exists from seed_users
        "password": "Password123!",
    })
    assert r2.status_code == 409
    assert "already registered" in r2.json()["detail"].lower()

    # Admin create-user duplicate username
    headers_admin = {"Authorization": f"Bearer {seed_users['admin']}"}
    r3 = client.post("/auth/admin/create-user", headers=headers_admin, json={
        "username": "sec_admin",
        "email": "new_unique@test.com",
        "password": "Password123!",
        "role": "COMPANY_USER",
    })
    assert r3.status_code == 409


# ====================================================================
# FIX 2: REMOVE CLIENT-CONTROLLED approved_by TESTS
# ====================================================================

@pytest.fixture
def pending_job_team_a():
    """Create a test job in PENDING_APPROVAL status for team-a."""
    with SessionLocal() as db:
        now = utcnow()
        job = JobORM(
            job_id="JOB-SEC-001",
            team_id="team-a",
            status=JobStatus.PENDING_APPROVAL,
            submitted_at=now,
            deadline=now + timedelta(hours=24),
            runtime_minutes=60,
            power_kw=10.0,
            energy_kwh=10.0,
            region="IN-TG",
            container_image="greenshift/sim:v1",
        )
        db.add(job)
        db.flush()

        decision = ScheduleDecisionORM(
            job_id=job.job_id,
            selected_start=now + timedelta(hours=2),
            selected_end=now + timedelta(hours=3),
            carbon_intensity=350.0,
            carbon_emission=3.5,
            electricity_cost=1.2,
            reason="Lowest carbon slot",
            region_id="IN-TG",
            currency="USD",
        )
        db.add(decision)
        db.commit()
        decision_id = decision.id
    return "JOB-SEC-001", decision_id


def test_approve_job_records_authenticated_jwt_identity_ignores_fake_approved_by(
    client, seed_users, pending_job_team_a
):
    """A & E. Authenticated user approves a job sending fake approved_by: records JWT identity."""
    job_id, decision_id = pending_job_team_a
    headers = {"Authorization": f"Bearer {seed_users['lead_a']}"}

    # Craft payload attempting to spoof identity as "CEO_ALICE"
    payload = {
        "schedule_id": decision_id,
        "reason": "Legitimate approval reason",
        "approved_by": "CEO_ALICE_IMPERSONATOR",
    }

    resp = client.post(f"/api/v1/approval/{job_id}/approve", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["decision"] == "APPROVED"
    assert data["approved_by"] == "sec_lead_a"  # Must match JWT username!
    assert data["approved_by"] != "CEO_ALICE_IMPERSONATOR"

    # Verify database record
    with SessionLocal() as db:
        approval = db.query(ApprovalORM).filter(ApprovalORM.job_id == job_id).first()
        assert approval is not None
        assert approval.approved_by == "sec_lead_a"

        # Check audit event
        events = db.query(AuditEventORM).filter(AuditEventORM.job_id == job_id).all()
        assert any("sec_lead_a" in (e.payload_json or "") for e in events)
        assert not any("CEO_ALICE_IMPERSONATOR" in (e.payload_json or "") for e in events)


def test_decline_job_records_authenticated_jwt_identity_ignores_fake_approved_by(
    client, seed_users, pending_job_team_a
):
    """B & E. Authenticated user declines a job sending fake approved_by: records JWT identity."""
    job_id, decision_id = pending_job_team_a
    headers = {"Authorization": f"Bearer {seed_users['lead_a']}"}

    payload = {
        "schedule_id": decision_id,
        "reason": "Window conflicts with cluster upgrade",
        "approved_by": "SPOOFED_ADMIN",
    }

    resp = client.post(f"/api/v1/approval/{job_id}/decline", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["decision"] == "DECLINED"
    assert data["approved_by"] == "sec_lead_a"
    assert data["approved_by"] != "SPOOFED_ADMIN"

    with SessionLocal() as db:
        approval = db.query(ApprovalORM).filter(ApprovalORM.job_id == job_id).first()
        assert approval is not None
        assert approval.approved_by == "sec_lead_a"

        events = db.query(AuditEventORM).filter(AuditEventORM.job_id == job_id).all()
        assert any("sec_lead_a" in (e.payload_json or "") for e in events)
        assert not any("SPOOFED_ADMIN" in (e.payload_json or "") for e in events)


def test_normal_approval_succeeds_without_approved_by_field(
    client, seed_users, pending_job_team_a
):
    """C. Verify normal approval succeeds without client sending approved_by."""
    job_id, decision_id = pending_job_team_a
    headers = {"Authorization": f"Bearer {seed_users['lead_a']}"}

    resp = client.post(
        f"/api/v1/approval/{job_id}/approve",
        headers=headers,
        json={"schedule_id": decision_id, "reason": "Standard operational approval"},
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "APPROVED"
    assert resp.json()["approved_by"] == "sec_lead_a"


def test_normal_decline_succeeds_without_approved_by_field(
    client, seed_users, pending_job_team_a
):
    """D. Verify normal decline succeeds without client sending approved_by."""
    job_id, decision_id = pending_job_team_a
    headers = {"Authorization": f"Bearer {seed_users['lead_a']}"}

    resp = client.post(
        f"/api/v1/approval/{job_id}/decline",
        headers=headers,
        json={"schedule_id": decision_id, "reason": "Maintenance window"},
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "DECLINED"
    assert resp.json()["approved_by"] == "sec_lead_a"


def test_approval_request_schema_does_not_expose_approved_by():
    """F. Verify ApprovalRequest model does not contain approved_by field."""
    schema_properties = ApprovalRequest.model_json_schema().get("properties", {})
    assert "approved_by" not in schema_properties
    assert "schedule_id" in schema_properties
    assert "reason" in schema_properties


# ====================================================================
# FIX 3: MULTI-TENANT TEAM ISOLATION ON READ ENDPOINTS
# ====================================================================

@pytest.fixture
def multi_team_jobs():
    """Create jobs and schedule decisions across team-a and team-b."""
    with SessionLocal() as db:
        now = utcnow()
        job_a1 = JobORM(
            job_id="JOB-TEAM-A-001",
            team_id="team-a",
            status=JobStatus.PENDING_APPROVAL,
            submitted_at=now,
            deadline=now + timedelta(hours=12),
            runtime_minutes=30,
            power_kw=5.0,
            energy_kwh=2.5,
            region="IN-TG",
            container_image="greenshift/sim:v1",
        )
        job_a2 = JobORM(
            job_id="JOB-TEAM-A-002",
            team_id="team-a",
            status=JobStatus.SUBMITTED,
            submitted_at=now,
            deadline=now + timedelta(hours=12),
            runtime_minutes=45,
            power_kw=10.0,
            energy_kwh=7.5,
            region="IN-TG",
            container_image="greenshift/sim:v1",
        )
        job_b1 = JobORM(
            job_id="JOB-TEAM-B-001",
            team_id="team-b",
            status=JobStatus.PENDING_APPROVAL,
            submitted_at=now,
            deadline=now + timedelta(hours=12),
            runtime_minutes=60,
            power_kw=8.0,
            energy_kwh=8.0,
            region="IN-GJ",
            container_image="greenshift/sim:v1",
        )
        job_b2 = JobORM(
            job_id="JOB-TEAM-B-002",
            team_id="team-b",
            status=JobStatus.SUBMITTED,
            submitted_at=now,
            deadline=now + timedelta(hours=12),
            runtime_minutes=90,
            power_kw=12.0,
            energy_kwh=18.0,
            region="IN-GJ",
            container_image="greenshift/sim:v1",
        )
        db.add_all([job_a1, job_a2, job_b1, job_b2])
        db.flush()

        dec_a1 = ScheduleDecisionORM(
            job_id="JOB-TEAM-A-001",
            selected_start=now + timedelta(hours=1),
            selected_end=now + timedelta(hours=2),
            carbon_intensity=300.0,
            carbon_emission=1.5,
            electricity_cost=0.5,
            reason="Optimal slot A",
        )
        dec_b1 = ScheduleDecisionORM(
            job_id="JOB-TEAM-B-001",
            selected_start=now + timedelta(hours=2),
            selected_end=now + timedelta(hours=3),
            carbon_intensity=400.0,
            carbon_emission=3.2,
            electricity_cost=1.1,
            reason="Optimal slot B",
        )
        db.add_all([dec_a1, dec_b1])
        db.commit()


def test_team_lead_list_jobs_isolated_and_cannot_bypass_via_query_param(
    client, seed_users, multi_team_jobs
):
    """B. COMPANY_ADMIN (lead_a) sees every team's jobs within their company
    (own team-a AND team-b) — Company Admin is company-wide, not team-scoped.
    Per the Consistency & Security Hardening model: Company Admin -> own
    company + ALL its teams. An explicit ?team_id filter narrows the view,
    it does not restrict which teams a Company Admin is allowed to see."""
    headers_lead_a = {"Authorization": f"Bearer {seed_users['lead_a']}"}

    # 1. Unfiltered query -> sees both teams
    r1 = client.get("/api/v1/jobs", headers=headers_lead_a)
    assert r1.status_code == 200
    jobs_1 = r1.json()
    job_ids_1 = [j["job_id"] for j in jobs_1]
    assert "JOB-TEAM-A-001" in job_ids_1
    assert "JOB-TEAM-A-002" in job_ids_1
    assert "JOB-TEAM-B-001" in job_ids_1
    assert "JOB-TEAM-B-002" in job_ids_1

    # 2. Explicit ?team_id=team-b filter -> narrows to team-b (Company Admin
    # is authorized to filter by any team in their company)
    r2 = client.get("/api/v1/jobs?team_id=team-b", headers=headers_lead_a)
    assert r2.status_code == 200
    jobs_2 = r2.json()
    job_ids_2 = [j["job_id"] for j in jobs_2]
    assert "JOB-TEAM-A-001" not in job_ids_2
    assert "JOB-TEAM-B-001" in job_ids_2
    assert "JOB-TEAM-B-002" in job_ids_2


def test_team_lead_get_job_detail_enforces_team_isolation(
    client, seed_users, multi_team_jobs
):
    """C. COMPANY_ADMIN (lead_a) can fetch job detail for any team in their
    company, including a team other than their own (company-wide access)."""
    headers_lead_a = {"Authorization": f"Bearer {seed_users['lead_a']}"}

    # Own team job -> 200
    r_own = client.get("/api/v1/jobs/JOB-TEAM-A-001", headers=headers_lead_a)
    assert r_own.status_code == 200
    assert r_own.json()["job_id"] == "JOB-TEAM-A-001"

    # Other team's job, same company -> 200 (Company Admin, not team-scoped)
    r_other = client.get("/api/v1/jobs/JOB-TEAM-B-001", headers=headers_lead_a)
    assert r_other.status_code == 200
    assert r_other.json()["job_id"] == "JOB-TEAM-B-001"


def test_team_lead_get_job_history_enforces_team_isolation(
    client, seed_users, multi_team_jobs
):
    """D. COMPANY_ADMIN (lead_a) can fetch job history for any team in their
    company, including a team other than their own (company-wide access)."""
    headers_lead_a = {"Authorization": f"Bearer {seed_users['lead_a']}"}

    # Own team history -> 200
    r_own = client.get("/api/v1/jobs/JOB-TEAM-A-001/history", headers=headers_lead_a)
    assert r_own.status_code == 200

    # Other team's history, same company -> 200
    r_other = client.get("/api/v1/jobs/JOB-TEAM-B-001/history", headers=headers_lead_a)
    assert r_other.status_code == 200


def test_pending_approvals_company_admin_sees_every_team_in_company(
    client, seed_users, multi_team_jobs
):
    """E. COMPANY_ADMIN (lead_a) sees pending approvals for every team in
    their company (team-a AND team-b), not just their own team — Company
    Admin is company-wide, not team-scoped."""
    headers_lead_a = {"Authorization": f"Bearer {seed_users['lead_a']}"}

    r_a = client.get("/api/v1/approvals/pending", headers=headers_lead_a)
    assert r_a.status_code == 200
    job_ids = {item["job_id"] for item in r_a.json()}
    assert "JOB-TEAM-A-001" in job_ids
    assert "JOB-TEAM-B-001" in job_ids

    # An explicit ?team_id=team-b filter narrows the view (Company Admin may
    # filter by any team in their company).
    r_a_filtered = client.get("/api/v1/approvals/pending?team_id=team-b", headers=headers_lead_a)
    assert r_a_filtered.status_code == 200
    filtered_ids = {item["job_id"] for item in r_a_filtered.json()}
    assert filtered_ids == {"JOB-TEAM-B-001"}


def test_pending_approvals_company_user_restricted_to_own_team(
    client, seed_users, multi_team_jobs
):
    """A plain COMPANY_USER (operator_a, team-a) remains strictly locked to
    their own team's pending approvals, including against a ?team_id
    override attempt."""
    headers_op_a = {"Authorization": f"Bearer {seed_users['operator_a']}"}

    r_a = client.get("/api/v1/approvals/pending", headers=headers_op_a)
    assert r_a.status_code == 200
    items_a = r_a.json()
    assert len(items_a) == 1
    assert items_a[0]["job_id"] == "JOB-TEAM-A-001"
    assert items_a[0]["team_id"] == "team-a"

    r_a_tamper = client.get("/api/v1/approvals/pending?team_id=team-b", headers=headers_op_a)
    assert r_a_tamper.status_code == 200
    assert len(r_a_tamper.json()) == 1
    assert r_a_tamper.json()[0]["job_id"] == "JOB-TEAM-A-001"


def test_admin_cross_team_access_and_filtering(
    client, seed_users, multi_team_jobs
):
    """F. PLATFORM_ADMIN can see cross-team data and filter by team."""
    headers_admin = {"Authorization": f"Bearer {seed_users['admin']}"}

    # 1. List all jobs across all teams
    r_all = client.get("/api/v1/jobs", headers=headers_admin)
    assert r_all.status_code == 200
    all_job_ids = [j["job_id"] for j in r_all.json()]
    assert "JOB-TEAM-A-001" in all_job_ids
    assert "JOB-TEAM-B-001" in all_job_ids

    # 2. Filter by team-b as admin
    r_filtered = client.get("/api/v1/jobs?team_id=team-b", headers=headers_admin)
    assert r_filtered.status_code == 200
    filtered_ids = [j["job_id"] for j in r_filtered.json()]
    assert "JOB-TEAM-B-001" in filtered_ids
    assert "JOB-TEAM-B-002" in filtered_ids
    assert "JOB-TEAM-A-001" not in filtered_ids

    # 3. View detail of any job
    r_detail_a = client.get("/api/v1/jobs/JOB-TEAM-A-001", headers=headers_admin)
    assert r_detail_a.status_code == 200
    r_detail_b = client.get("/api/v1/jobs/JOB-TEAM-B-001", headers=headers_admin)
    assert r_detail_b.status_code == 200

    # 4. View history of any job
    r_hist_b = client.get("/api/v1/jobs/JOB-TEAM-B-001/history", headers=headers_admin)
    assert r_hist_b.status_code == 200

    # 5. Pending approvals: admin sees both teams
    r_pending = client.get("/api/v1/approvals/pending", headers=headers_admin)
    assert r_pending.status_code == 200
    pending_ids = [p["job_id"] for p in r_pending.json()]
    assert "JOB-TEAM-A-001" in pending_ids
    assert "JOB-TEAM-B-001" in pending_ids


def test_operator_and_viewer_team_isolation(
    client, seed_users, multi_team_jobs
):
    """G. Repeat key tests for COMPANY_USER accounts (operator_a, viewer_a)."""
    # COMPANY_USER (operator_a) from team-a
    headers_op = {"Authorization": f"Bearer {seed_users['operator_a']}"}
    r_op_jobs = client.get("/api/v1/jobs", headers=headers_op)
    assert r_op_jobs.status_code == 200
    assert all(j["team_id"] == "team-a" for j in r_op_jobs.json())

    r_op_cross = client.get("/api/v1/jobs/JOB-TEAM-B-001", headers=headers_op)
    assert r_op_cross.status_code == 403

    # COMPANY_USER (viewer_a) from team-a
    headers_view = {"Authorization": f"Bearer {seed_users['viewer_a']}"}
    r_view_jobs = client.get("/api/v1/jobs", headers=headers_view)
    assert r_view_jobs.status_code == 200
    assert all(j["team_id"] == "team-a" for j in r_view_jobs.json())

    r_view_cross = client.get("/api/v1/jobs/JOB-TEAM-B-001", headers=headers_view)
    assert r_view_cross.status_code == 403

    r_view_hist = client.get("/api/v1/jobs/JOB-TEAM-B-001/history", headers=headers_view)
    assert r_view_hist.status_code == 403
