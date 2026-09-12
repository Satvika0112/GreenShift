"""
Regression tests for the Consistency & Security Hardening pass — Section 1
(Authenticated Identity Consistency) and Section 11, item 5.

Root-cause bug fixed in app.api.tenant_scope.get_tenant_jobs: the function
used `is_admin = is_platform_admin(identity)` to decide whether to apply
team-level filtering, which meant a Company Admin (is_platform_admin=False)
was incorrectly restricted to only their own team's jobs whenever their
team_id happened to be set — contradicting the documented and required
model: Company Admin -> own company + ALL its teams, Company User -> own
team only, Platform Admin -> global.

These tests exercise the real /api/v1/jobs endpoints (not just the helper
directly) so they also cover app/api/routers/ingest.py's actual wiring.
"""

from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import (
    APIKeyORM,
    ApprovalORM,
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
        db.query(ApprovalORM).delete()
        db.query(APIKeyORM).delete()
        db.query(ScheduleDecisionORM).delete()
        db.query(JobORM).delete()
        db.query(UserORM).delete()
        db.query(TenantORM).delete()
        db.add(TenantORM(id="tenant-teamscope", name="TeamScope Corp", is_active=True))
        db.commit()
    yield
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(ApprovalORM).delete()
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
        user_id=u.id,
        username=u.username,
        role=u.role.value if hasattr(u.role, "value") else str(u.role),
        tenant_id=u.tenant_id,
        team_id=u.team_id,
    )
    return {"Authorization": f"Bearer {token}"}


def _make_job(db, job_id, tenant_id, team_id):
    now = datetime.now(timezone.utc)
    db.add(JobORM(
        job_id=job_id,
        team_id=team_id,
        tenant_id=tenant_id,
        company_name="TeamScope Corp",
        job_type="TRAINING",
        priority="HIGH",
        status=JobStatus.SUBMITTED,
        submitted_at=now,
        deadline=now + timedelta(hours=24),
        runtime_minutes=60,
        power_kw=10.0,
        region="IN-TG",
        container_image="python:3.10-slim",
    ))
    db.commit()


@pytest.fixture
def scoped_setup():
    with SessionLocal() as db:
        admin_headers = _make_user(
            db, "ts_company_admin", "admin@teamscope.com",
            UserRole.COMPANY_ADMIN, tenant_id="tenant-teamscope", team_id="team-red",
        )
        red_user_headers = _make_user(
            db, "ts_red_user", "red@teamscope.com",
            UserRole.COMPANY_USER, tenant_id="tenant-teamscope", team_id="team-red",
        )
        blue_user_headers = _make_user(
            db, "ts_blue_user", "blue@teamscope.com",
            UserRole.COMPANY_USER, tenant_id="tenant-teamscope", team_id="team-blue",
        )
        no_team_user_headers = _make_user(
            db, "ts_noteam_user", "noteam@teamscope.com",
            UserRole.COMPANY_USER, tenant_id="tenant-teamscope", team_id=None,
        )
        plat_headers = _make_user(
            db, "ts_plat_admin", "plat@greenshift.dev",
            UserRole.PLATFORM_ADMIN, tenant_id=None, team_id=None,
        )

        _make_job(db, "job-red-001", "tenant-teamscope", "team-red")
        _make_job(db, "job-blue-001", "tenant-teamscope", "team-blue")

    return {
        "admin_headers": admin_headers,
        "red_user_headers": red_user_headers,
        "blue_user_headers": blue_user_headers,
        "no_team_user_headers": no_team_user_headers,
        "plat_headers": plat_headers,
    }


class TestCompanyAdminSeesAllTeamsInOwnCompany:
    def test_list_jobs_includes_every_team(self, client, scoped_setup):
        resp = client.get("/api/v1/jobs", headers=scoped_setup["admin_headers"])
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()}
        assert "job-red-001" in job_ids
        assert "job-blue-001" in job_ids

    def test_can_fetch_job_detail_for_a_team_that_is_not_their_own(self, client, scoped_setup):
        resp = client.get("/api/v1/jobs/job-blue-001", headers=scoped_setup["admin_headers"])
        assert resp.status_code == 200
        assert resp.json()["job_id"] == "job-blue-001"

    def test_can_still_filter_by_a_specific_team_id(self, client, scoped_setup):
        resp = client.get("/api/v1/jobs?team_id=team-blue", headers=scoped_setup["admin_headers"])
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()}
        assert job_ids == {"job-blue-001"}


class TestCompanyUserRestrictedToOwnTeam:
    def test_list_jobs_only_shows_own_team(self, client, scoped_setup):
        resp = client.get("/api/v1/jobs", headers=scoped_setup["red_user_headers"])
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()}
        assert job_ids == {"job-red-001"}

    def test_cannot_fetch_job_detail_of_another_team_in_same_tenant(self, client, scoped_setup):
        resp = client.get("/api/v1/jobs/job-blue-001", headers=scoped_setup["red_user_headers"])
        assert resp.status_code == 403

    def test_team_id_query_param_cannot_widen_access_to_another_team(self, client, scoped_setup):
        resp = client.get("/api/v1/jobs?team_id=team-blue", headers=scoped_setup["red_user_headers"])
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()}
        assert "job-blue-001" not in job_ids


class TestPlatformAdminGlobalAccess:
    def test_list_jobs_sees_every_team_and_tenant(self, client, scoped_setup):
        resp = client.get("/api/v1/jobs", headers=scoped_setup["plat_headers"])
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()}
        assert "job-red-001" in job_ids
        assert "job-blue-001" in job_ids

    def test_can_fetch_any_job_detail(self, client, scoped_setup):
        resp = client.get("/api/v1/jobs/job-red-001", headers=scoped_setup["plat_headers"])
        assert resp.status_code == 200


class TestReportEndpointsTeamScoping:
    """/report/summary and /report/csv accept an optional team_id query
    param and, unlike /jobs, previously never clamped it for a plain
    Company User — allowing a within-tenant cross-team data leak of
    per-job carbon/cost/SLA report rows. Same fix class as /impact/fleet."""

    def test_company_user_team_id_override_is_clamped(self, client, scoped_setup):
        resp = client.get("/api/v1/report/summary?team_id=team-blue", headers=scoped_setup["red_user_headers"])
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()["jobs"]}
        assert "job-blue-001" not in job_ids

    def test_company_user_csv_team_id_override_is_clamped(self, client, scoped_setup):
        resp = client.get("/api/v1/report/csv?team_id=team-blue", headers=scoped_setup["red_user_headers"])
        assert resp.status_code == 200
        assert "job-blue-001" not in resp.text

    def test_company_admin_may_still_filter_report_by_any_team(self, client, scoped_setup):
        resp = client.get("/api/v1/report/summary?team_id=team-blue", headers=scoped_setup["admin_headers"])
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()["jobs"]}
        assert "job-blue-001" in job_ids
        assert "job-red-001" not in job_ids


class TestMissingTeamContextNeverBroadensAccess:
    """A Company User with no team assigned yet must fail closed (see
    nothing team-scoped), never fail open to the whole tenant."""

    def test_user_with_no_team_sees_no_team_scoped_jobs(self, client, scoped_setup):
        resp = client.get("/api/v1/jobs", headers=scoped_setup["no_team_user_headers"])
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()}
        assert job_ids == set()

    def test_user_with_no_team_cannot_fetch_a_teamed_job_by_id(self, client, scoped_setup):
        resp = client.get("/api/v1/jobs/job-red-001", headers=scoped_setup["no_team_user_headers"])
        assert resp.status_code == 403


@pytest.fixture
def approvals_setup():
    """Two teams within one company, each with a decided (one pending, one
    declined) approval — mirrors app.api.routers.approval's own inline
    tenant/team scoping (a separate code path from get_tenant_jobs)."""
    with SessionLocal() as db:
        admin_headers = _make_user(
            db, "appr_company_admin", "appr_admin@teamscope.com",
            UserRole.COMPANY_ADMIN, tenant_id="tenant-teamscope", team_id="team-red",
        )
        red_user_headers = _make_user(
            db, "appr_red_user", "appr_red@teamscope.com",
            UserRole.COMPANY_USER, tenant_id="tenant-teamscope", team_id="team-red",
        )

        now = datetime.now(timezone.utc)

        def _job_with_decision(job_id, team_id, decision):
            job = JobORM(
                job_id=job_id, team_id=team_id, tenant_id="tenant-teamscope",
                company_name="TeamScope Corp", job_type="TRAINING", priority="HIGH",
                status=JobStatus.PENDING_APPROVAL if decision is None else (
                    JobStatus.DECLINED if decision == "DECLINED" else JobStatus.APPROVED
                ),
                submitted_at=now, deadline=now + timedelta(hours=24),
                runtime_minutes=60, power_kw=10.0, region="IN-TG",
                container_image="python:3.10-slim",
            )
            db.add(job)
            db.flush()
            sd = ScheduleDecisionORM(
                job_id=job_id, selected_start=now + timedelta(hours=1), selected_end=now + timedelta(hours=2),
                carbon_intensity=300.0, carbon_emission=1.0, electricity_cost=0.5, reason="test",
            )
            db.add(sd)
            db.flush()
            if decision is not None:
                db.add(ApprovalORM(job_id=job_id, schedule_decision_id=sd.id, decision=decision, approved_by="tester"))
            db.commit()

        _job_with_decision("job-appr-red-pending", "team-red", None)
        _job_with_decision("job-appr-blue-pending", "team-blue", None)
        _job_with_decision("job-appr-red-declined", "team-red", "DECLINED")
        _job_with_decision("job-appr-blue-declined", "team-blue", "DECLINED")

    return {"admin_headers": admin_headers, "red_user_headers": red_user_headers}


class TestApprovalEndpointsCompanyAdminSeesAllTeams:
    """Real gap found in app.api.routers.approval: three endpoints
    (pending, declined, history) had their own inline tenant/team scoping
    that forced team_id=current_user.team_id for ANY non-Platform-Admin,
    incorrectly restricting Company Admin to their own team — the same bug
    class already fixed at the root in app.api.tenant_scope.get_tenant_jobs,
    but this code path doesn't go through that helper."""

    def test_pending_approvals_company_admin_sees_both_teams(self, client, approvals_setup):
        resp = client.get("/api/v1/approvals/pending", headers=approvals_setup["admin_headers"])
        assert resp.status_code == 200
        job_ids = {i["job_id"] for i in resp.json()}
        assert "job-appr-red-pending" in job_ids
        assert "job-appr-blue-pending" in job_ids

    def test_declined_approvals_company_admin_sees_both_teams(self, client, approvals_setup):
        resp = client.get("/api/v1/approvals/declined", headers=approvals_setup["admin_headers"])
        assert resp.status_code == 200
        job_ids = {i["job_id"] for i in resp.json()}
        assert "job-appr-red-declined" in job_ids
        assert "job-appr-blue-declined" in job_ids

    def test_approval_history_company_admin_sees_both_teams(self, client, approvals_setup):
        resp = client.get("/api/v1/approvals/history", headers=approvals_setup["admin_headers"])
        assert resp.status_code == 200
        job_ids = {i["job_id"] for i in resp.json()}
        assert "job-appr-red-declined" in job_ids
        assert "job-appr-blue-declined" in job_ids

    def test_company_user_still_restricted_to_own_team_on_all_three(self, client, approvals_setup):
        headers = approvals_setup["red_user_headers"]

        pending = client.get("/api/v1/approvals/pending", headers=headers).json()
        assert {i["job_id"] for i in pending} == {"job-appr-red-pending"}

        declined = client.get("/api/v1/approvals/declined", headers=headers).json()
        assert {i["job_id"] for i in declined} == {"job-appr-red-declined"}

        history = client.get("/api/v1/approvals/history", headers=headers).json()
        assert {i["job_id"] for i in history} == {"job-appr-red-declined"}
