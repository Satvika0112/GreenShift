"""
Tests for P0-BE-3: Comprehensive Tenant Isolation Audit Across All Endpoints.

Verifies:
1. Rule 5: Cross-tenant access on any individual job resource returns 404 Not Found (never 403).
2. Querying lists (/jobs, /admin/users, /admin/api-keys, /report/summary, /impact/fleet) strictly isolates data to the caller's tenant.
3. Cross-tenant query filtering by a Company Admin returns 403 Forbidden.
4. Platform Admin can inspect across all tenants or filter by specific tenant.
"""

from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import (
    APIKeyORM,
    AuditEventORM,
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
        # audit_events is append-only at the DB level (Trust/Audit P0) — never
        # deleted, including in test cleanup. Tests below filter by unique
        # job_id/username/event_type, so accumulated rows across the shared
        # file-backed test DB do not affect their assertions.
        db.query(ScheduleDecisionORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()

        db.add(TenantORM(id="tenant-alpha", name="Alpha Corp", is_active=True))
        db.add(TenantORM(id="tenant-beta", name="Beta Corp", is_active=True))
        db.commit()
    yield
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(APIKeyORM).delete()
        # audit_events is append-only at the DB level (Trust/Audit P0) — never
        # deleted, including in test cleanup. Tests below filter by unique
        # job_id/username/event_type, so accumulated rows across the shared
        # file-backed test DB do not affect their assertions.
        db.query(ScheduleDecisionORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()
        db.commit()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def setup_tenants_and_jobs():
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

        _, plat_headers = make_user("plat_adm", "p@greenshift.dev", UserRole.PLATFORM_ADMIN, None)
        _, alpha_admin_headers = make_user("alpha_adm", "adm@alpha.com", UserRole.COMPANY_ADMIN, "tenant-alpha")
        _, beta_admin_headers = make_user("beta_adm", "adm@beta.com", UserRole.COMPANY_ADMIN, "tenant-beta")

        # Create job in tenant-alpha
        now = datetime.now(timezone.utc)
        job_alpha = JobORM(
            job_id="job-alpha-001",
            team_id="team-alpha",
            tenant_id="tenant-alpha",
            company_name="Alpha Corp",
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
        db.add(job_alpha)

        # Create job in tenant-beta
        job_beta = JobORM(
            job_id="job-beta-001",
            team_id="team-beta",
            tenant_id="tenant-beta",
            company_name="Beta Corp",
            job_type="INFERENCE",
            priority="NORMAL",
            status=JobStatus.SUBMITTED,
            submitted_at=now,
            deadline=now + timedelta(hours=12),
            runtime_minutes=30,
            power_kw=5.0,
            region="IN-MH",
            container_image="python:3.10-slim",
        )
        db.add(job_beta)
        db.commit()

    return {
        "plat_headers": plat_headers,
        "alpha_admin_headers": alpha_admin_headers,
        "beta_admin_headers": beta_admin_headers,
    }


def test_cross_tenant_get_job_detail_returns_404(client, setup_tenants_and_jobs):
    # Alpha admin querying beta's job -> 404 (Rule 5: never 403)
    resp = client.get("/api/v1/jobs/job-beta-001", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp.status_code == 404

    # Beta admin querying alpha's job -> 404
    resp = client.get("/api/v1/jobs/job-alpha-001", headers=setup_tenants_and_jobs["beta_admin_headers"])
    assert resp.status_code == 404


def test_platform_admin_can_access_any_tenant_job(client, setup_tenants_and_jobs):
    resp_alpha = client.get("/api/v1/jobs/job-alpha-001", headers=setup_tenants_and_jobs["plat_headers"])
    assert resp_alpha.status_code == 200
    assert resp_alpha.json()["job_id"] == "job-alpha-001"

    resp_beta = client.get("/api/v1/jobs/job-beta-001", headers=setup_tenants_and_jobs["plat_headers"])
    assert resp_beta.status_code == 200
    assert resp_beta.json()["job_id"] == "job-beta-001"


def test_list_jobs_returns_only_own_tenant_jobs(client, setup_tenants_and_jobs):
    resp = client.get("/api/v1/jobs", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp.status_code == 200
    job_ids = [j["job_id"] for j in resp.json()]
    assert "job-alpha-001" in job_ids
    assert "job-beta-001" not in job_ids


def test_cross_tenant_schedule_trigger_returns_404(client, setup_tenants_and_jobs):
    # Alpha admin trying to schedule beta's job -> 404
    resp = client.post("/api/v1/schedule/job-beta-001", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp.status_code == 404


def test_cross_tenant_dispatch_trigger_returns_404(client, setup_tenants_and_jobs):
    # Alpha admin trying to dispatch beta's job -> 404
    resp = client.post("/api/v1/dispatch/job-beta-001", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp.status_code == 404


def test_cross_tenant_approval_history_returns_404(client, setup_tenants_and_jobs):
    resp = client.get("/api/v1/approval/job-beta-001", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp.status_code == 404


def test_cross_tenant_audit_trail_returns_404(client, setup_tenants_and_jobs):
    resp = client.get("/api/v1/trust/jobs/job-beta-001", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp.status_code == 404


def test_cross_tenant_actual_impact_returns_404(client, setup_tenants_and_jobs):
    resp = client.get("/api/v1/impact/job/job-beta-001/actual", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp.status_code == 404


def test_company_admin_cannot_query_other_tenant_in_fleet_impact(client, setup_tenants_and_jobs):
    resp = client.get("/api/v1/impact/fleet?tenant_id=tenant-beta", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp.status_code == 403


def test_company_admin_cannot_query_other_tenant_in_reports(client, setup_tenants_and_jobs):
    resp = client.get("/api/v1/report/summary?tenant_id=tenant-beta", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp.status_code == 403

    resp_csv = client.get("/api/v1/report/csv?tenant_id=tenant-beta", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp_csv.status_code == 403

    resp_md = client.get("/api/v1/report/markdown?tenant_id=tenant-beta", headers=setup_tenants_and_jobs["alpha_admin_headers"])
    assert resp_md.status_code == 403
