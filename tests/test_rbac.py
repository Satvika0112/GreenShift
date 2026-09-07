"""
Tests for GreenShift Role-Based Access Control (RBAC) on Approval & Scheduling

Covers:
1. TEAM_LEAD approving own team job -> 200 OK
2. TEAM_LEAD attempting another team's job -> 403 Forbidden
3. VIEWER attempting approval -> 403 Forbidden
4. OPERATOR attempting approval -> 403 Forbidden
5. ADMIN approving any team's job -> 200 OK
6. Unauthorized request (missing / invalid token) -> 401 Unauthorized
7. TEAM_LEAD declining own team job (200 OK) vs another team's job (403 Forbidden)
8. Service-level authorization validation unit tests
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
    """Create test users for all roles and return a dictionary of their tokens."""
    with SessionLocal() as db:
        users = [
            ("admin_user", "admin@greenshift.io", "AdminPassword123!", UserRole.ADMIN, None),
            ("lead_team_a", "lead_a@greenshift.io", "LeadPassword123!", UserRole.TEAM_LEAD, "team-a"),
            ("lead_team_b", "lead_b@greenshift.io", "LeadPassword123!", UserRole.TEAM_LEAD, "team-b"),
            ("operator_user", "operator@greenshift.io", "OperatorPassword123!", UserRole.OPERATOR, "team-a"),
            ("viewer_user", "viewer@greenshift.io", "ViewerPassword123!", UserRole.VIEWER, "team-a"),
        ]
        user_objs = {}
        for username, email, pwd, role, team in users:
            u = UserORM(
                username=username,
                email=email,
                hashed_password=hash_password(pwd),
                role=role,
                team_id=team,
                is_active=True,
            )
            db.add(u)
            user_objs[username] = u
        db.commit()
        for u in user_objs.values():
            db.refresh(u)

        reg_admin = {"id": user_objs["admin_user"].id}
        reg_lead_a = {"id": user_objs["lead_team_a"].id}
        reg_lead_b = {"id": user_objs["lead_team_b"].id}
        reg_operator = {"id": user_objs["operator_user"].id}
        reg_viewer = {"id": user_objs["viewer_user"].id}

    token_admin = client.post("/auth/login", json={
        "username": "admin_user",
        "password": "AdminPassword123!",
    }).json()["access_token"]
    token_lead_a = client.post("/auth/login", json={
        "username": "lead_team_a",
        "password": "LeadPassword123!",
    }).json()["access_token"]
    token_lead_b = client.post("/auth/login", json={
        "username": "lead_team_b",
        "password": "LeadPassword123!",
    }).json()["access_token"]
    token_operator = client.post("/auth/login", json={
        "username": "operator_user",
        "password": "OperatorPassword123!",
    }).json()["access_token"]
    token_viewer = client.post("/auth/login", json={
        "username": "viewer_user",
        "password": "ViewerPassword123!",
    }).json()["access_token"]

    return {
        "admin": {"id": reg_admin["id"], "token": token_admin},
        "lead_a": {"id": reg_lead_a["id"], "token": token_lead_a, "team_id": "team-a"},
        "lead_b": {"id": reg_lead_b["id"], "token": token_lead_b, "team_id": "team-b"},
        "operator": {"id": reg_operator["id"], "token": token_operator},
        "viewer": {"id": reg_viewer["id"], "token": token_viewer},
    }


def create_test_pending_job(db, job_id: str, team_id: str) -> tuple[JobORM, ScheduleDecisionORM]:
    """Helper to create a job and schedule decision in PENDING_APPROVAL status."""
    from sqlalchemy import text as sa_text
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
    job = submit_job(db, req)
    dec = schedule_and_store(db, job, record_audit=True)
    return job, dec


# ====================================================================
# 1. TEAM_LEAD Approving Own Team Job (200 OK)
# ====================================================================

def test_team_lead_approves_own_team_job(client, users_and_tokens):
    db = SessionLocal()
    try:
        job, dec = create_test_pending_job(db, "JOB-TEAM-A-001", "team-a")
    finally:
        db.close()

    token_a = users_and_tokens["lead_a"]["token"]
    headers = {"Authorization": f"Bearer {token_a}"}
    payload = {"schedule_id": dec.id, "reason": "Team A Lead approved"}

    response = client.post(f"/approval/{job.job_id}/approve", json=payload, headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["job_id"] == "JOB-TEAM-A-001"
    assert data["decision"] == "APPROVED"
    assert data["job_status"] == "APPROVED"
    assert data["approved_by"] == "lead_team_a"

    # Verify job status in database
    db = SessionLocal()
    try:
        updated_job = db.get(JobORM, "JOB-TEAM-A-001")
        assert updated_job.status == JobStatus.APPROVED
    finally:
        db.close()


# ====================================================================
# 2. TEAM_LEAD Attempting Another Team's Job (403 Forbidden)
# ====================================================================

def test_team_lead_attempting_another_team_job_is_forbidden(client, users_and_tokens):
    db = SessionLocal()
    try:
        # Job belongs to team-b
        job, dec = create_test_pending_job(db, "JOB-TEAM-B-001", "team-b")
    finally:
        db.close()

    # Team A Lead attempts to approve Team B job
    token_a = users_and_tokens["lead_a"]["token"]
    headers = {"Authorization": f"Bearer {token_a}"}
    payload = {"schedule_id": dec.id, "reason": "Unauthorized attempt"}

    response = client.post(f"/approval/{job.job_id}/approve", json=payload, headers=headers)
    assert response.status_code == 403
    assert "not authorized to approve/decline jobs for team 'team-b'" in response.json()["detail"].lower()

    # Confirm job status remains PENDING_APPROVAL
    db = SessionLocal()
    try:
        job_check = db.get(JobORM, "JOB-TEAM-B-001")
        assert job_check.status == JobStatus.PENDING_APPROVAL
    finally:
        db.close()


# ====================================================================
# 3. VIEWER Attempting Approval (403 Forbidden)
# ====================================================================

def test_viewer_attempting_approval_is_forbidden(client, users_and_tokens):
    db = SessionLocal()
    try:
        job, dec = create_test_pending_job(db, "JOB-TEAM-A-002", "team-a")
    finally:
        db.close()

    token_viewer = users_and_tokens["viewer"]["token"]
    headers = {"Authorization": f"Bearer {token_viewer}"}
    payload = {"schedule_id": dec.id, "reason": "Viewer attempt"}

    response = client.post(f"/approval/{job.job_id}/approve", json=payload, headers=headers)
    assert response.status_code == 403
    assert "viewer" in response.json()["detail"].lower()

    # Test decline with viewer is also forbidden
    response_dec = client.post(f"/approval/{job.job_id}/decline", json=payload, headers=headers)
    assert response_dec.status_code == 403
    assert "viewer" in response_dec.json()["detail"].lower()


# ====================================================================
# 4. OPERATOR Attempting Approval (403 Forbidden)
# ====================================================================

def test_operator_attempting_approval_is_forbidden(client, users_and_tokens):
    db = SessionLocal()
    try:
        job, dec = create_test_pending_job(db, "JOB-TEAM-A-003", "team-a")
    finally:
        db.close()

    token_op = users_and_tokens["operator"]["token"]
    headers = {"Authorization": f"Bearer {token_op}"}
    payload = {"schedule_id": dec.id, "reason": "Operator attempt"}

    response = client.post(f"/approval/{job.job_id}/approve", json=payload, headers=headers)
    assert response.status_code == 403
    assert "operator" in response.json()["detail"].lower()


# ====================================================================
# 5. ADMIN Approving Any Team's Job (200 OK)
# ====================================================================

def test_admin_can_approve_any_team_job(client, users_and_tokens):
    db = SessionLocal()
    try:
        job_a, dec_a = create_test_pending_job(db, "JOB-ADMIN-A-001", "team-a")
        job_b, dec_b = create_test_pending_job(db, "JOB-ADMIN-B-001", "team-b")
    finally:
        db.close()

    token_admin = users_and_tokens["admin"]["token"]
    headers = {"Authorization": f"Bearer {token_admin}"}

    # Admin approves Team A job
    res_a = client.post(f"/approval/{job_a.job_id}/approve", json={"schedule_id": dec_a.id}, headers=headers)
    assert res_a.status_code == 200
    assert res_a.json()["decision"] == "APPROVED"

    # Admin approves Team B job
    res_b = client.post(f"/approval/{job_b.job_id}/approve", json={"schedule_id": dec_b.id}, headers=headers)
    assert res_b.status_code == 200
    assert res_b.json()["decision"] == "APPROVED"


# ====================================================================
# 6. Unauthorized Request Handling (401 Unauthorized)
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
# 7. Decline Endpoint Authorization
# ====================================================================

def test_team_lead_decline_authorization(client, users_and_tokens):
    db = SessionLocal()
    try:
        job_a, dec_a = create_test_pending_job(db, "JOB-DEC-A-001", "team-a")
        job_b, dec_b = create_test_pending_job(db, "JOB-DEC-B-001", "team-b")
    finally:
        db.close()

    token_a = users_and_tokens["lead_a"]["token"]
    headers = {"Authorization": f"Bearer {token_a}"}

    # Team A lead declining own job -> 200 OK
    res_own = client.post(
        f"/approval/{job_a.job_id}/decline",
        json={"schedule_id": dec_a.id, "reason": "Cost too high"},
        headers=headers,
    )
    assert res_own.status_code == 200
    assert res_own.json()["decision"] == "DECLINED"

    # Team A lead declining Team B job -> 403 Forbidden
    res_other = client.post(
        f"/approval/{job_b.job_id}/decline",
        json={"schedule_id": dec_b.id, "reason": "Unauthorized decline"},
        headers=headers,
    )
    assert res_other.status_code == 403


# ====================================================================
# 8. Service-Level Unit Tests for check_user_approval_permission
# ====================================================================

def test_service_level_check_user_approval_permission():
    job_a = JobORM(job_id="JOB-A", team_id="team-a", status=JobStatus.PENDING_APPROVAL)

    admin_user = UserORM(username="admin", role=UserRole.ADMIN, is_active=True)
    lead_a = UserORM(username="lead_a", role=UserRole.TEAM_LEAD, team_id="team-a", is_active=True)
    lead_b = UserORM(username="lead_b", role=UserRole.TEAM_LEAD, team_id="team-b", is_active=True)
    operator = UserORM(username="operator", role=UserRole.OPERATOR, team_id="team-a", is_active=True)
    viewer = UserORM(username="viewer", role=UserRole.VIEWER, team_id="team-a", is_active=True)

    # Admin passes
    check_user_approval_permission(job_a, admin_user)

    # Team A lead passes on Job A
    check_user_approval_permission(job_a, lead_a)

    # Team B lead fails on Job A
    with pytest.raises(ApprovalPermissionError) as exc_b:
        check_user_approval_permission(job_a, lead_b)
    assert exc_b.value.status_code == 403

    # Operator fails
    with pytest.raises(ApprovalPermissionError) as exc_op:
        check_user_approval_permission(job_a, operator)
    assert exc_op.value.status_code == 403

    # Viewer fails
    with pytest.raises(ApprovalPermissionError) as exc_view:
        check_user_approval_permission(job_a, viewer)
    assert exc_view.value.status_code == 403
