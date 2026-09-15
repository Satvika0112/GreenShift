"""
Tests for GreenShift Policy-Aware Optimization.

Covers:
1. app.decide.optimization_policy — pure ranking/validation unit tests
2. Scheduler integration — CARBON_FIRST / COST_FIRST / CARBON_CONSTRAINED
   applied via schedule_job(), with common hard constraints still enforced
3. Regression — introducing the policy layer does not change existing
   CARBON_FIRST (default) scheduling decisions
4. API — GET/PUT /api/v1/settings/optimization-policy: RBAC, tenant
   isolation, validation, audit
5. Integration — Company Admin changes policy via the API -> DECIDE
   resolves and applies it -> ScheduleDecision stores it
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import app
from app.decide.optimization_policy import (
    InvalidOptimizationPolicyError,
    OptimizationPolicy,
    build_policy_reason,
    min_carbon_kg,
    rank_feasible_candidates,
    validate_carbon_tolerance_pct,
    validate_policy,
)
from app.decide.scheduler import schedule_job
from app.decide.service import schedule_and_store
from app.ingest.jobs import submit_job
from app.settings.optimization_policy_service import resolve_effective_policy
from app.shared.auth import hash_password
from app.shared.database import SessionLocal
from app.shared.models import (
    AuditEventORM,
    CarbonDataPoint,
    EventType,
    JobORM,
    JobSubmitRequest,
    OptimizationPolicyORM,
    TariffDataPoint,
    TeamORM,
    TenantORM,
    UserApprovalStatus,
    UserORM,
    UserRole,
)

TENANT_A = "tenant-optpolicy-test-alpha-inc"
TENANT_B = "tenant-optpolicy-test-beta-inc"
COMPANY_A_NAME = "OptPolicy Test Alpha Inc"
COMPANY_B_NAME = "OptPolicy Test Beta Inc"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def now():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


class _Cand:
    """Minimal candidate stand-in matching the (carbon_emission_kg,
    electricity_cost, start_time) attribute contract rank_feasible_candidates
    expects by default."""
    def __init__(self, carbon, cost, start):
        self.carbon_emission_kg = carbon
        self.electricity_cost = cost
        self.start_time = start


@pytest.fixture()
def client():
    return TestClient(app)


def _login(client, username, password):
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture(autouse=True)
def clean_db():
    with SessionLocal() as db:
        db.query(OptimizationPolicyORM).filter(OptimizationPolicyORM.tenant_id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(JobORM).filter(JobORM.tenant_id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(TeamORM).filter(TeamORM.tenant_id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(UserORM).filter(UserORM.tenant_id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(TenantORM).filter(TenantORM.id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(TenantORM).filter(TenantORM.name.in_([COMPANY_A_NAME, COMPANY_B_NAME])).delete(synchronize_session=False)
        db.query(UserORM).filter(UserORM.username == "optpolicy_platadm").delete(synchronize_session=False)
        db.commit()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _register_company(client, name, tenant_id, admin_email) -> dict:
    body = {
        "company_name": name,
        "legal_name": f"{name} Pvt Ltd",
        "company_email": admin_email.replace("admin", "hq"),
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
    resp = client.post("/api/v1/companies/register", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_company_user(client, admin_token, email) -> None:
    resp = client.post(
        "/api/v1/companies/me/users",
        json={"email": email, "password": "StrongPass1", "role": "COMPANY_USER"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text


def _make_platform_admin(db) -> UserORM:
    u = UserORM(
        username="optpolicy_platadm", email="platadm@optpolicytest.io",
        hashed_password=hash_password("PlatPass1!"), role=UserRole.PLATFORM_ADMIN,
        approval_status=UserApprovalStatus.APPROVED.value, is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ─────────────────────────────────────────────────────────────────────────────
# 1. Canonical policy model — validation
# ─────────────────────────────────────────────────────────────────────────────

class TestPolicyValidation:
    def test_validate_policy_accepts_exact_values(self):
        assert validate_policy("CARBON_FIRST") == OptimizationPolicy.CARBON_FIRST
        assert validate_policy("cost_first") == OptimizationPolicy.COST_FIRST
        assert validate_policy(OptimizationPolicy.CARBON_CONSTRAINED) == OptimizationPolicy.CARBON_CONSTRAINED

    def test_validate_policy_rejects_invalid_value_no_silent_substitution(self):
        with pytest.raises(InvalidOptimizationPolicyError):
            validate_policy("BALANCED")
        with pytest.raises(InvalidOptimizationPolicyError):
            validate_policy("")
        with pytest.raises(InvalidOptimizationPolicyError):
            validate_policy(None)

    def test_validate_carbon_tolerance_pct_accepts_range(self):
        assert validate_carbon_tolerance_pct(0) == 0.0
        assert validate_carbon_tolerance_pct(5) == 5.0
        assert validate_carbon_tolerance_pct(100) == 100.0
        assert validate_carbon_tolerance_pct("7.5") == 7.5

    def test_validate_carbon_tolerance_pct_rejects_out_of_range(self):
        with pytest.raises(InvalidOptimizationPolicyError):
            validate_carbon_tolerance_pct(-0.01)
        with pytest.raises(InvalidOptimizationPolicyError):
            validate_carbon_tolerance_pct(100.01)

    def test_validate_carbon_tolerance_pct_rejects_non_numeric_and_nan_inf(self):
        with pytest.raises(InvalidOptimizationPolicyError):
            validate_carbon_tolerance_pct("not-a-number")
        with pytest.raises(InvalidOptimizationPolicyError):
            validate_carbon_tolerance_pct(float("nan"))
        with pytest.raises(InvalidOptimizationPolicyError):
            validate_carbon_tolerance_pct(float("inf"))


# ─────────────────────────────────────────────────────────────────────────────
# 2. rank_feasible_candidates — pure ranking unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestRankCarbonFirst:
    def test_lowest_carbon_selected(self, now):
        cands = [_Cand(2.0, 0.05, now), _Cand(1.0, 0.15, now + timedelta(hours=1))]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.CARBON_FIRST)
        assert ranked[0].carbon_emission_kg == 1.0

    def test_cost_breaks_carbon_tie(self, now):
        cands = [
            _Cand(1.0, 0.10, now),
            _Cand(1.0, 0.05, now + timedelta(hours=1)),
        ]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.CARBON_FIRST)
        assert ranked[0].electricity_cost == 0.05

    def test_earliest_start_breaks_final_tie(self, now):
        cands = [
            _Cand(1.0, 0.10, now + timedelta(hours=2)),
            _Cand(1.0, 0.10, now),
        ]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.CARBON_FIRST)
        assert ranked[0].start_time == now


class TestRankCostFirst:
    def test_lowest_cost_selected(self, now):
        cands = [_Cand(1.0, 0.20, now), _Cand(3.0, 0.05, now + timedelta(hours=1))]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.COST_FIRST)
        assert ranked[0].electricity_cost == 0.05

    def test_carbon_breaks_cost_tie(self, now):
        cands = [
            _Cand(2.0, 0.05, now),
            _Cand(1.0, 0.05, now + timedelta(hours=1)),
        ]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.COST_FIRST)
        assert ranked[0].carbon_emission_kg == 1.0

    def test_earliest_start_breaks_final_tie(self, now):
        cands = [
            _Cand(1.0, 0.10, now + timedelta(hours=2)),
            _Cand(1.0, 0.10, now),
        ]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.COST_FIRST)
        assert ranked[0].start_time == now


class TestRankCarbonConstrained:
    def test_minimum_carbon_and_tolerance_calculated_correctly(self, now):
        # min carbon = 1.0; 20% tolerance -> limit = 1.2
        cands = [
            _Cand(1.0, 0.30, now),
            _Cand(1.2, 0.10, now + timedelta(hours=1)),   # exactly at the limit -> included
            _Cand(1.20001, 0.01, now + timedelta(hours=2)),  # just outside -> excluded (within float epsilon of the limit itself is fine; this is well beyond it)
        ]
        assert min_carbon_kg(cands) == pytest.approx(1.0)
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.CARBON_CONSTRAINED, 20.0)
        # Cheapest among {1.0, 1.2} is 1.2 @ $0.10
        assert ranked[0].carbon_emission_kg == pytest.approx(1.2)
        assert ranked[0].electricity_cost == pytest.approx(0.10)

    def test_candidates_outside_tolerance_rejected(self, now):
        cands = [
            _Cand(1.0, 0.50, now),
            _Cand(5.0, 0.01, now + timedelta(hours=1)),  # far outside a 5% tolerance
        ]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.CARBON_CONSTRAINED, 5.0)
        # The only in-tolerance candidate (1.0) must win despite being far more expensive.
        assert ranked[0].carbon_emission_kg == pytest.approx(1.0)

    def test_cheapest_candidate_inside_tolerance_selected(self, now):
        cands = [
            _Cand(1.0, 0.20, now),
            _Cand(1.05, 0.05, now + timedelta(hours=1)),  # within 10%, cheaper
            _Cand(1.5, 0.01, now + timedelta(hours=2)),   # outside 10%, cheapest overall but excluded
        ]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.CARBON_CONSTRAINED, 10.0)
        assert ranked[0].electricity_cost == pytest.approx(0.05)

    def test_earliest_start_breaks_final_tie(self, now):
        cands = [
            _Cand(1.0, 0.10, now + timedelta(hours=2)),
            _Cand(1.0, 0.10, now),
        ]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.CARBON_CONSTRAINED, 5.0)
        assert ranked[0].start_time == now

    def test_zero_tolerance_only_admits_minimum_carbon_candidates(self, now):
        cands = [
            _Cand(1.0, 0.20, now),
            _Cand(1.0, 0.05, now + timedelta(hours=1)),
            _Cand(1.01, 0.01, now + timedelta(hours=2)),
        ]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.CARBON_CONSTRAINED, 0.0)
        assert ranked[0].carbon_emission_kg == pytest.approx(1.0)
        assert ranked[0].electricity_cost == pytest.approx(0.05)

    def test_no_silent_tolerance_relaxation_missing_tolerance_uses_documented_default_not_infinite(self, now):
        """Omitting carbon_tolerance_pct must fall back to the documented
        DEFAULT_CARBON_TOLERANCE_PCT, never to "no limit" (which would be
        indistinguishable from COST_FIRST and defeat the policy's purpose)."""
        cands = [
            _Cand(1.0, 0.50, now),
            _Cand(100.0, 0.01, now + timedelta(hours=1)),  # wildly over any sane default tolerance
        ]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.CARBON_CONSTRAINED, None)
        assert ranked[0].carbon_emission_kg == pytest.approx(1.0)

    def test_invalid_tolerance_raises_rather_than_clamping(self, now):
        cands = [_Cand(1.0, 0.1, now)]
        with pytest.raises(InvalidOptimizationPolicyError):
            rank_feasible_candidates(cands, OptimizationPolicy.CARBON_CONSTRAINED, 200.0)
        with pytest.raises(InvalidOptimizationPolicyError):
            rank_feasible_candidates(cands, OptimizationPolicy.CARBON_CONSTRAINED, -5.0)

    def test_ranking_is_total_never_drops_a_candidate(self, now):
        cands = [_Cand(1.0, 0.5, now), _Cand(50.0, 0.01, now + timedelta(hours=1))]
        ranked = rank_feasible_candidates(cands, OptimizationPolicy.CARBON_CONSTRAINED, 1.0)
        assert len(ranked) == len(cands)
        assert set(id(c) for c in ranked) == set(id(c) for c in cands)


class TestRankEdgeCases:
    def test_empty_candidates_returns_empty(self):
        assert rank_feasible_candidates([], OptimizationPolicy.CARBON_FIRST) == []

    def test_unsupported_policy_raises(self, now):
        with pytest.raises(InvalidOptimizationPolicyError):
            rank_feasible_candidates([_Cand(1.0, 0.1, now)], "NOT_A_POLICY")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Scheduler integration — schedule_job() with an explicit policy
# ─────────────────────────────────────────────────────────────────────────────

def _two_slot_curves(now):
    """Slot A (now): carbon 200 gCO2/kWh, $0.005/kWh. Slot B (+1h): carbon
    100 gCO2/kWh, $0.015/kWh. Power=10kW, runtime=60m -> energy=10kWh.
    Slot A: 2.0 kg CO2, $0.05. Slot B: 1.0 kg CO2, $0.15."""
    earliest = now + timedelta(hours=1)
    carbon_curve = [
        CarbonDataPoint(timestamp=earliest, region="IN-TG", carbon_gco2_kwh=200.0),
        CarbonDataPoint(timestamp=earliest + timedelta(hours=1), region="IN-TG", carbon_gco2_kwh=100.0),
    ]
    tariff_curve = [
        TariffDataPoint(timestamp=earliest, region="IN-TG", price_per_kwh=0.005),
        TariffDataPoint(timestamp=earliest + timedelta(hours=1), region="IN-TG", price_per_kwh=0.015),
    ]
    return earliest, carbon_curve, tariff_curve


class TestSchedulerPolicyIntegration:
    def test_carbon_first_selects_lower_carbon_higher_cost_slot(self, now):
        earliest, carbon_curve, tariff_curve = _two_slot_curves(now)
        decision = schedule_job(
            job_id="JOB-POLICY-CF", team_id="ml", deadline=earliest + timedelta(hours=3),
            runtime_minutes=60, power_kw=10.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve, earliest_start_time=earliest,
            policy=OptimizationPolicy.CARBON_FIRST,
        )
        assert decision.selected_start == earliest + timedelta(hours=1)
        assert decision.carbon_emission == pytest.approx(1.0)
        assert decision.scheduler_objective == "CARBON_FIRST"
        assert decision.carbon_tolerance_pct is None
        assert "Lowest-carbon feasible window" in decision.reason

    def test_cost_first_selects_lower_cost_higher_carbon_slot(self, now):
        earliest, carbon_curve, tariff_curve = _two_slot_curves(now)
        decision = schedule_job(
            job_id="JOB-POLICY-CO", team_id="ml", deadline=earliest + timedelta(hours=3),
            runtime_minutes=60, power_kw=10.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve, earliest_start_time=earliest,
            policy=OptimizationPolicy.COST_FIRST,
        )
        assert decision.selected_start == earliest
        assert decision.electricity_cost == pytest.approx(0.05)
        assert decision.scheduler_objective == "COST_FIRST"
        assert "minimum electricity cost" in decision.reason

    def test_carbon_constrained_selects_cheapest_within_tolerance(self, now):
        # min carbon (slot B) = 1.0kg; 100% tolerance admits both slots ->
        # cheapest of the two (slot A, $0.05) wins despite higher carbon.
        earliest, carbon_curve, tariff_curve = _two_slot_curves(now)
        decision = schedule_job(
            job_id="JOB-POLICY-CC", team_id="ml", deadline=earliest + timedelta(hours=3),
            runtime_minutes=60, power_kw=10.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve, earliest_start_time=earliest,
            policy=OptimizationPolicy.CARBON_CONSTRAINED, carbon_tolerance_pct=100.0,
        )
        assert decision.selected_start == earliest
        assert decision.electricity_cost == pytest.approx(0.05)
        assert decision.scheduler_objective == "CARBON_CONSTRAINED"
        assert decision.carbon_tolerance_pct == pytest.approx(100.0)
        assert "within 100%" in decision.reason

    def test_carbon_constrained_tight_tolerance_excludes_cheaper_high_carbon_slot(self, now):
        # 0% tolerance -> only the minimum-carbon slot (B, $0.15) is eligible.
        earliest, carbon_curve, tariff_curve = _two_slot_curves(now)
        decision = schedule_job(
            job_id="JOB-POLICY-CC-TIGHT", team_id="ml", deadline=earliest + timedelta(hours=3),
            runtime_minutes=60, power_kw=10.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve, earliest_start_time=earliest,
            policy=OptimizationPolicy.CARBON_CONSTRAINED, carbon_tolerance_pct=0.0,
        )
        assert decision.selected_start == earliest + timedelta(hours=1)
        assert decision.carbon_emission == pytest.approx(1.0)

    def test_invalid_policy_string_raises(self, now):
        earliest, carbon_curve, tariff_curve = _two_slot_curves(now)
        with pytest.raises(InvalidOptimizationPolicyError):
            schedule_job(
                job_id="JOB-POLICY-BAD", team_id="ml", deadline=earliest + timedelta(hours=3),
                runtime_minutes=60, power_kw=10.0, region="IN-TG",
                carbon_curve=carbon_curve, tariff_curve=tariff_curve, earliest_start_time=earliest,
                policy="NOT_A_REAL_POLICY",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Common hard constraints — must hold regardless of policy
# ─────────────────────────────────────────────────────────────────────────────

class TestHardConstraintsIndependentOfPolicy:
    @pytest.mark.parametrize("policy", [OptimizationPolicy.CARBON_FIRST, OptimizationPolicy.COST_FIRST, OptimizationPolicy.CARBON_CONSTRAINED])
    def test_deadline_always_respected(self, now, policy):
        earliest, carbon_curve, tariff_curve = _two_slot_curves(now)
        # Deadline only leaves room for the first slot.
        decision = schedule_job(
            job_id=f"JOB-HC-DEADLINE-{policy.value}", team_id="ml", deadline=earliest + timedelta(minutes=90),
            runtime_minutes=60, power_kw=10.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve, earliest_start_time=earliest,
            policy=policy, carbon_tolerance_pct=5.0 if policy == OptimizationPolicy.CARBON_CONSTRAINED else None,
        )
        assert decision.selected_start + timedelta(minutes=60) <= earliest + timedelta(minutes=90)

    @pytest.mark.parametrize("policy", [OptimizationPolicy.CARBON_FIRST, OptimizationPolicy.COST_FIRST, OptimizationPolicy.CARBON_CONSTRAINED])
    def test_earliest_start_always_respected(self, now, policy):
        earliest, carbon_curve, tariff_curve = _two_slot_curves(now)
        decision = schedule_job(
            job_id=f"JOB-HC-EARLIEST-{policy.value}", team_id="ml", deadline=earliest + timedelta(hours=3),
            runtime_minutes=60, power_kw=10.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve, earliest_start_time=earliest,
            policy=policy, carbon_tolerance_pct=5.0 if policy == OptimizationPolicy.CARBON_CONSTRAINED else None,
        )
        assert decision.selected_start >= earliest

    @pytest.mark.parametrize("policy", [OptimizationPolicy.CARBON_FIRST, OptimizationPolicy.COST_FIRST, OptimizationPolicy.CARBON_CONSTRAINED])
    def test_workload_carbon_budget_always_respected_no_relaxation(self, now, policy):
        earliest, carbon_curve, tariff_curve = _two_slot_curves(now)
        # Budget only the more-expensive, lower-carbon slot (1.0kg) can meet.
        decision = schedule_job(
            job_id=f"JOB-HC-BUDGET-{policy.value}", team_id="ml", deadline=earliest + timedelta(hours=3),
            runtime_minutes=60, power_kw=10.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve, earliest_start_time=earliest,
            carbon_budget_kg=1.5,
            policy=policy, carbon_tolerance_pct=100.0 if policy == OptimizationPolicy.CARBON_CONSTRAINED else None,
        )
        assert decision.carbon_emission <= 1.5
        # Regardless of policy preference, only slot B (1.0kg) satisfies the budget.
        assert decision.selected_start == earliest + timedelta(hours=1)

    @pytest.mark.parametrize("policy", [OptimizationPolicy.CARBON_FIRST, OptimizationPolicy.COST_FIRST, OptimizationPolicy.CARBON_CONSTRAINED])
    def test_impossible_carbon_budget_raises_regardless_of_policy(self, now, policy):
        earliest, carbon_curve, tariff_curve = _two_slot_curves(now)
        with pytest.raises(ValueError, match="carbon budget"):
            schedule_job(
                job_id=f"JOB-HC-IMPOSSIBLE-{policy.value}", team_id="ml", deadline=earliest + timedelta(hours=3),
                runtime_minutes=60, power_kw=10.0, region="IN-TG",
                carbon_curve=carbon_curve, tariff_curve=tariff_curve, earliest_start_time=earliest,
                carbon_budget_kg=0.000001,
                policy=policy, carbon_tolerance_pct=5.0 if policy == OptimizationPolicy.CARBON_CONSTRAINED else None,
            )

    @pytest.mark.parametrize("policy", [OptimizationPolicy.CARBON_FIRST, OptimizationPolicy.COST_FIRST, OptimizationPolicy.CARBON_CONSTRAINED])
    def test_missing_carbon_data_raises_regardless_of_policy(self, now, policy):
        with pytest.raises(ValueError, match="Carbon data is unavailable"):
            schedule_job(
                job_id=f"JOB-HC-NOCARBON-{policy.value}", team_id="ml", deadline=now + timedelta(hours=4),
                runtime_minutes=60, power_kw=5.0, region="IN-TG",
                carbon_curve=[], tariff_curve=[TariffDataPoint(timestamp=now, region="IN-TG", price_per_kwh=0.08)],
                earliest_start_time=now,
                policy=policy, carbon_tolerance_pct=5.0 if policy == OptimizationPolicy.CARBON_CONSTRAINED else None,
            )

    @pytest.mark.parametrize("policy", [OptimizationPolicy.CARBON_FIRST, OptimizationPolicy.COST_FIRST, OptimizationPolicy.CARBON_CONSTRAINED])
    def test_missing_cost_data_candidate_rejected_regardless_of_policy(self, now, policy):
        earliest, carbon_curve, _tariff_curve = _two_slot_curves(now)
        # An empty tariff_curve alone isn't enough to prove cost data is
        # unavailable — the scheduler has a real regional-template fallback
        # (app.decide.scheduler._interpolate_tariff) that can still resolve a
        # rate. Patch that resolution function itself to genuinely produce
        # "no cost data for any candidate", regardless of company policy.
        with patch("app.decide.scheduler._interpolate_tariff", return_value=None):
            with pytest.raises(ValueError):
                schedule_job(
                    job_id=f"JOB-HC-NOCOST-{policy.value}", team_id="ml", deadline=earliest + timedelta(hours=3),
                    runtime_minutes=60, power_kw=10.0, region="IN-TG",
                    carbon_curve=carbon_curve, tariff_curve=[], earliest_start_time=earliest,
                    policy=policy, carbon_tolerance_pct=5.0 if policy == OptimizationPolicy.CARBON_CONSTRAINED else None,
                )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Regression — CARBON_FIRST behavior unchanged by the policy layer
# ─────────────────────────────────────────────────────────────────────────────

class TestCarbonFirstRegression:
    """Phase 7: introducing the policy layer must not change any existing
    CARBON_FIRST scheduling decision. Compares the no-policy call path
    (policy=None, exactly how every pre-existing caller invokes schedule_job)
    against an explicit policy=CARBON_FIRST call on identical inputs."""

    @pytest.mark.parametrize("case", ["carbon_wins", "cost_tie", "start_tie", "with_budget"])
    def test_no_policy_matches_explicit_carbon_first(self, now, case):
        earliest, carbon_curve, tariff_curve = _two_slot_curves(now)
        kwargs = dict(
            team_id="ml", deadline=earliest + timedelta(hours=3),
            runtime_minutes=60, power_kw=10.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve, earliest_start_time=earliest,
        )
        if case == "cost_tie":
            carbon_curve = [
                CarbonDataPoint(timestamp=earliest, region="IN-TG", carbon_gco2_kwh=100.0),
                CarbonDataPoint(timestamp=earliest + timedelta(hours=1), region="IN-TG", carbon_gco2_kwh=100.0),
            ]
            tariff_curve = [
                TariffDataPoint(timestamp=earliest, region="IN-TG", price_per_kwh=0.005),
                TariffDataPoint(timestamp=earliest + timedelta(hours=1), region="IN-TG", price_per_kwh=0.010),
            ]
            kwargs["carbon_curve"] = carbon_curve
            kwargs["tariff_curve"] = tariff_curve
        elif case == "with_budget":
            kwargs["carbon_budget_kg"] = 1.5

        no_policy = schedule_job(job_id=f"JOB-REG-{case}-A", **kwargs)
        explicit_cf = schedule_job(job_id=f"JOB-REG-{case}-B", policy=OptimizationPolicy.CARBON_FIRST, **kwargs)

        assert no_policy.selected_start == explicit_cf.selected_start
        assert no_policy.carbon_emission == pytest.approx(explicit_cf.carbon_emission)
        assert no_policy.electricity_cost == pytest.approx(explicit_cf.electricity_cost)
        assert no_policy.scheduler_objective == explicit_cf.scheduler_objective == "CARBON_FIRST"
        assert no_policy.reason == explicit_cf.reason


# ─────────────────────────────────────────────────────────────────────────────
# 6. Policy API — RBAC, tenant isolation, validation, audit
# ─────────────────────────────────────────────────────────────────────────────

class TestOptimizationPolicyAPI:
    def test_default_policy_before_any_configuration_is_carbon_first(self, client):
        reg = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        token = _login(client, reg["admin"]["username"], "StrongPass1")
        resp = client.get("/api/v1/settings/optimization-policy", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["policy"] == "CARBON_FIRST"
        assert data["carbon_tolerance_pct"] is None
        assert data["updated_by"] is None

    def test_company_admin_can_update_policy(self, client):
        reg = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        token = _login(client, reg["admin"]["username"], "StrongPass1")
        resp = client.put(
            "/api/v1/settings/optimization-policy",
            json={"policy": "COST_FIRST"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["policy"] == "COST_FIRST"
        assert data["updated_by"] == reg["admin"]["username"]
        assert data["updated_at"] is not None

        # Persisted — a fresh GET reflects it.
        get_resp = client.get("/api/v1/settings/optimization-policy", headers={"Authorization": f"Bearer {token}"})
        assert get_resp.json()["policy"] == "COST_FIRST"

    def test_carbon_constrained_requires_tolerance(self, client):
        reg = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        token = _login(client, reg["admin"]["username"], "StrongPass1")
        resp = client.put(
            "/api/v1/settings/optimization-policy",
            json={"policy": "CARBON_CONSTRAINED"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422, resp.text

    def test_carbon_constrained_with_valid_tolerance_succeeds(self, client):
        reg = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        token = _login(client, reg["admin"]["username"], "StrongPass1")
        resp = client.put(
            "/api/v1/settings/optimization-policy",
            json={"policy": "CARBON_CONSTRAINED", "carbon_tolerance_pct": 7.5},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["carbon_tolerance_pct"] == pytest.approx(7.5)

    def test_tolerance_out_of_range_rejected(self, client):
        reg = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        token = _login(client, reg["admin"]["username"], "StrongPass1")
        resp = client.put(
            "/api/v1/settings/optimization-policy",
            json={"policy": "CARBON_CONSTRAINED", "carbon_tolerance_pct": 150},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422, resp.text

    def test_invalid_policy_value_rejected_not_substituted(self, client):
        reg = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        token = _login(client, reg["admin"]["username"], "StrongPass1")
        resp = client.put(
            "/api/v1/settings/optimization-policy",
            json={"policy": "BALANCED"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422, resp.text
        # Confirm nothing was silently written.
        get_resp = client.get("/api/v1/settings/optimization-policy", headers={"Authorization": f"Bearer {token}"})
        assert get_resp.json()["policy"] == "CARBON_FIRST"

    def test_tolerance_rejected_for_non_constrained_policy(self, client):
        reg = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        token = _login(client, reg["admin"]["username"], "StrongPass1")
        resp = client.put(
            "/api/v1/settings/optimization-policy",
            json={"policy": "CARBON_FIRST", "carbon_tolerance_pct": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422, resp.text

    def test_company_user_can_read_but_not_update(self, client):
        reg = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        admin_token = _login(client, reg["admin"]["username"], "StrongPass1")
        _make_company_user(client, admin_token, "user@optpolicy-alpha.example.com")
        user_token = _login(client, "user", "StrongPass1")

        get_resp = client.get("/api/v1/settings/optimization-policy", headers={"Authorization": f"Bearer {user_token}"})
        assert get_resp.status_code == 200, get_resp.text

        put_resp = client.put(
            "/api/v1/settings/optimization-policy",
            json={"policy": "COST_FIRST"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert put_resp.status_code == 403, put_resp.text

    def test_unauthenticated_request_rejected(self, client):
        resp = client.get("/api/v1/settings/optimization-policy")
        assert resp.status_code in (401, 403)

    def test_platform_admin_has_no_own_company_matches_existing_convention(self, client):
        """Mirrors GET/PUT /companies/me's existing behavior for Platform
        Admin (no tenant_id of their own) — this endpoint is self-service,
        not Platform Admin's cross-tenant surface."""
        with SessionLocal() as db:
            _make_platform_admin(db)
        token = _login(client, "optpolicy_platadm", "PlatPass1!")
        resp = client.get("/api/v1/settings/optimization-policy", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 400, resp.text

    def test_company_admin_cannot_affect_another_companys_policy(self, client):
        """No client-supplied tenant_id/company_id exists on this endpoint at
        all — this test confirms two independently-authenticated Company
        Admins genuinely cannot see or influence each other's policy."""
        reg_a = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        reg_b = _register_company(client, COMPANY_B_NAME, TENANT_B, "admin@optpolicy-beta.example.com")
        token_a = _login(client, reg_a["admin"]["username"], "StrongPass1")
        token_b = _login(client, reg_b["admin"]["username"], "StrongPass1")

        put_a = client.put(
            "/api/v1/settings/optimization-policy",
            json={"policy": "COST_FIRST"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert put_a.status_code == 200, put_a.text

        get_b = client.get("/api/v1/settings/optimization-policy", headers={"Authorization": f"Bearer {token_b}"})
        assert get_b.json()["policy"] == "CARBON_FIRST"  # untouched by tenant A's change

        with SessionLocal() as db:
            row_a = db.query(OptimizationPolicyORM).filter(OptimizationPolicyORM.tenant_id == TENANT_A).first()
            row_b = db.query(OptimizationPolicyORM).filter(OptimizationPolicyORM.tenant_id == TENANT_B).first()
            assert row_a is not None and row_a.policy == "COST_FIRST"
            assert row_b is None  # tenant B never wrote a row

    def test_policy_change_is_audited_with_authenticated_actor(self, client):
        reg = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        token = _login(client, reg["admin"]["username"], "StrongPass1")
        resp = client.put(
            "/api/v1/settings/optimization-policy",
            json={"policy": "CARBON_CONSTRAINED", "carbon_tolerance_pct": 15.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text

        with SessionLocal() as db:
            events = (
                db.query(AuditEventORM)
                .filter(
                    AuditEventORM.event_type == EventType.OPTIMIZATION_POLICY_CHANGED,
                    AuditEventORM.tenant_id == TENANT_A,
                )
                .order_by(AuditEventORM.sequence.desc())
                .all()
            )
            assert len(events) >= 1
            ev = events[0]
            assert ev.actor_username == reg["admin"]["username"]
            assert ev.actor_type == "USER"
            payload = ev.payload
            # No policy row existed before this call — previous_policy is
            # honestly None, never fabricated as "CARBON_FIRST".
            assert payload["previous_policy"] is None
            assert payload["new_policy"] == "CARBON_CONSTRAINED"
            assert payload["new_carbon_tolerance_pct"] == pytest.approx(15.0)


# ─────────────────────────────────────────────────────────────────────────────
# 7. End-to-end integration — policy change flows through to DECIDE
# ─────────────────────────────────────────────────────────────────────────────

class TestPolicyIntegrationEndToEnd:
    def test_company_policy_change_flows_through_to_schedule_decision(self, client, db):
        reg = _register_company(client, COMPANY_A_NAME, TENANT_A, "admin@optpolicy-alpha.example.com")
        token = _login(client, reg["admin"]["username"], "StrongPass1")

        put_resp = client.put(
            "/api/v1/settings/optimization-policy",
            json={"policy": "CARBON_CONSTRAINED", "carbon_tolerance_pct": 25.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert put_resp.status_code == 200, put_resp.text

        # resolve_effective_policy reads through the SAME real DB the API
        # just wrote to (SessionLocal-backed, not the isolated `db` fixture).
        with SessionLocal() as real_db:
            policy, tolerance = resolve_effective_policy(real_db, TENANT_A)
            assert policy == OptimizationPolicy.CARBON_CONSTRAINED
            assert tolerance == pytest.approx(25.0)

            req = JobSubmitRequest(
                team_id="ops",
                tenant_id=TENANT_A,
                deadline=datetime.now(timezone.utc) + timedelta(hours=8),
                runtime_minutes=45,
                power_kw=4.0,
                region="IN-GJ",
                container_image="greenshift/sim:v1",
            )
            job = submit_job(real_db, req)
            job.tenant_id = TENANT_A
            real_db.commit()

            decision = schedule_and_store(real_db, job, record_audit=False)

            assert decision.scheduler_objective == "CARBON_CONSTRAINED"
            assert decision.carbon_tolerance_pct == pytest.approx(25.0)
            assert "25%" in decision.reason

            real_db.refresh(job)
            sd = job.schedule_decision
            assert sd.scheduler_objective == "CARBON_CONSTRAINED"
            assert sd.carbon_tolerance_pct == pytest.approx(25.0)

    def test_tenant_with_no_configured_policy_defaults_to_carbon_first(self, db):
        req = JobSubmitRequest(
            team_id="ops",
            deadline=datetime.now(timezone.utc) + timedelta(hours=8),
            runtime_minutes=45,
            power_kw=4.0,
            region="IN-GJ",
            container_image="greenshift/sim:v1",
        )
        job = submit_job(db, req)
        decision = schedule_and_store(db, job, record_audit=False)
        assert decision.scheduler_objective == "CARBON_FIRST"
        assert decision.carbon_tolerance_pct is None
