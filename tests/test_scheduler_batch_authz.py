"""
Regression tests for a genuine RBAC gap found during the Global RBAC
Consistency Audit (Consistency & Security Hardening pass, Section 4):
POST /api/v1/schedule/batch, POST /api/v1/demand-forecaster/train,
GET /api/v1/demand-forecaster/status, and GET /api/v1/scheduler/capacity-map
had no authentication dependency at all when AUTH_ENABLED=true, and
/schedule/batch queried+mutated JobORM with zero tenant/team scoping —
any caller (or none) could batch-schedule every tenant's submitted jobs.

Fix: /schedule/batch now requires authentication and scopes eligible jobs
exactly like app.api.tenant_scope.get_tenant_jobs (Platform Admin: global;
Company Admin: own company, all teams; Company User: own team only).
/demand-forecaster/train (mutates one shared global model) is now Platform
Admin only. The two read-only endpoints now require authentication (their
aggregate output is not tenant-scoped by design, matching the shared
dataset/workloads reference-data endpoint).
"""

from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import (
    APIKeyORM,
    JobORM,
    JobStatus,
    ScheduleDecisionORM,
    TenantORM,
    UserApprovalStatus,
    UserORM,
    UserRole,
)
from app.shared.auth import create_access_token, hash_password


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(APIKeyORM).delete()
        db.query(ScheduleDecisionORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()
        db.add(TenantORM(id="tenant-batch-a", name="Batch Corp A", is_active=True))
        db.add(TenantORM(id="tenant-batch-b", name="Batch Corp B", is_active=True))
        db.commit()
    yield
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(APIKeyORM).delete()
        db.query(ScheduleDecisionORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()
        db.commit()


@pytest.fixture
def client():
    return TestClient(app)


def _make_user(db, username, email, role, tenant_id=None, team_id=None):
    u = UserORM(
        username=username,
        email=email,
        hashed_password=hash_password("Pass123!"),
        role=role,
        tenant_id=tenant_id,
        team_id=team_id,
        approval_status=UserApprovalStatus.APPROVED.value,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    token = create_access_token(
        user_id=u.id, username=u.username,
        role=u.role.value if hasattr(u.role, "value") else str(u.role),
        tenant_id=u.tenant_id, team_id=u.team_id,
    )
    return {"Authorization": f"Bearer {token}"}


def _make_job(db, job_id, tenant_id, team_id):
    now = datetime.now(timezone.utc)
    job = JobORM(
        job_id=job_id,
        team_id=team_id,
        tenant_id=tenant_id,
        job_type="TRAINING",
        priority="HIGH",
        status=JobStatus.SUBMITTED,
        submitted_at=now,
        deadline=now + timedelta(hours=24),
        runtime_minutes=60,
        power_kw=10.0,
        region="IN-TG",
        container_image="python:3.10-slim",
    )
    db.add(job)
    db.commit()
    return job


def test_batch_schedule_requires_authentication(client):
    """No Authorization header, AUTH_ENABLED=true -> 401, not a silent global batch run."""
    resp = client.post("/api/v1/schedule/batch", json={})
    assert resp.status_code == 401


def test_company_admin_batch_schedule_only_affects_own_tenant(client):
    """A Company Admin's batch-schedule call must never touch another
    company's submitted jobs, even though no job_ids filter was given."""
    with SessionLocal() as db:
        admin_headers = _make_user(
            db, "batch_admin_a", "admin_a@batch.com",
            UserRole.COMPANY_ADMIN, tenant_id="tenant-batch-a", team_id="team-1",
        )
        _make_job(db, "JOB-A-BATCH-001", "tenant-batch-a", "team-1")
        _make_job(db, "JOB-B-BATCH-001", "tenant-batch-b", "team-1")

    resp = client.post("/api/v1/schedule/batch", json={"use_demand_forecast": False}, headers=admin_headers)
    assert resp.status_code == 200
    scheduled_ids = {d["job_id"] for d in resp.json()["decisions"]}
    assert "JOB-A-BATCH-001" in scheduled_ids
    assert "JOB-B-BATCH-001" not in scheduled_ids

    with SessionLocal() as db:
        job_b = db.get(JobORM, "JOB-B-BATCH-001")
        assert job_b.status == JobStatus.SUBMITTED  # untouched


def test_company_admin_batch_schedule_covers_every_team_in_own_company(client):
    """Company Admin batch-scheduling is company-wide, not team-scoped."""
    with SessionLocal() as db:
        admin_headers = _make_user(
            db, "batch_admin_multi", "admin_multi@batch.com",
            UserRole.COMPANY_ADMIN, tenant_id="tenant-batch-a", team_id="team-1",
        )
        _make_job(db, "JOB-TEAM1-BATCH-001", "tenant-batch-a", "team-1")
        _make_job(db, "JOB-TEAM2-BATCH-001", "tenant-batch-a", "team-2")

    resp = client.post("/api/v1/schedule/batch", json={"use_demand_forecast": False}, headers=admin_headers)
    assert resp.status_code == 200
    scheduled_ids = {d["job_id"] for d in resp.json()["decisions"]}
    assert "JOB-TEAM1-BATCH-001" in scheduled_ids
    assert "JOB-TEAM2-BATCH-001" in scheduled_ids


def test_company_user_batch_schedule_scoped_to_own_team_only(client):
    """A plain COMPANY_USER's batch-schedule call is locked to their own team."""
    with SessionLocal() as db:
        user_headers = _make_user(
            db, "batch_user_team1", "user_team1@batch.com",
            UserRole.COMPANY_USER, tenant_id="tenant-batch-a", team_id="team-1",
        )
        _make_job(db, "JOB-T1-BATCH-002", "tenant-batch-a", "team-1")
        _make_job(db, "JOB-T2-BATCH-002", "tenant-batch-a", "team-2")

    resp = client.post("/api/v1/schedule/batch", json={"use_demand_forecast": False}, headers=user_headers)
    assert resp.status_code == 200
    scheduled_ids = {d["job_id"] for d in resp.json()["decisions"]}
    assert "JOB-T1-BATCH-002" in scheduled_ids
    assert "JOB-T2-BATCH-002" not in scheduled_ids


def test_job_ids_filter_cannot_widen_batch_schedule_scope(client):
    """Explicitly requesting another company's job_id via job_ids must not
    bypass tenant scoping."""
    with SessionLocal() as db:
        admin_headers = _make_user(
            db, "batch_admin_narrow", "admin_narrow@batch.com",
            UserRole.COMPANY_ADMIN, tenant_id="tenant-batch-a", team_id="team-1",
        )
        _make_job(db, "JOB-CROSS-BATCH-001", "tenant-batch-b", "team-1")

    resp = client.post(
        "/api/v1/schedule/batch",
        json={"job_ids": ["JOB-CROSS-BATCH-001"], "use_demand_forecast": False},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["jobs_scheduled"] == 0

    with SessionLocal() as db:
        job = db.get(JobORM, "JOB-CROSS-BATCH-001")
        assert job.status == JobStatus.SUBMITTED  # untouched


def test_demand_forecaster_train_requires_platform_admin(client):
    with SessionLocal() as db:
        admin_headers = _make_user(
            db, "batch_company_admin", "cadmin@batch.com",
            UserRole.COMPANY_ADMIN, tenant_id="tenant-batch-a",
        )
    resp = client.post("/api/v1/demand-forecaster/train", headers=admin_headers)
    assert resp.status_code == 403


def test_demand_forecaster_status_requires_authentication(client):
    resp = client.get("/api/v1/demand-forecaster/status")
    assert resp.status_code == 401


def test_capacity_map_requires_authentication(client):
    resp = client.get("/api/v1/scheduler/capacity-map")
    assert resp.status_code == 401
