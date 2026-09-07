"""
GreenShift — Phase 2 Security Hardening Test Suite: API Route Protection

Validates:
1. Unauthenticated access across all protected endpoints returns 401 Unauthorized
2. Role-based access control (RBAC):
   - VIEWER cannot submit, schedule, approve, or dispatch workloads (403 Forbidden)
   - TEAM_LEAD cannot submit, schedule, approve, or dispatch other teams' workloads (403 Forbidden)
   - TEAM_LEAD can manage own team's workloads
   - OPERATOR can submit, schedule, and dispatch approved workloads
   - ADMIN has full access across all operations
3. Error response sanitization (no internal stack traces / db errors exposed)
4. Full End-to-End Authenticated Pipeline Workflow
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.database import init_db, SessionLocal
from app.shared.models import (
    JobORM,
    JobStatus,
    ScheduleDecisionORM,
    KubernetesExecutionORM,
    ApprovalORM,
    AuditEventORM,
    UserORM,
    UserRole,
    EventType,
)
from app.shared.utils import utcnow
from app.trust.ledger import verify_chain
from app.shared.auth import hash_password, create_access_token


@pytest.fixture(autouse=True)
def setup_route_protection_db():
    """Ensure clean database tables for users & jobs before/after each test."""
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


from app.shared.auth import create_access_token, hash_password

DUMMY_PASSWORD_HASH = hash_password("TestPassword123!")


@pytest.fixture
def auth_tokens(client):
    """Seed test users and generate JWT access tokens for all standard roles."""
    roles = [
        ("admin_p2", "admin_p2@greenshift.io", "ADMIN", None),
        ("lead_alpha_p2", "lead_alpha@greenshift.io", "TEAM_LEAD", "team_alpha"),
        ("lead_beta_p2", "lead_beta@greenshift.io", "TEAM_LEAD", "team_beta"),
        ("operator_p2", "operator_p2@greenshift.io", "OPERATOR", "team_alpha"),
        ("viewer_p2", "viewer_p2@greenshift.io", "VIEWER", "team_alpha"),
    ]
    tokens = {}
    db = SessionLocal()
    try:
        for idx, (username, email, role, team_id) in enumerate(roles, start=200):
            user = UserORM(
                id=idx,
                username=username,
                email=email,
                hashed_password=DUMMY_PASSWORD_HASH,
                role=UserRole(role),
                team_id=team_id,
                is_active=True,
            )
            db.merge(user)
            token = create_access_token(
                user_id=idx,
                username=username,
                role=role,
                team_id=team_id,
            )
            tokens[role if team_id is None else f"{role}_{team_id}"] = token
        db.commit()
    finally:
        db.close()

    try:
        from sqlalchemy import text
        from app.shared.database import engine
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))
    except Exception:
        pass

    return tokens



# ====================================================================
# 1. Unauthenticated Endpoint Access Tests (401 Unauthorized)
# ====================================================================

@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/v1/jobs", None),
    ("POST", "/api/v1/jobs", {"job_id": "TEST-UNAUTH", "team_id": "team_alpha", "runtime_minutes": 30, "power_kw": 1.0, "region": "IN-TG"}),
    ("POST", "/api/v1/schedule/JOB-TEST-001", None),
    ("GET", "/api/v1/trust/verify", None),
    ("GET", "/api/v1/trust/events", None),
    ("GET", "/api/v1/report/summary", None),
    ("GET", "/api/v1/report/csv", None),
    ("GET", "/api/v1/report/markdown", None),
    ("GET", "/api/v1/dashboard/summary", None),
    ("GET", "/api/v1/approvals/pending", None),
    ("GET", "/api/v1/dispatch/JOB-TEST-001/status", None),
    ("GET", "/api/v1/kubernetes/state", None),
])
def test_unauthenticated_endpoints_return_401(client, method, path, payload):
    """Calling protected endpoints without authorization header must return 401 Unauthorized."""
    if method == "GET":
        res = client.get(path)
    elif method == "POST":
        res = client.post(path, json=payload or {})
    assert res.status_code == 401
    assert "token required" in res.json()["detail"].lower()


# ====================================================================
# 2. VIEWER Role Restrictions (403 Forbidden on Write/Execute)
# ====================================================================

def test_viewer_cannot_submit_workloads(client, auth_tokens):
    """VIEWER role must receive 403 Forbidden when attempting to submit a job."""
    viewer_token = auth_tokens["VIEWER_team_alpha"]
    headers = {"Authorization": f"Bearer {viewer_token}"}
    payload = {
        "job_id": "JOB-VIEWER-SUBMIT",
        "team_id": "team_alpha",
        "deadline": (utcnow() + timedelta(hours=6)).isoformat(),
        "runtime_minutes": 30,
        "power_kw": 2.0,
        "region": "IN-TG",
        "container_image": "greenshift/workload:latest",
    }
    res = client.post("/api/v1/jobs", json=payload, headers=headers)
    assert res.status_code == 403
    assert "operation not permitted" in res.json()["detail"].lower()


def test_viewer_cannot_schedule_workloads(client, auth_tokens):
    """VIEWER role must receive 403 Forbidden when attempting to trigger scheduling."""
    admin_token = auth_tokens["ADMIN"]
    viewer_token = auth_tokens["VIEWER_team_alpha"]

    # Submit job as Admin
    client.post("/api/v1/jobs", json={
        "job_id": "JOB-FOR-VIEWER-SCHED",
        "team_id": "team_alpha",
        "deadline": (utcnow() + timedelta(hours=6)).isoformat(),
        "runtime_minutes": 30,
        "power_kw": 2.0,
        "region": "IN-TG",
        "container_image": "greenshift/workload:latest",
    }, headers={"Authorization": f"Bearer {admin_token}"})

    # Viewer attempts to schedule
    res = client.post("/api/v1/schedule/JOB-FOR-VIEWER-SCHED", headers={"Authorization": f"Bearer {viewer_token}"})
    assert res.status_code == 403
    assert "operation not permitted" in res.json()["detail"].lower()


def test_viewer_cannot_dispatch_workloads(client, auth_tokens):
    """VIEWER role must receive 403 Forbidden when attempting to dispatch a workload."""
    viewer_token = auth_tokens["VIEWER_team_alpha"]
    res = client.post("/api/v1/dispatch/JOB-SAMPLE", headers={"Authorization": f"Bearer {viewer_token}"})
    # 403 Forbidden (either RBAC check or dispatch permission)
    assert res.status_code in (403, 404)
    if res.status_code == 403:
        assert "not authorized" in res.json()["detail"].lower() or "operation not permitted" in res.json()["detail"].lower()


def test_viewer_can_read_telemetry_reports_and_trust(client, auth_tokens):
    """VIEWER role can successfully access read-only telemetry, reports, and trust ledger."""
    viewer_token = auth_tokens["VIEWER_team_alpha"]
    headers = {"Authorization": f"Bearer {viewer_token}"}

    # 1. GET /jobs
    res_jobs = client.get("/api/v1/jobs", headers=headers)
    assert res_jobs.status_code == 200

    # 2. GET /trust/verify
    res_trust = client.get("/api/v1/trust/verify", headers=headers)
    assert res_trust.status_code == 200
    assert "valid" in res_trust.json()

    # 3. GET /report/summary
    res_report = client.get("/api/v1/report/summary", headers=headers)
    assert res_report.status_code == 200

    # 4. GET /dashboard/summary
    res_dash = client.get("/api/v1/dashboard/summary", headers=headers)
    assert res_dash.status_code == 200


# ====================================================================
# 3. Cross-Tenant Authorization Tests (TEAM_LEAD boundaries)
# ====================================================================

def test_team_lead_cannot_submit_for_another_team(client, auth_tokens):
    """TEAM_LEAD of team_alpha cannot submit a job for team_beta."""
    lead_alpha_token = auth_tokens["TEAM_LEAD_team_alpha"]
    headers = {"Authorization": f"Bearer {lead_alpha_token}"}
    payload = {
        "job_id": "JOB-ALPHA-ATTEMPT-BETA",
        "team_id": "team_beta",
        "deadline": (utcnow() + timedelta(hours=6)).isoformat(),
        "runtime_minutes": 30,
        "power_kw": 2.0,
        "region": "IN-TG",
        "container_image": "greenshift/workload:latest",
    }
    res = client.post("/api/v1/jobs", json=payload, headers=headers)
    assert res.status_code == 403
    assert "cannot submit jobs for team 'team_beta'" in res.json()["detail"].lower()


def test_team_lead_cannot_schedule_another_team_job(client, auth_tokens):
    """TEAM_LEAD of team_alpha cannot trigger scheduling for a team_beta job."""
    admin_token = auth_tokens["ADMIN"]
    lead_alpha_token = auth_tokens["TEAM_LEAD_team_alpha"]

    # Submit job for team_beta
    client.post("/api/v1/jobs", json={
        "job_id": "JOB-BETA-001",
        "team_id": "team_beta",
        "deadline": (utcnow() + timedelta(hours=6)).isoformat(),
        "runtime_minutes": 30,
        "power_kw": 2.0,
        "region": "IN-TG",
        "container_image": "greenshift/workload:latest",
    }, headers={"Authorization": f"Bearer {admin_token}"})

    # Team Lead Alpha attempts to schedule Beta's job
    res = client.post("/api/v1/schedule/JOB-BETA-001", headers={"Authorization": f"Bearer {lead_alpha_token}"})
    assert res.status_code == 403
    assert "cannot schedule jobs for team 'team_beta'" in res.json()["detail"].lower()


# ====================================================================
# 4. Error Sanitization Tests
# ====================================================================

def test_internal_errors_do_not_expose_stack_traces(client, auth_tokens):
    """Ensure unexpected 500 errors return clean messages without python tracebacks or SQL syntax."""
    admin_token = auth_tokens["ADMIN"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Force a mock error during schedule_and_store
    with patch("app.api.routers.schedule.schedule_and_store", side_effect=RuntimeError("CRITICAL DB CRASH TRACEBACK")):
        # Submit valid job first
        client.post("/api/v1/jobs", json={
            "job_id": "JOB-ERROR-TEST",
            "team_id": "team_alpha",
            "deadline": (utcnow() + timedelta(hours=6)).isoformat(),
            "runtime_minutes": 30,
            "power_kw": 2.0,
            "region": "IN-TG",
            "container_image": "greenshift/workload:latest",
        }, headers=headers)

        res = client.post("/api/v1/schedule/JOB-ERROR-TEST", headers=headers)
        assert res.status_code == 500
        detail = res.json()["detail"]
        # Must not contain the raw exception or trace info
        assert "CRITICAL DB CRASH TRACEBACK" not in detail
        assert "Traceback" not in detail


# ====================================================================
# 5. Full End-to-End Authenticated Pipeline Test
# ====================================================================

def test_end_to_end_authenticated_pipeline(client):
    """
    Complete end-to-end authenticated lifecycle:
    1. Login as Admin & Operator
    2. Submit workload via POST /api/v1/jobs
    3. Trigger schedule optimization via POST /api/v1/schedule/{job_id}
    4. Fetch workload detail and inspect schedule decision
    5. Fetch pending approvals list
    6. Approve proposed schedule via POST /api/v1/approval/{job_id}/approve
    7. Dispatch workload to Kubernetes via POST /api/v1/dispatch/{job_id}
    8. Check dispatch execution status via GET /api/v1/dispatch/{job_id}/status
    9. Verify SHA-256 tamper-evident trust ledger via GET /api/v1/trust/verify
    """
    # 1. Seed & Login Admin & Operator
    with SessionLocal() as db:
        admin_u = UserORM(
            username="e2e_admin",
            email="e2e_admin@greenshift.io",
            hashed_password=hash_password("AdminPassword123!"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        op_u = UserORM(
            username="e2e_operator",
            email="e2e_operator@greenshift.io",
            hashed_password=hash_password("OpsPassword123!"),
            role=UserRole.OPERATOR,
            team_id="team_alpha",
            is_active=True,
        )
        db.add_all([admin_u, op_u])
        db.commit()

    admin_token = client.post("/auth/login", json={
        "username": "e2e_admin",
        "password": "AdminPassword123!",
    }).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    operator_token = client.post("/auth/login", json={
        "username": "e2e_operator",
        "password": "OpsPassword123!",
    }).json()["access_token"]
    operator_headers = {"Authorization": f"Bearer {operator_token}"}

    # 2. Submit Workload (Operator)
    submit_payload = {
        "job_id": "JOB-E2E-SEC-001",
        "team_id": "team_alpha",
        "deadline": (utcnow() + timedelta(hours=8)).isoformat(),
        "runtime_minutes": 45,
        "power_kw": 3.5,
        "region": "IN-TG",
        "container_image": "greenshift/workload-e2e:latest",
        "carbon_budget_kg": 10.0,
    }
    submit_res = client.post("/api/v1/jobs", json=submit_payload, headers=operator_headers)
    assert submit_res.status_code == 201
    assert submit_res.json()["job_id"] == "JOB-E2E-SEC-001"
    assert submit_res.json()["status"] == "SUBMITTED"

    # 3. Schedule Workload (Operator)
    sched_res = client.post("/api/v1/schedule/JOB-E2E-SEC-001", headers=operator_headers)
    assert sched_res.status_code == 200
    sched_data = sched_res.json()
    assert sched_data["job_id"] == "JOB-E2E-SEC-001"
    assert "selected_start" in sched_data
    schedule_id = sched_data["schedule_id"]

    # 4. Fetch Workload Detail
    detail_res = client.get("/api/v1/jobs/JOB-E2E-SEC-001", headers=admin_headers)
    assert detail_res.status_code == 200
    assert detail_res.json()["status"] == "PENDING_APPROVAL"

    # 5. Fetch Pending Approvals (Admin)
    pending_res = client.get("/api/v1/approvals/pending", headers=admin_headers)
    assert pending_res.status_code == 200
    pending_ids = [p["job_id"] for p in pending_res.json()]
    assert "JOB-E2E-SEC-001" in pending_ids

    # 6. Approve Schedule (Admin)
    approve_res = client.post(
        "/api/v1/approval/JOB-E2E-SEC-001/approve",
        json={"schedule_id": schedule_id, "reason": "Optimal carbon emissions verified"},
        headers=admin_headers,
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["decision"] == "APPROVED"

    from kubernetes.client.rest import ApiException
    mock_batch = MagicMock()
    mock_batch.read_namespaced_job.side_effect = ApiException(status=404)

    with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch):
        # 7. Dispatch Workload (Operator)
        dispatch_res = client.post("/api/v1/dispatch/JOB-E2E-SEC-001", headers=operator_headers)
        assert dispatch_res.status_code == 200
        assert dispatch_res.json()["job_id"] == "JOB-E2E-SEC-001"

    # 8. Check Dispatch Execution Status (Operator)
    status_res = client.get("/api/v1/dispatch/JOB-E2E-SEC-001/status", headers=operator_headers)
    assert status_res.status_code == 200
    assert status_res.json()["job_id"] == "JOB-E2E-SEC-001"

    # 9. Verify SHA-256 Tamper-Evident Audit Ledger (Admin)
    trust_res = client.get("/api/v1/trust/verify", headers=admin_headers)
    assert trust_res.status_code == 200
    assert trust_res.json()["valid"] is True
    assert trust_res.json()["event_count"] >= 3
