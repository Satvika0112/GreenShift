"""
Tests for BRSR-Aligned Sustainability Report Strengthening.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.ingest.service import submit_job
from app.decide.service import schedule_and_store
from app.shared.auth import create_access_token, hash_password
from app.shared.database import get_db
from app.shared.models import JobORM, JobStatus, JobSubmitRequest, TenantORM, UserORM, UserRole
from app.trust.report import generate_report, generate_markdown_summary, _aggregate, _aggregate_by_region, _job_row


def test_aggregate_includes_regional_breakdown(db):
    """Verify by_region key with per-region job_count, energy, carbon_avoided."""
    req1 = JobSubmitRequest(
        team_id="BRSR-TEAM-1",
        deadline=datetime.now(timezone.utc) + timedelta(hours=24),
        runtime_minutes=60,
        power_kw=1.0,
        region="IN-WE",
        container_image="greenshift/sample-workload:latest",
        cpu_request="100m",
        memory_request="64Mi",
    )
    req2 = JobSubmitRequest(
        team_id="BRSR-TEAM-2",
        deadline=datetime.now(timezone.utc) + timedelta(hours=24),
        runtime_minutes=120,
        power_kw=2.0,
        region="IN-SO",
        container_image="greenshift/sample-workload:latest",
        cpu_request="200m",
        memory_request="128Mi",
    )
    job1 = submit_job(db, req1)
    job2 = submit_job(db, req2)
    schedule_and_store(db, job1)
    schedule_and_store(db, job2)

    report = generate_report(db)
    summary = report["summary"]

    assert "by_region" in summary
    by_region = summary["by_region"]
    assert job1.region in by_region
    assert job2.region in by_region


def test_job_row_cost_is_not_double_multiplied_by_energy(db):
    """_job_row's greenshift_cost_usd/baseline_cost_usd must be
    ScheduleDecisionORM.electricity_cost/baseline_cost verbatim — both are
    already energy_kwh * price_per_kwh_usd totals (see
    app.decide.impact_calculator.calculate_impact). A prior regression here
    re-multiplied the already-total electricity_cost by energy_kwh a second
    time, inflating every greenshift_cost_usd (and every aggregate derived
    from it) by a factor of energy_kwh. power_kw/runtime_minutes below are
    chosen so energy_kwh (=4.0 * 1.5 = 6.0) is far from 1.0, so a
    reintroduced double-multiply would be caught by a plain equality check."""
    req = JobSubmitRequest(
        team_id="BRSR-COST-CHECK",
        deadline=datetime.now(timezone.utc) + timedelta(hours=24),
        runtime_minutes=90,
        power_kw=4.0,
        region="IN-WE",
        container_image="greenshift/sample-workload:latest",
        cpu_request="100m",
        memory_request="64Mi",
    )
    job = submit_job(db, req)
    schedule_and_store(db, job)

    sd = job.schedule_decision
    assert sd is not None
    assert sd.electricity_cost is not None

    row = _job_row(job)
    assert row["energy_kwh"] == pytest.approx(6.0, rel=1e-6)
    assert row["greenshift_cost_usd"] == pytest.approx(sd.electricity_cost, rel=1e-9)
    assert row["baseline_cost_usd"] == pytest.approx(sd.baseline_cost, rel=1e-9)


def test_aggregate_includes_energy_intensity(db):
    """energy_intensity_kwh_per_job is calculated correctly as total_energy / total_jobs."""
    mock_rows = [
        {"greenshift_carbon_kg": 1.0, "energy_kwh": 2.0, "sla_met": True, "sla_miss": False, "status": "COMPLETED", "cost_difference_usd": 0.5, "baseline_carbon_kg": 2.0, "carbon_avoided_kg": 1.0, "carbon_intensity_gco2_kwh": 400.0, "greenshift_cost_usd": 0.2, "baseline_cost_usd": 0.3},
        {"greenshift_carbon_kg": 1.5, "energy_kwh": 4.0, "sla_met": True, "sla_miss": False, "status": "COMPLETED", "cost_difference_usd": 0.8, "baseline_carbon_kg": 3.0, "carbon_avoided_kg": 1.5, "carbon_intensity_gco2_kwh": 400.0, "greenshift_cost_usd": 0.4, "baseline_cost_usd": 0.6},
    ]
    summary = _aggregate(mock_rows)
    assert summary["energy_intensity_kwh_per_job"] == round(6.0 / 2, 4)


def test_aggregate_includes_ghg_intensity(db):
    """ghg_intensity_kg_per_kwh is calculated correctly as total_gs_carbon / total_energy_kwh."""
    mock_rows = [
        {"greenshift_carbon_kg": 2.5, "energy_kwh": 5.0, "sla_met": True, "sla_miss": False, "status": "COMPLETED", "cost_difference_usd": 0.5, "baseline_carbon_kg": 3.0, "carbon_avoided_kg": 0.5, "carbon_intensity_gco2_kwh": 400.0, "greenshift_cost_usd": 0.2, "baseline_cost_usd": 0.3},
    ]
    summary = _aggregate(mock_rows)
    assert summary["ghg_intensity_kg_per_kwh"] == round(2.5 / 5.0, 6)


def test_aggregate_includes_native_currency_costs(db):
    """Native-currency cost saved is present alongside USD, currency-separated
    (Currency Consistency Hardening — replaces the old always-INR-labeled
    fields, which silently mislabeled every non-INR job's native cost)."""
    mock_rows = [
        {
            "greenshift_carbon_kg": 1.0,
            "energy_kwh": 2.0,
            "sla_met": True,
            "sla_miss": False,
            "status": "COMPLETED",
            "cost_difference_usd": 0.1,
            "baseline_carbon_kg": 2.0,
            "carbon_avoided_kg": 1.0,
            "carbon_intensity_gco2_kwh": 400.0,
            "greenshift_cost_usd": 0.2,
            "baseline_cost_usd": 0.3,
            "greenshift_cost_native": 16.5,
            "baseline_cost_native": 24.8,
            "currency": "INR",
        },
    ]
    summary = _aggregate(mock_rows)
    assert "cost_saved_by_currency" in summary
    assert summary["cost_saved_by_currency"] == {"INR": round(24.8 - 16.5, 4)}


def test_aggregate_never_combines_different_currencies(db):
    """A report spanning an INR job and a USD job must report two separate
    currency entries, never a single summed figure."""
    mock_rows = [
        {
            "greenshift_carbon_kg": 1.0, "energy_kwh": 2.0, "sla_met": True, "sla_miss": False,
            "status": "COMPLETED", "cost_difference_usd": 0.1, "baseline_carbon_kg": 2.0,
            "carbon_avoided_kg": 1.0, "carbon_intensity_gco2_kwh": 400.0,
            "greenshift_cost_usd": 0.2, "baseline_cost_usd": 0.3,
            "greenshift_cost_native": 16.5, "baseline_cost_native": 24.8, "currency": "INR",
        },
        {
            "greenshift_carbon_kg": 1.0, "energy_kwh": 2.0, "sla_met": True, "sla_miss": False,
            "status": "COMPLETED", "cost_difference_usd": 0.05, "baseline_carbon_kg": 2.0,
            "carbon_avoided_kg": 1.0, "carbon_intensity_gco2_kwh": 400.0,
            "greenshift_cost_usd": 0.1, "baseline_cost_usd": 0.15,
            "greenshift_cost_native": 0.1, "baseline_cost_native": 0.15, "currency": "USD",
        },
    ]
    summary = _aggregate(mock_rows)
    assert summary["cost_saved_by_currency"] == {
        "INR": round(24.8 - 16.5, 4),
        "USD": round(0.15 - 0.1, 4),
    }


def test_methodology_in_metadata(db):
    """Metadata contains methodology and data_quality_notes disclosures."""
    report = generate_report(db)
    meta = report["metadata"]

    assert "methodology" in meta
    assert "Scope 2" in meta["methodology"] or "Scope 2" in meta["scope"]
    assert "Electricity Maps API" in meta["methodology"]
    assert "data_quality_notes" in meta
    assert "carbon_source" in meta["data_quality_notes"]
    assert "tariff_source" in meta["data_quality_notes"]
    assert "limitations" in meta["data_quality_notes"]


def test_report_says_aligned_not_compliant(db):
    """Verify 'Aligned' in report_type and framework, not 'Compliant'."""
    report = generate_report(db)
    meta = report["metadata"]

    assert "Aligned" in meta["report_type"]
    assert "Compliant" not in meta["report_type"]
    assert "Aligned" in meta["framework"]
    assert "Compliant" not in meta["framework"]


def test_markdown_includes_methodology_section(db):
    """Markdown report includes Methodology & Data Quality section and regional table."""
    md = generate_markdown_summary(db)

    assert "## Methodology & Data Quality" in md
    assert "Scope 2 — Purchased Electricity" in md
    assert "Electricity Maps API" in md
    assert "Limitations" in md
    assert "## Regional Breakdown" in md
    assert "BRSR-Aligned" in md


# ─────────────────────────────────────────────────────────────────────────────
# Tenant scoping for the actual HTTP endpoints (GET /report/summary, /report/csv)
#
# Everything above this line calls generate_report(db)/_aggregate(...) directly
# with no tenant_id, so it never exercises app/api/routers/report.py's own
# 403-on-tenant-mismatch and team_id-clamping logic — only manual code reading
# guaranteed that behavior was correct. These tests close that gap.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def report_client(db):
    def _get_test_db():
        yield db

    app.dependency_overrides[get_db] = _get_test_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _report_user(db, username, email, role, tenant_id=None, team_id=None):
    u = UserORM(
        username=username,
        email=email,
        hashed_password=hash_password("Pass123!"),
        role=role,
        tenant_id=tenant_id,
        team_id=team_id,
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


def _report_job(db, job_id, tenant_id, team_id):
    now = datetime.now(timezone.utc)
    db.add(JobORM(
        job_id=job_id,
        team_id=team_id,
        tenant_id=tenant_id,
        company_name="ReportScope Corp",
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
def report_scoped_setup(db):
    db.add_all([
        TenantORM(id="tenant-report-a", name="Report Corp A", is_active=True),
        TenantORM(id="tenant-report-b", name="Report Corp B", is_active=True),
    ])
    db.commit()

    admin_a = _report_user(db, "rpt_admin_a", "admin_a@report.io", UserRole.COMPANY_ADMIN,
                            tenant_id="tenant-report-a", team_id="team-red")
    user_a_red = _report_user(db, "rpt_user_a_red", "red_a@report.io", UserRole.COMPANY_USER,
                               tenant_id="tenant-report-a", team_id="team-red")
    user_a_blue = _report_user(db, "rpt_user_a_blue", "blue_a@report.io", UserRole.COMPANY_USER,
                                tenant_id="tenant-report-a", team_id="team-blue")
    platform_admin = _report_user(db, "rpt_platform_admin", "pa@report.io", UserRole.PLATFORM_ADMIN,
                                   tenant_id=None, team_id=None)

    _report_job(db, "rpt-job-a-red", "tenant-report-a", "team-red")
    _report_job(db, "rpt-job-a-blue", "tenant-report-a", "team-blue")
    _report_job(db, "rpt-job-b", "tenant-report-b", "team-only")

    return {
        "admin_a": admin_a,
        "user_a_red": user_a_red,
        "user_a_blue": user_a_blue,
        "platform_admin": platform_admin,
    }


class TestReportSummaryTenantScoping:
    def test_company_admin_cannot_request_another_tenants_report(self, report_client, report_scoped_setup):
        resp = report_client.get(
            "/report/summary?tenant_id=tenant-report-b",
            headers=report_scoped_setup["admin_a"],
        )
        assert resp.status_code == 403

    def test_company_admin_sees_only_own_tenants_jobs(self, report_client, report_scoped_setup):
        resp = report_client.get("/report/summary", headers=report_scoped_setup["admin_a"])
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()["jobs"]}
        assert "rpt-job-a-red" in job_ids
        assert "rpt-job-a-blue" in job_ids
        assert "rpt-job-b" not in job_ids

    def test_company_user_forged_tenant_id_is_ignored(self, report_client, report_scoped_setup):
        """A Company User's own tenant_id always matches, so the request
        isn't rejected — but the forged tenant_id must have no effect on
        which tenant's data is actually returned."""
        resp = report_client.get(
            "/report/summary?tenant_id=tenant-report-b",
            headers=report_scoped_setup["user_a_red"],
        )
        assert resp.status_code == 403

    def test_company_user_team_id_is_clamped_to_own_team(self, report_client, report_scoped_setup):
        """A Company User in team-red requesting team_id=team-blue must still
        only see their own team's jobs — team_id is never client-controlled
        for a non-Company-Admin, same fix as /impact/fleet."""
        resp = report_client.get(
            "/report/summary?team_id=team-blue",
            headers=report_scoped_setup["user_a_red"],
        )
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()["jobs"]}
        assert "rpt-job-a-red" in job_ids
        assert "rpt-job-a-blue" not in job_ids

    def test_platform_admin_can_filter_by_any_tenant(self, report_client, report_scoped_setup):
        resp = report_client.get(
            "/report/summary?tenant_id=tenant-report-b",
            headers=report_scoped_setup["platform_admin"],
        )
        assert resp.status_code == 200
        job_ids = {j["job_id"] for j in resp.json()["jobs"]}
        assert job_ids == {"rpt-job-b"}


class TestReportCsvTenantScoping:
    def test_company_admin_cannot_request_another_tenants_csv(self, report_client, report_scoped_setup):
        resp = report_client.get(
            "/report/csv?tenant_id=tenant-report-b",
            headers=report_scoped_setup["admin_a"],
        )
        assert resp.status_code == 403

    def test_company_user_team_id_is_clamped_in_csv(self, report_client, report_scoped_setup):
        resp = report_client.get(
            "/report/csv?team_id=team-blue",
            headers=report_scoped_setup["user_a_red"],
        )
        assert resp.status_code == 200
        assert "rpt-job-a-red" in resp.text
        assert "rpt-job-a-blue" not in resp.text

    def test_csv_never_leaks_another_tenants_job_ids(self, report_client, report_scoped_setup):
        resp = report_client.get("/report/csv", headers=report_scoped_setup["admin_a"])
        assert resp.status_code == 200
        assert "rpt-job-b" not in resp.text
