"""
Tests for Fleet Impact Analytics & Actual Execution Variance Tracker.
Covers compute_fleet_impact, compute_actual_impact, REST API endpoints,
percentile calculations, and edge cases.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.analytics.actual_impact import (
    ActualImpactResult,
    compute_actual_impact,
    compute_fleet_actual_impact,
)
from app.analytics.fleet_impact import (
    FleetImpactReport,
    compute_fleet_impact,
)
from app.api.main import app
from app.shared.auth import create_access_token, hash_password
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import (
    JobORM,
    JobStatus,
    KubernetesExecutionORM,
    ScheduleDecisionORM,
    TenantORM,
    UserORM,
    UserRole,
)


@pytest.fixture
def client(db):
    """TestClient that uses the test database session."""
    from app.shared.database import get_db
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


def _create_dummy_job_and_decision(
    db,
    job_id: str,
    team_id: str = "analytics",
    region: str = "IN-TG",
    job_type: str = "DATA_PROCESSING",
    energy_kwh: float = 10.0,
    base_carbon: float = 5.0,
    gs_carbon: float = 3.5,
    base_cost: float = 1.0,
    gs_cost: float = 0.7,
    sla_met: bool = True,
    delay_hours: float = 2.0,
    base_hour: int = 10,
    gs_hour: int = 14,
    tenant_id: "str | None" = None,
    currency: str = "INR",
    fx_rate_to_usd: float = 0.012,
):
    now = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    base_start = now.replace(hour=base_hour)
    gs_start = now.replace(hour=gs_hour)

    job = JobORM(
        job_id=job_id,
        team_id=team_id,
        tenant_id=tenant_id,
        region=region,
        job_type=job_type,
        status=JobStatus.SCHEDULED,
        runtime_minutes=60,
        power_kw=10.0,
        energy_kwh=energy_kwh,
        deadline=now + timedelta(hours=24),
        submitted_at=now,
        earliest_start_time=now,
        container_image="greenshift/sample-workload:latest",
    )
    db.add(job)
    db.flush()

    c_avoided = base_carbon - gs_carbon
    c_red_pct = (c_avoided / base_carbon * 100.0) if base_carbon > 0 else 0.0
    cost_diff = base_cost - gs_cost
    cost_red_pct = (cost_diff / base_cost * 100.0) if base_cost > 0 else 0.0

    sd = ScheduleDecisionORM(
        job_id=job_id,
        selected_start=gs_start,
        selected_end=gs_start + timedelta(hours=1),
        carbon_intensity=350.0,
        electricity_cost=gs_cost,
        carbon_emission=gs_carbon,
        baseline_start=base_start,
        baseline_end=base_start + timedelta(hours=1),
        baseline_carbon_emission=base_carbon,
        baseline_cost=base_cost,
        carbon_avoided=c_avoided,
        cost_difference=cost_diff,
        carbon_reduction_pct=c_red_pct,
        cost_reduction_pct=cost_red_pct,
        scheduling_delay_hours=delay_hours,
        sla_met=sla_met,
        region_id=region,
        tariff_plan="HT-I(A)",
        reason="Carbon optimal slot",
        currency=currency,
        native_cost=gs_cost / fx_rate_to_usd,
        baseline_native_cost=base_cost / fx_rate_to_usd,
    )
    db.add(sd)
    db.commit()
    return job, sd


def test_fleet_impact_with_no_decisions(db):
    """Empty DB returns zeroes and empty distributions without crashing."""
    report = compute_fleet_impact(db)
    assert report.total_jobs_analyzed == 0
    assert report.total_jobs_with_decisions == 0
    assert report.total_carbon_avoided_kg == 0.0
    assert report.avg_carbon_reduction_pct == 0.0
    assert report.sla_compliance_pct == 0.0
    assert report.by_region == {}
    assert report.carbon_reduction_distribution == []


def test_fleet_impact_with_single_job(db):
    """Verify all summary metrics populated correctly for a single job."""
    _create_dummy_job_and_decision(
        db,
        job_id="JOB-SINGLE-1",
        base_carbon=10.0,
        gs_carbon=7.0,
        base_cost=2.0,
        gs_cost=1.5,
    )
    report = compute_fleet_impact(db)
    assert report.total_jobs_with_decisions == 1
    assert report.total_baseline_carbon_kg == 10.0
    assert report.total_greenshift_carbon_kg == 7.0
    assert report.total_carbon_avoided_kg == 3.0
    assert report.avg_carbon_reduction_pct == 30.0
    assert report.median_carbon_reduction_pct == 30.0
    assert report.total_cost_saved_usd == 0.5
    assert report.jobs_with_positive_carbon_savings == 1
    assert report.jobs_with_negative_carbon_savings == 0
    assert report.jobs_with_zero_impact == 0
    assert report.sla_compliance_pct == 100.0


def test_fleet_impact_regional_breakdown(db):
    """4 jobs across 4 regions appear in by_region."""
    regions = ["IN-TG", "IN-GJ", "IN-HP", "IN-WB"]
    for i, reg in enumerate(regions):
        _create_dummy_job_and_decision(
            db,
            job_id=f"JOB-REG-{i}",
            region=reg,
            base_carbon=5.0,
            gs_carbon=3.0,
        )
    report = compute_fleet_impact(db)
    assert report.total_jobs_with_decisions == 4
    for reg in regions:
        assert reg in report.by_region
        assert report.by_region[reg].job_count == 1
        assert report.by_region[reg].total_carbon_avoided_kg == 2.0


def test_fleet_impact_multi_region_currencies_never_combined(db):
    """Currency Consistency Hardening: an India (INR), USA (USD), and
    Australia (AUD) job in the same fleet must never have their native
    costs summed into a single mislabeled figure — the fleet-level
    breakdown must be currency-separated, and each region's own bucket
    must report its own real currency."""
    _create_dummy_job_and_decision(
        db, job_id="JOB-CUR-IN", region="IN-TG", currency="INR", fx_rate_to_usd=0.012,
        base_cost=100.0, gs_cost=80.0,
    )
    _create_dummy_job_and_decision(
        db, job_id="JOB-CUR-US", region="US-CA", currency="USD", fx_rate_to_usd=1.0,
        base_cost=10.0, gs_cost=8.0,
    )
    _create_dummy_job_and_decision(
        db, job_id="JOB-CUR-AU", region="AU-SA-Small", currency="AUD", fx_rate_to_usd=0.65,
        base_cost=5.0, gs_cost=4.0,
    )

    report = compute_fleet_impact(db)
    assert report.total_jobs_with_decisions == 3

    # Per-region buckets: each reports its OWN real currency and native total.
    assert report.by_region["IN-TG"].currency == "INR"
    assert report.by_region["IN-TG"].total_cost_saved_native == pytest.approx((100.0 - 80.0) / 0.012, abs=0.01)
    assert report.by_region["US-CA"].currency == "USD"
    assert report.by_region["US-CA"].total_cost_saved_native == pytest.approx((10.0 - 8.0) / 1.0, abs=0.01)
    assert report.by_region["AU-SA-Small"].currency == "AUD"
    assert report.by_region["AU-SA-Small"].total_cost_saved_native == pytest.approx((5.0 - 4.0) / 0.65, abs=0.01)

    # Fleet level: currency-separated dict, one entry per real currency —
    # never a single number combining INR + USD + AUD.
    by_currency = report.cost_saved_by_currency
    assert set(by_currency.keys()) == {"INR", "USD", "AUD"}
    assert by_currency["INR"] == pytest.approx((100.0 - 80.0) / 0.012, abs=0.01)
    assert by_currency["USD"] == pytest.approx((10.0 - 8.0) / 1.0, abs=0.01)
    assert by_currency["AUD"] == pytest.approx((5.0 - 4.0) / 0.65, abs=0.01)

    # total_cost_saved_usd remains the one legitimate cross-region metric —
    # unaffected by this fix, still a genuine USD sum via the real FX path.
    assert report.total_cost_saved_usd == pytest.approx(20.0 + 2.0 + 1.0, rel=1e-6)


def test_fleet_impact_distribution_stats(db):
    """Verify median and P90 percentile calculations."""
    reductions = [10.0, 20.0, 30.0, 40.0, 50.0]
    for i, red in enumerate(reductions):
        base_c = 100.0
        gs_c = base_c * (1.0 - red / 100.0)
        _create_dummy_job_and_decision(
            db,
            job_id=f"JOB-DIST-{i}",
            base_carbon=base_c,
            gs_carbon=gs_c,
        )
    report = compute_fleet_impact(db)
    assert report.median_carbon_reduction_pct == 30.0
    assert report.p90_carbon_reduction_pct >= 40.0
    assert len(report.carbon_reduction_distribution) == 5


def test_positive_negative_savings_counting(db):
    """Jobs where GreenShift carbon > baseline are counted as negative."""
    # Positive job
    _create_dummy_job_and_decision(db, "JOB-POS", base_carbon=10.0, gs_carbon=8.0)
    # Negative job (carbon increased)
    _create_dummy_job_and_decision(db, "JOB-NEG", base_carbon=10.0, gs_carbon=12.0)
    # Zero job
    _create_dummy_job_and_decision(db, "JOB-ZERO", base_carbon=10.0, gs_carbon=10.0)

    report = compute_fleet_impact(db)
    assert report.jobs_with_positive_carbon_savings == 1
    assert report.jobs_with_negative_carbon_savings == 1
    assert report.jobs_with_zero_impact == 1


def test_actual_impact_computation(db):
    """Verify compute_actual_impact with simulated execution window."""
    job, sd = _create_dummy_job_and_decision(db, "JOB-ACTUAL-1")

    now = datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc)
    k8s_exec = KubernetesExecutionORM(
        job_id=job.job_id,
        kubernetes_job_name="gs-job-actual-1",
        kubernetes_namespace="greenshift",
        planned_start=sd.selected_start,
        planned_end=sd.selected_end,
        actual_start=now,
        actual_end=now + timedelta(minutes=60),
        gs_status=JobStatus.COMPLETED,
    )
    db.add(k8s_exec)
    db.commit()

    res = compute_actual_impact(db, job.job_id)
    assert res is not None
    assert isinstance(res, ActualImpactResult)
    assert res.job_id == job.job_id
    assert res.actual_carbon_emission_kg > 0.0
    assert res.actual_cost_usd > 0.0
    assert res.estimation_quality in ("ACCURATE", "ACCEPTABLE", "POOR")


def test_actual_impact_estimation_quality(db):
    """Verify estimation quality classification thresholds."""
    job, sd = _create_dummy_job_and_decision(db, "JOB-QUALITY-1")

    # When no execution exists, returns None
    assert compute_actual_impact(db, job.job_id) is None

    # When execution exists
    now = datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc)
    k8s_exec = KubernetesExecutionORM(
        job_id=job.job_id,
        kubernetes_job_name="gs-job-quality-1",
        kubernetes_namespace="greenshift",
        planned_start=sd.selected_start,
        actual_start=now,
        actual_end=now + timedelta(minutes=60),
        gs_status=JobStatus.COMPLETED,
    )
    db.add(k8s_exec)
    db.commit()

    res = compute_actual_impact(db, job.job_id)
    assert res is not None
    if abs(res.carbon_estimation_error_pct) < 5.0:
        assert res.estimation_quality == "ACCURATE"
    elif abs(res.carbon_estimation_error_pct) < 15.0:
        assert res.estimation_quality == "ACCEPTABLE"
    else:
        assert res.estimation_quality == "POOR"


def test_fleet_impact_api_endpoint(client, db):
    """FastAPI TestClient integration test for /api/v1/impact/fleet."""
    _create_dummy_job_and_decision(db, "JOB-API-1")
    r = client.get("/api/v1/impact/fleet")
    assert r.status_code == 200
    data = r.json()
    assert "total_carbon_avoided_kg" in data
    assert "avg_carbon_reduction_pct" in data
    assert "by_region" in data
    assert data["total_jobs_with_decisions"] >= 1


def test_headline_api_endpoint(client, db):
    """Verify /api/v1/impact/fleet/headline returns minimal presentation shape."""
    _create_dummy_job_and_decision(db, "JOB-API-2")
    r = client.get("/api/v1/impact/fleet/headline")
    assert r.status_code == 200
    data = r.json()
    expected_keys = {
        "total_carbon_avoided_kg",
        "avg_carbon_reduction_pct",
        "total_cost_saved_usd",
        "cost_saved_by_currency",
        "sla_compliance_pct",
        "total_jobs",
        "jobs_with_positive_savings",
    }
    assert set(data.keys()) == expected_keys


def test_actual_impact_endpoints(client, db):
    """Verify /api/v1/impact/job/{id}/actual and /api/v1/impact/fleet/actual."""
    job, sd = _create_dummy_job_and_decision(db, "JOB-API-ACTUAL")

    # 404 when no execution
    r404 = client.get(f"/api/v1/impact/job/{job.job_id}/actual")
    assert r404.status_code == 404

    now = datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc)
    k8s_exec = KubernetesExecutionORM(
        job_id=job.job_id,
        kubernetes_job_name="gs-job-api-act",
        kubernetes_namespace="greenshift",
        planned_start=sd.selected_start,
        actual_start=now,
        actual_end=now + timedelta(minutes=60),
        gs_status=JobStatus.COMPLETED,
    )
    db.add(k8s_exec)
    db.commit()

    # 200 when execution exists
    r200 = client.get(f"/api/v1/impact/job/{job.job_id}/actual")
    assert r200.status_code == 200
    act_data = r200.json()
    assert act_data["job_id"] == job.job_id
    assert "actual_carbon_emission_kg" in act_data
    assert "carbon_estimation_error_pct" in act_data

    # Fleet actual impact
    rfleet = client.get("/api/v1/impact/fleet/actual")
    assert rfleet.status_code == 200
    fleet_act = rfleet.json()
    assert fleet_act["total_completed_jobs_analyzed"] >= 1
    assert "estimation_quality_distribution" in fleet_act


# ─────────────────────────────────────────────────────────────────────────────
# Consistency audit: /impact/fleet/actual previously had NO identity
# dependency at all (unlike its siblings /impact/fleet and
# /impact/fleet/headline) and returned unscoped, cross-tenant data to any
# caller regardless of authentication. Also: a plain Company User's
# `team_id` query param on /impact/fleet was never validated against their
# own identity, letting them view another team's numbers within their own
# tenant. Both fixed in app/api/routers/impact.py + app/shared/auth.py
# (AuthenticatedIdentity gained a real team_id field).
# ─────────────────────────────────────────────────────────────────────────────

def _make_user(db, username, email, role, tenant_id=None, team_id=None):
    u = UserORM(
        username=username, email=email, hashed_password=hash_password("Pass123!"),
        role=role, tenant_id=tenant_id, team_id=team_id, is_active=True, approval_status="APPROVED",
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


def test_fleet_actual_impact_requires_authentication_when_auth_enabled(client, db, monkeypatch):
    """Consistency fix: previously this endpoint had no identity dependency
    at all and was reachable with zero credentials even when AUTH_ENABLED=true."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    r = client.get("/api/v1/impact/fleet/actual")
    assert r.status_code == 401


def test_fleet_actual_impact_scoped_to_callers_own_tenant(client, db, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    db.add(TenantORM(id="tenant-fleet-actual-a", name="Fleet Actual Co A", is_active=True))
    db.add(TenantORM(id="tenant-fleet-actual-b", name="Fleet Actual Co B", is_active=True))
    db.commit()

    job_a, sd_a = _create_dummy_job_and_decision(db, "JOB-FLEET-ACT-A", tenant_id="tenant-fleet-actual-a")
    job_b, sd_b = _create_dummy_job_and_decision(db, "JOB-FLEET-ACT-B", tenant_id="tenant-fleet-actual-b")
    now = datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc)
    for job, sd in ((job_a, sd_a), (job_b, sd_b)):
        db.add(KubernetesExecutionORM(
            job_id=job.job_id, kubernetes_job_name=f"gs-{job.job_id.lower()}",
            kubernetes_namespace="greenshift", planned_start=sd.selected_start,
            actual_start=now, actual_end=now + timedelta(minutes=60), gs_status=JobStatus.COMPLETED,
        ))
    db.commit()

    headers_a = _make_user(db, "fleet_act_admin_a", "a@fleetactual.example.com", UserRole.COMPANY_ADMIN, "tenant-fleet-actual-a")
    r = client.get("/api/v1/impact/fleet/actual", headers=headers_a)
    assert r.status_code == 200
    # Scoped to tenant A only: exactly the 1 job we created for tenant A.
    assert r.json()["total_completed_jobs_analyzed"] == 1


def test_company_user_cannot_override_team_id_on_fleet_impact(client, db, monkeypatch):
    """A plain Company User's team_id is always their own — a query param
    requesting a different team must not widen their visibility."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    db.add(TenantORM(id="tenant-fleet-team-scope", name="Fleet Team Scope Co", is_active=True))
    db.commit()

    _create_dummy_job_and_decision(db, "JOB-FLEET-TEAM-OWN", team_id="team-own", tenant_id="tenant-fleet-team-scope")
    _create_dummy_job_and_decision(db, "JOB-FLEET-TEAM-OTHER", team_id="team-other", tenant_id="tenant-fleet-team-scope")

    headers = _make_user(
        db, "fleet_team_user", "user@fleetteamscope.example.com", UserRole.COMPANY_USER,
        "tenant-fleet-team-scope", "team-own",
    )

    # Requesting their own team: sees their own job.
    r_own = client.get("/api/v1/impact/fleet?team_id=team-own", headers=headers)
    assert r_own.status_code == 200
    assert r_own.json()["total_jobs_with_decisions"] == 1

    # Attempting to view another team within the SAME tenant: clamped back
    # to their own team, never the requested one.
    r_spoofed = client.get("/api/v1/impact/fleet?team_id=team-other", headers=headers)
    assert r_spoofed.status_code == 200
    assert r_spoofed.json()["total_jobs_with_decisions"] == 1  # still only their own job, not team-other's


def test_company_admin_may_still_filter_fleet_impact_by_any_team(client, db, monkeypatch):
    """Company Admin/Platform Admin retain the pre-existing ability to filter
    by any team_id — only a plain Company User is clamped."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    db.add(TenantORM(id="tenant-fleet-admin-scope", name="Fleet Admin Scope Co", is_active=True))
    db.commit()
    _create_dummy_job_and_decision(db, "JOB-FLEET-ADMIN-OTHER", team_id="team-other-2", tenant_id="tenant-fleet-admin-scope")

    headers = _make_user(
        db, "fleet_team_admin", "admin@fleetadminscope.example.com", UserRole.COMPANY_ADMIN,
        "tenant-fleet-admin-scope", "team-own-2",
    )
    r = client.get("/api/v1/impact/fleet?team_id=team-other-2", headers=headers)
    assert r.status_code == 200
    assert r.json()["total_jobs_with_decisions"] == 1

