"""
Tests for GreenShift Role-Based Access Control (RBAC) on Approval & Scheduling

GreenShift supports exactly three application roles: PLATFORM_ADMIN,
COMPANY_ADMIN, COMPANY_USER (see app.shared.models.UserRole). Company Admin
approval/decline authorization is scoped by tenant_id (company), not team_id —
team_id remains a data/organizational field but is not an authorization tier
(a Company Admin has full authority across every team within their own
company, matching how Company Admin already behaved before role consolidation).

Covers:
1. COMPANY_ADMIN approving own company's job -> 200 OK
2. COMPANY_ADMIN attempting another company's job -> 403/404 Forbidden
3. COMPANY_USER attempting approval -> 403 Forbidden
4. PLATFORM_ADMIN approving any company's job -> 200 OK
5. Unauthorized request (missing / invalid token) -> 401 Unauthorized
6. COMPANY_ADMIN declining own company job (200 OK) vs another company's job (403/404)
7. Service-level authorization validation unit tests
"""

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.database import init_db, SessionLocal
from app.shared.models import (
    ApprovalORM,
    AuditEventORM,
    JobORM,
    JobStatus,
    JobSubmitRequest,
    KubernetesExecutionORM,
    ScheduleDecisionORM,
    TenantORM,
    UserORM,
    UserRole,
)
from app.shared.auth import (
    hash_password,
    create_access_token,
)
from app.ingest.jobs import submit_job
from app.decide.service import schedule_and_store
from app.approval.service import (
    ApprovalPermissionError,
    approve_schedule,
    decline_schedule,
    check_user_approval_permission,
)
from app.shared.utils import utcnow


@pytest.fixture(autouse=True)
def setup_rbac_db():
    """Ensure clean database tables for users & jobs before each test."""
    from sqlalchemy import text as sa_text
    from app.shared.database import engine
    from app.shared.database import get_db
    from app.api.main import app as _app

    _app.dependency_overrides.pop(get_db, None)

    db = SessionLocal()
    try:
        db.query(ApprovalORM).delete()
        db.query(KubernetesExecutionORM).delete()
        db.query(ScheduleDecisionORM).delete()
        db.query(AuditEventORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()
        db.commit()
    finally:
        db.close()

    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(sa_text("PRAGMA wal_checkpoint(PASSIVE)"))
    except Exception:
        pass

    yield

    _app.dependency_overrides.pop(get_db, None)

    db = SessionLocal()
    try:
        db.query(ApprovalORM).delete()
        db.query(KubernetesExecutionORM).delete()
        db.query(ScheduleDecisionORM).delete()
        db.query(AuditEventORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()
        db.commit()
    finally:
        db.close()

    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(sa_text("PRAGMA wal_checkpoint(PASSIVE)"))
    except Exception:
        pass


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def users_and_tokens(client):
    """Create test users for all three canonical roles across two companies
    and return a dictionary of their tokens."""
    with SessionLocal() as db:
        db.add(TenantORM(id="tenant-a", name="Company A", is_active=True))
        db.add(TenantORM(id="tenant-b", name="Company B", is_active=True))
        db.commit()

        users = [
            ("admin_user", "admin@greenshift.io", "AdminPassword123!", UserRole.PLATFORM_ADMIN, None, "team-a"),
            ("company_admin_a", "admin_a@greenshift.io", "AdminAPassword123!", UserRole.COMPANY_ADMIN, "tenant-a", "team-a"),
            ("company_admin_b", "admin_b@greenshift.io", "AdminBPassword123!", UserRole.COMPANY_ADMIN, "tenant-b", "team-b"),
            ("company_user_a", "user_a@greenshift.io", "UserAPassword123!", UserRole.COMPANY_USER, "tenant-a", "team-a"),
        ]
        user_objs = {}
        for username, email, pwd, role, tenant_id, team in users:
            u = UserORM(
                username=username,
                email=email,
                hashed_password=hash_password(pwd),
                role=role,
                tenant_id=tenant_id,
                team_id=team,
                is_active=True,
            )
            db.add(u)
            user_objs[username] = u
        db.commit()
        for u in user_objs.values():
            db.refresh(u)

        ids = {name: u.id for name, u in user_objs.items()}

    tokens = {}
    for username, _email, pwd, _role, _tenant_id, _team in users:
        tokens[username] = client.post("/auth/login", json={
            "username": username,
            "password": pwd,
        }).json()["access_token"]

    return {
        "admin": {"id": ids["admin_user"], "token": tokens["admin_user"]},
        "company_admin_a": {"id": ids["company_admin_a"], "token": tokens["company_admin_a"], "tenant_id": "tenant-a"},
        "company_admin_b": {"id": ids["company_admin_b"], "token": tokens["company_admin_b"], "tenant_id": "tenant-b"},
        "company_user_a": {"id": ids["company_user_a"], "token": tokens["company_user_a"], "tenant_id": "tenant-a"},
    }


def create_test_pending_job(db, job_id: str, team_id: str, tenant_id: str = None) -> tuple[JobORM, ScheduleDecisionORM]:
    """Helper to create a job and schedule decision in PENDING_APPROVAL status."""
    now = utcnow()
    req = JobSubmitRequest(
        job_id=job_id,
        team_id=team_id,
        deadline=now + timedelta(hours=8),
        runtime_minutes=45,
        power_kw=5.0,
        region="IN-TG",
        container_image="greenshift/workload:latest",
    )
    job = submit_job(db, req, tenant_id=tenant_id)
    dec = schedule_and_store(db, job, record_audit=True)
    return job, dec


# ====================================================================
# 1. COMPANY_ADMIN Approving Own Company's Job (200 OK)
# ====================================================================

def test_company_admin_approves_own_company_job(client, users_and_tokens):
    db = SessionLocal()
    try:
        job, dec = create_test_pending_job(db, "JOB-COMPANY-A-001", "team-a", tenant_id="tenant-a")
    finally:
        db.close()

    token_a = users_and_tokens["company_admin_a"]["token"]
    headers = {"Authorization": f"Bearer {token_a}"}
    payload = {"schedule_id": dec.id, "reason": "Company A Admin approved"}

    response = client.post(f"/approval/{job.job_id}/approve", json=payload, headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["job_id"] == "JOB-COMPANY-A-001"
    assert data["decision"] == "APPROVED"
    assert data["job_status"] == "APPROVED"
    assert data["approved_by"] == "company_admin_a"

    # Verify job status in database
    db = SessionLocal()
    try:
        updated_job = db.get(JobORM, "JOB-COMPANY-A-001")
        assert updated_job.status == JobStatus.APPROVED
    finally:
        db.close()


# ====================================================================
# 2. COMPANY_ADMIN Attempting Another Company's Job (blocked)
# ====================================================================

def test_company_admin_attempting_another_company_job_is_blocked(client, users_and_tokens):
    db = SessionLocal()
    try:
        # Job belongs to tenant-b
        job, dec = create_test_pending_job(db, "JOB-COMPANY-B-001", "team-b", tenant_id="tenant-b")
    finally:
        db.close()

    # Company A Admin attempts to approve Company B's job
    token_a = users_and_tokens["company_admin_a"]["token"]
    headers = {"Authorization": f"Bearer {token_a}"}
    payload = {"schedule_id": dec.id, "reason": "Unauthorized attempt"}

    response = client.post(f"/approval/{job.job_id}/approve", json=payload, headers=headers)
    # Cross-tenant access is 404 (not 403) to avoid leaking job existence.
    assert response.status_code == 404

    # Confirm job status remains PENDING_APPROVAL
    db = SessionLocal()
    try:
        job_check = db.get(JobORM, "JOB-COMPANY-B-001")
        assert job_check.status == JobStatus.PENDING_APPROVAL
    finally:
        db.close()


# ====================================================================
# 3. COMPANY_USER Attempting Approval (403 Forbidden)
# ====================================================================

def test_company_user_attempting_approval_is_forbidden(client, users_and_tokens):
    db = SessionLocal()
    try:
        job, dec = create_test_pending_job(db, "JOB-COMPANY-A-002", "team-a", tenant_id="tenant-a")
    finally:
        db.close()

    token_user = users_and_tokens["company_user_a"]["token"]
    headers = {"Authorization": f"Bearer {token_user}"}
    payload = {"schedule_id": dec.id, "reason": "Company User attempt"}

    response = client.post(f"/approval/{job.job_id}/approve", json=payload, headers=headers)
    assert response.status_code == 403
    assert "not authorized" in response.json()["detail"].lower()

    # Test decline with a Company User is also forbidden
    response_dec = client.post(f"/approval/{job.job_id}/decline", json=payload, headers=headers)
    assert response_dec.status_code == 403
    assert "not authorized" in response_dec.json()["detail"].lower()


# ====================================================================
# 4. PLATFORM_ADMIN Approving Any Company's Job (200 OK)
# ====================================================================

def test_platform_admin_can_approve_any_company_job(client, users_and_tokens):
    db = SessionLocal()
    try:
        job_a, dec_a = create_test_pending_job(db, "JOB-ADMIN-A-001", "team-a", tenant_id="tenant-a")
        job_b, dec_b = create_test_pending_job(db, "JOB-ADMIN-B-001", "team-b", tenant_id="tenant-b")
    finally:
        db.close()

    token_admin = users_and_tokens["admin"]["token"]
    headers = {"Authorization": f"Bearer {token_admin}"}

    # Platform Admin approves Company A job
    res_a = client.post(f"/approval/{job_a.job_id}/approve", json={"schedule_id": dec_a.id}, headers=headers)
    assert res_a.status_code == 200
    assert res_a.json()["decision"] == "APPROVED"

    # Platform Admin approves Company B job
    res_b = client.post(f"/approval/{job_b.job_id}/approve", json={"schedule_id": dec_b.id}, headers=headers)
    assert res_b.status_code == 200
    assert res_b.json()["decision"] == "APPROVED"


# ====================================================================
# 5. Unauthorized Request Handling (401 Unauthorized)
# ====================================================================

def test_unauthorized_request_rejected(client):
    db = SessionLocal()
    try:
        job, dec = create_test_pending_job(db, "JOB-UNAUTH-001", "team-a")
    finally:
        db.close()

    payload = {"schedule_id": dec.id}

    # 1. No Authorization header
    res_no_auth = client.post(f"/approval/{job.job_id}/approve", json=payload)
    assert res_no_auth.status_code == 401
    assert "token required" in res_no_auth.json()["detail"].lower()

    # 2. Invalid / bogus token
    headers_bogus = {"Authorization": "Bearer not_a_valid_token_string"}
    res_bogus = client.post(f"/approval/{job.job_id}/approve", json=payload, headers=headers_bogus)
    assert res_bogus.status_code == 401
    assert "invalid" in res_bogus.json()["detail"].lower()


# ====================================================================
# 6. Decline Endpoint Authorization
# ====================================================================

def test_company_admin_decline_authorization(client, users_and_tokens):
    db = SessionLocal()
    try:
        job_a, dec_a = create_test_pending_job(db, "JOB-DEC-A-001", "team-a", tenant_id="tenant-a")
        job_b, dec_b = create_test_pending_job(db, "JOB-DEC-B-001", "team-b", tenant_id="tenant-b")
    finally:
        db.close()

    token_a = users_and_tokens["company_admin_a"]["token"]
    headers = {"Authorization": f"Bearer {token_a}"}

    # Company A Admin declining own company's job -> 200 OK
    res_own = client.post(
        f"/approval/{job_a.job_id}/decline",
        json={"schedule_id": dec_a.id, "reason": "Cost too high"},
        headers=headers,
    )
    assert res_own.status_code == 200
    assert res_own.json()["decision"] == "DECLINED"

    # Company A Admin declining Company B's job -> blocked (404, cross-tenant)
    res_other = client.post(
        f"/approval/{job_b.job_id}/decline",
        json={"schedule_id": dec_b.id, "reason": "Unauthorized decline"},
        headers=headers,
    )
    assert res_other.status_code == 404


# ====================================================================
# 7. Service-Level Unit Tests for check_user_approval_permission
# ====================================================================

def test_service_level_check_user_approval_permission():
    job_a = JobORM(job_id="JOB-A", team_id="team-a", tenant_id="tenant-a", status=JobStatus.PENDING_APPROVAL)

    platform_admin = UserORM(username="admin", role=UserRole.PLATFORM_ADMIN, is_active=True)
    company_admin_a = UserORM(username="admin_a", role=UserRole.COMPANY_ADMIN, tenant_id="tenant-a", is_active=True)
    company_admin_b = UserORM(username="admin_b", role=UserRole.COMPANY_ADMIN, tenant_id="tenant-b", is_active=True)
    company_user_a = UserORM(username="user_a", role=UserRole.COMPANY_USER, tenant_id="tenant-a", is_active=True)

    # Platform Admin passes
    check_user_approval_permission(job_a, platform_admin)

    # Company A Admin passes on a Company A job
    check_user_approval_permission(job_a, company_admin_a)

    # Company B Admin fails on a Company A job (cross-tenant -> 404)
    from app.approval.service import ApprovalNotFoundError
    with pytest.raises(ApprovalNotFoundError):
        check_user_approval_permission(job_a, company_admin_b)

    # Company User fails
    with pytest.raises(ApprovalPermissionError) as exc_user:
        check_user_approval_permission(job_a, company_user_a)
    assert exc_user.value.status_code == 403
