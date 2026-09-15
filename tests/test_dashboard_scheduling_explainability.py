"""
Tests for the Dashboard Scheduling Consistency & Explainability Hardening Pass.

Covers app.dashboard.scheduling_explainability — the shared, presentation-only
module both app.dashboard.views.scheduling_engine and
app.dashboard.views.workloads now consume instead of independently
fabricating decision-factor scores and candidate slot data.

A. Decision Factors — no hardcoded 88/74/82/95; N/A for missing/zero
   baseline; different workloads produce different real values.
B. Candidate carbon — real backend values, no hour-offset formula.
C. Candidate cost — real tariff/cost data, no 10%-per-hour multiplier,
   correct (USD) currency label.
D. Feasibility/rejection — truthful, derived from real structured codes.
E. Consistency — dashboard output matches the real GET /api/v1/jobs/{id}
   response; both views consume the identical shared functions.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.dashboard.scheduling_explainability import (
    NA,
    build_candidate_rows,
    compute_decision_factors,
    format_candidate_table,
    format_scheduler_objective,
    humanize_rejection_reason,
)
from app.shared.auth import create_access_token, hash_password
from app.shared.database import get_db
from app.shared.models import JobORM, JobStatus, ScheduleDecisionORM, UserORM, UserRole
from app.shared.utils import utcnow

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def override_db(db):
    def _get_test_db():
        yield db
    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_user(db):
    u = UserORM(
        username="explain_test_admin", email="explain_admin@test.io",
        hashed_password=hash_password("Pass1234!"), role=UserRole.PLATFORM_ADMIN,
        approval_status="APPROVED", is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _token(user: UserORM) -> str:
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    return create_access_token(user_id=user.id, username=user.username, role=role_str, team_id=user.team_id, tenant_id=user.tenant_id)


def _make_job(db, job_id: str, **decision_kwargs) -> JobORM:
    now = utcnow()
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    job = JobORM(
        job_id=job_id, workload_name=f"Workload-{job_id}", job_type="Batch",
        team_id="team_explain", submitted_at=now, deadline=now + timedelta(hours=8),
        runtime_minutes=30, power_kw=2.5, region="IN-TG",
        container_image="greenshift/sim:v1", cpu_request="500m", memory_request="512Mi",
        status=JobStatus.PENDING_APPROVAL,
    )
    defaults = dict(
        job_id=job_id, selected_start=start, selected_end=start + timedelta(minutes=30),
        carbon_intensity=157.0, electricity_cost=0.0233, carbon_emission=0.0523,
        reason="Lowest-carbon feasible window (0.0523 kg CO2).",
        region_id="IN-TG",
    )
    defaults.update(decision_kwargs)
    decision = ScheduleDecisionORM(**defaults)
    job.schedule_decision = decision
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _fetch_dec(client, token, job_id) -> dict:
    resp = client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["schedule_decision"]


# ─────────────────────────────────────────────────────────────────────────────
# A. Decision Factors
# ─────────────────────────────────────────────────────────────────────────────

class TestDecisionFactorsNoHardcoding:
    def test_no_hardcoded_88_74_82_95_appear_for_real_distinct_data(self):
        dec = {
            "baseline_carbon_emission": 1.0, "carbon_reduction_pct": 47.3,
            "baseline_cost": 0.10, "cost_reduction_pct": 12.9,
            "slot_utilization_pct": 63.0, "selected_end": "2026-09-15T10:00:00+00:00",
        }
        factors = compute_decision_factors(dec, deadline_iso="2026-09-15T14:00:00+00:00")
        for forbidden in (88.0, 74.0, 82.0, 95.0):
            assert factors["carbon_abatement_pct"] != forbidden
            assert factors["cost_score_pct"] != forbidden
            assert factors["slot_headroom_pct"] != forbidden
        assert factors["carbon_abatement_pct"] == 47.3
        assert factors["cost_score_pct"] == 12.9
        assert factors["slot_headroom_pct"] == pytest.approx(37.0)

    def test_different_workloads_produce_different_values(self):
        dec_a = {"baseline_carbon_emission": 1.0, "carbon_reduction_pct": 10.0, "baseline_cost": 0.1, "cost_reduction_pct": 5.0}
        dec_b = {"baseline_carbon_emission": 1.0, "carbon_reduction_pct": 90.0, "baseline_cost": 0.1, "cost_reduction_pct": 60.0}
        fa = compute_decision_factors(dec_a, None)
        fb = compute_decision_factors(dec_b, None)
        assert fa["carbon_abatement_pct"] != fb["carbon_abatement_pct"]
        assert fa["cost_score_pct"] != fb["cost_score_pct"]

    def test_missing_baseline_carbon_is_na(self):
        dec = {"baseline_carbon_emission": None, "carbon_reduction_pct": 50.0}
        factors = compute_decision_factors(dec, None)
        assert factors["carbon_abatement_pct"] is None

    def test_zero_baseline_carbon_is_na_not_fabricated(self):
        dec = {"baseline_carbon_emission": 0.0, "carbon_reduction_pct": 0.0}
        factors = compute_decision_factors(dec, None)
        assert factors["carbon_abatement_pct"] is None

    def test_missing_baseline_cost_is_na(self):
        dec = {"baseline_cost": None, "cost_reduction_pct": 20.0}
        factors = compute_decision_factors(dec, None)
        assert factors["cost_score_pct"] is None

    def test_zero_baseline_cost_is_na(self):
        dec = {"baseline_cost": 0.0, "cost_reduction_pct": 0.0}
        factors = compute_decision_factors(dec, None)
        assert factors["cost_score_pct"] is None

    def test_negative_cost_reduction_reported_truthfully_not_hidden(self):
        """A carbon-prioritizing decision can genuinely cost more than
        baseline — that must be visible, not clamped away."""
        dec = {"baseline_cost": 0.10, "cost_reduction_pct": -18.4}
        factors = compute_decision_factors(dec, None)
        assert factors["cost_score_pct"] == -18.4

    def test_slot_headroom_na_when_slot_utilization_absent(self):
        """Single-job (non-batch) scheduling never populates
        slot_utilization_pct — must render N/A, never an invented 5.0 fallback headroom."""
        dec = {"slot_utilization_pct": None}
        factors = compute_decision_factors(dec, None)
        assert factors["slot_headroom_pct"] is None

    def test_slot_headroom_derived_from_real_utilization(self):
        dec = {"slot_utilization_pct": 22.5}
        factors = compute_decision_factors(dec, None)
        assert factors["slot_headroom_pct"] == pytest.approx(77.5)

    def test_sla_buffer_computed_from_real_timestamps(self):
        dec = {"selected_end": "2026-09-15T10:00:00+00:00"}
        factors = compute_decision_factors(dec, deadline_iso="2026-09-15T13:30:00+00:00")
        assert factors["sla_buffer_hours"] == pytest.approx(3.5)

    def test_sla_buffer_na_when_deadline_missing(self):
        dec = {"selected_end": "2026-09-15T10:00:00+00:00"}
        factors = compute_decision_factors(dec, deadline_iso=None)
        assert factors["sla_buffer_hours"] is None

    def test_sla_buffer_na_when_selected_end_missing(self):
        factors = compute_decision_factors({}, deadline_iso="2026-09-15T13:30:00+00:00")
        assert factors["sla_buffer_hours"] is None

    def test_all_factors_na_for_empty_decision(self):
        factors = compute_decision_factors({}, None)
        assert factors == {
            "carbon_abatement_pct": None,
            "cost_score_pct": None,
            "slot_headroom_pct": None,
            "sla_buffer_hours": None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# B/C. Candidate carbon & cost
# ─────────────────────────────────────────────────────────────────────────────

class TestCandidateRows:
    def test_real_candidate_values_used_verbatim(self):
        dec = {
            "selected_start": "2026-09-15T10:00:00+00:00",
            "candidates": [
                {"slot_start": "2026-09-15T09:00:00+00:00", "slot_end": "2026-09-15T09:30:00+00:00", "carbon_intensity": 210.0, "carbon_emission": 0.07, "electricity_cost": 0.03},
                {"slot_start": "2026-09-15T10:00:00+00:00", "slot_end": "2026-09-15T10:30:00+00:00", "carbon_intensity": 140.0, "carbon_emission": 0.045, "electricity_cost": 0.05},
            ],
            "rejected_candidates": [],
        }
        rows = build_candidate_rows(dec)
        assert len(rows) == 2
        winner = [r for r in rows if r["is_selected"]][0]
        assert winner["carbon_intensity"] == 140.0
        assert winner["electricity_cost"] == 0.05
        assert winner["decision_label"] == "SELECTED"
        loser = [r for r in rows if not r["is_selected"]][0]
        assert loser["carbon_intensity"] == 210.0
        assert loser["decision_label"] == "Feasible (not selected)"

    def test_no_hour_offset_carbon_formula(self):
        """A candidate 2 hours away from the selected slot must not show
        carbon_intensity == selected_intensity + 2*25 (the old fabricated
        formula) — it must show exactly its own recorded value."""
        dec = {
            "selected_start": "2026-09-15T10:00:00+00:00",
            "candidates": [
                {"slot_start": "2026-09-15T08:00:00+00:00", "slot_end": "2026-09-15T08:30:00+00:00", "carbon_intensity": 300.0, "carbon_emission": 0.1, "electricity_cost": 0.02},
                {"slot_start": "2026-09-15T10:00:00+00:00", "slot_end": "2026-09-15T10:30:00+00:00", "carbon_intensity": 140.0, "carbon_emission": 0.045, "electricity_cost": 0.05},
            ],
        }
        rows = build_candidate_rows(dec)
        far_candidate = [r for r in rows if r["slot_start"] == "2026-09-15T08:00:00+00:00"][0]
        # The fabricated formula would have produced 140.0 + 2*25.0 = 190.0.
        assert far_candidate["carbon_intensity"] == 300.0
        assert far_candidate["carbon_intensity"] != 190.0

    def test_no_ten_percent_hourly_cost_multiplier(self):
        """A candidate 2 hours away must not show
        selected_cost * (1 + 2*0.1) (the old fabricated formula)."""
        dec = {
            "selected_start": "2026-09-15T10:00:00+00:00",
            "candidates": [
                {"slot_start": "2026-09-15T08:00:00+00:00", "slot_end": "2026-09-15T08:30:00+00:00", "carbon_intensity": 300.0, "carbon_emission": 0.1, "electricity_cost": 0.09},
                {"slot_start": "2026-09-15T10:00:00+00:00", "slot_end": "2026-09-15T10:30:00+00:00", "carbon_intensity": 140.0, "carbon_emission": 0.045, "electricity_cost": 0.05},
            ],
        }
        rows = build_candidate_rows(dec)
        far_candidate = [r for r in rows if r["slot_start"] == "2026-09-15T08:00:00+00:00"][0]
        # The fabricated formula would have produced 0.05 * 1.2 = 0.06.
        assert far_candidate["electricity_cost"] == 0.09
        assert far_candidate["electricity_cost"] != pytest.approx(0.06)

    def test_no_candidate_data_returns_empty_not_synthetic(self):
        assert build_candidate_rows({}) == []
        assert build_candidate_rows({"candidates": None, "rejected_candidates": None}) == []

    def test_format_candidate_table_labels_currency_as_usd_not_dollar_sign(self):
        dec = {
            "selected_start": "2026-09-15T10:00:00+00:00",
            "candidates": [{"slot_start": "2026-09-15T10:00:00+00:00", "slot_end": "2026-09-15T10:30:00+00:00", "carbon_intensity": 140.0, "carbon_emission": 0.045, "electricity_cost": 0.0512}],
        }
        table = format_candidate_table(dec)
        assert table[0]["Electricity Cost"] == "0.0512 USD"
        assert "$" not in table[0]["Electricity Cost"]

    def test_format_candidate_table_na_for_missing_carbon_or_cost(self):
        dec = {
            "selected_start": "2026-09-15T10:00:00+00:00",
            "candidates": [{"slot_start": "2026-09-15T10:00:00+00:00", "slot_end": "2026-09-15T10:30:00+00:00", "carbon_intensity": None, "carbon_emission": None, "electricity_cost": None}],
        }
        table = format_candidate_table(dec)
        assert table[0]["Carbon Intensity"] == NA
        assert table[0]["Electricity Cost"] == NA

    def test_rows_are_sorted_by_start_time(self):
        dec = {
            "selected_start": "2026-09-15T10:00:00+00:00",
            "candidates": [{"slot_start": "2026-09-15T12:00:00+00:00", "slot_end": "2026-09-15T12:30:00+00:00", "carbon_intensity": 1.0, "carbon_emission": 1.0, "electricity_cost": 1.0}],
            "rejected_candidates": [{"slot_start": "2026-09-15T08:00:00+00:00", "slot_end": "2026-09-15T08:30:00+00:00", "rejection_reasons": ["DEADLINE_VIOLATION"]}],
        }
        rows = build_candidate_rows(dec)
        assert [r["slot_start"] for r in rows] == ["2026-09-15T08:00:00+00:00", "2026-09-15T12:00:00+00:00"]


# ─────────────────────────────────────────────────────────────────────────────
# D. Feasibility / rejection reasons
# ─────────────────────────────────────────────────────────────────────────────

class TestRejectionReasons:
    @pytest.mark.parametrize("code,expected", [
        ("DEADLINE_VIOLATION", "Misses Deadline"),
        ("SLA_VIOLATION", "Misses Deadline"),
        ("CARBON_BUDGET_EXCEEDED", "Exceeds Carbon Budget"),
        ("INSUFFICIENT_CPU", "Insufficient CPU"),
        ("INSUFFICIENT_RAM", "Insufficient RAM"),
        ("INSUFFICIENT_GPU", "Insufficient GPU"),
        ("REGION_INELIGIBLE", "Outside Allowed Region"),
        ("CARBON_DATA_UNAVAILABLE", "Carbon Data Unavailable"),
        ("COST_DATA_UNAVAILABLE", "Cost Data Unavailable"),
    ])
    def test_known_codes_map_to_truthful_labels(self, code, expected):
        assert humanize_rejection_reason(code) == expected

    def test_missing_code_is_na_not_generic_higher_carbon(self):
        assert humanize_rejection_reason(None) == NA
        assert humanize_rejection_reason("") == NA

    def test_unrecognized_code_is_shown_not_swallowed(self):
        assert humanize_rejection_reason("SOME_NEW_CODE") == "Some New Code"

    def test_rejected_candidate_uses_real_reason_not_generic_higher_carbon(self):
        dec = {
            "selected_start": "2026-09-15T10:00:00+00:00",
            "rejected_candidates": [
                {"slot_start": "2026-09-15T08:00:00+00:00", "slot_end": "2026-09-15T08:30:00+00:00", "rejection_reasons": ["INSUFFICIENT_GPU"], "primary_rejection_reason": "INSUFFICIENT_GPU"},
            ],
        }
        rows = build_candidate_rows(dec)
        assert rows[0]["decision_label"] == "Insufficient GPU"
        assert rows[0]["feasible"] is False
        assert rows[0]["decision_label"] != "Higher Carbon"

    def test_two_different_rejected_candidates_get_distinct_truthful_reasons(self):
        dec = {
            "selected_start": "2026-09-15T10:00:00+00:00",
            "rejected_candidates": [
                {"slot_start": "2026-09-15T08:00:00+00:00", "slot_end": "2026-09-15T08:30:00+00:00", "primary_rejection_reason": "DEADLINE_VIOLATION"},
                {"slot_start": "2026-09-15T09:00:00+00:00", "slot_end": "2026-09-15T09:30:00+00:00", "primary_rejection_reason": "CARBON_BUDGET_EXCEEDED"},
            ],
        }
        rows = build_candidate_rows(dec)
        labels = {r["slot_start"]: r["decision_label"] for r in rows}
        assert labels["2026-09-15T08:00:00+00:00"] == "Misses Deadline"
        assert labels["2026-09-15T09:00:00+00:00"] == "Exceeds Carbon Budget"


# ─────────────────────────────────────────────────────────────────────────────
# Objective formatting
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatSchedulerObjective:
    def test_carbon_first_not_hardcoded_for_other_policies(self):
        assert format_scheduler_objective({"scheduler_objective": "CARBON_FIRST"}) == "CARBON_FIRST"
        assert format_scheduler_objective({"scheduler_objective": "COST_FIRST"}) == "COST_FIRST"

    def test_carbon_constrained_includes_real_tolerance(self):
        result = format_scheduler_objective({"scheduler_objective": "CARBON_CONSTRAINED", "carbon_tolerance_pct": 7.5})
        assert result == "CARBON_CONSTRAINED (7.5% tolerance)"

    def test_missing_objective_is_na(self):
        assert format_scheduler_objective({}) == NA


# ─────────────────────────────────────────────────────────────────────────────
# E. Consistency — real API response -> dashboard helpers, end to end
# ─────────────────────────────────────────────────────────────────────────────

class TestEndToEndConsistency:
    def test_minimal_decision_has_no_fabricated_defaults(self, client, db, admin_user):
        """A decision missing baseline/candidate data must never surface
        the old fabricated 310.0/0.045/0.012/88/74/82/95 constants."""
        _make_job(db, "JOB-EXPLAIN-MINIMAL")
        dec = _fetch_dec(client, _token(admin_user), "JOB-EXPLAIN-MINIMAL")

        # Real stored values pass through untouched.
        assert dec["carbon_intensity"] == 157.0
        assert dec["electricity_cost"] == 0.0233
        # Never coerced to the old fabricated fallbacks.
        assert dec["carbon_intensity"] != 310.0
        assert dec["electricity_cost"] != 0.045

        factors = compute_decision_factors(dec, deadline_iso=None)
        assert factors["carbon_abatement_pct"] is None  # no baseline stored
        assert factors["cost_score_pct"] is None
        assert factors["slot_headroom_pct"] is None  # single-job, no capacity registry

        assert format_candidate_table(dec) == []  # no candidates_json stored
        assert format_scheduler_objective(dec) == "CARBON_FIRST"  # real column default, not a UI hardcode

    def test_full_decision_flows_through_consistently(self, client, db, admin_user):
        """A decision with real baseline/candidate/policy data must expose
        exactly those real values through the API and the shared helpers."""
        job = _make_job(
            db, "JOB-EXPLAIN-FULL",
            carbon_avoided=0.031, baseline_carbon_emission=0.083,
            carbon_reduction_pct=37.3,
            baseline_cost=0.09, cost_difference=0.02, cost_reduction_pct=-14.2,
            scheduler_objective="CARBON_CONSTRAINED", carbon_tolerance_pct=8.0,
            slot_utilization_pct=41.0,
            candidates_json=[
                {"slot_start": job_iso, "slot_end": job_iso, "carbon_intensity": 157.0, "carbon_emission": 0.0523, "electricity_cost": 0.0233}
                for job_iso in ["2026-09-15T11:00:00+00:00"]
            ],
            rejected_candidates_json=[
                {"slot_start": "2026-09-15T09:00:00+00:00", "slot_end": "2026-09-15T09:30:00+00:00", "primary_rejection_reason": "CARBON_BUDGET_EXCEEDED"},
            ],
        )
        dec = _fetch_dec(client, _token(admin_user), "JOB-EXPLAIN-FULL")

        assert dec["scheduler_objective"] == "CARBON_CONSTRAINED"
        assert dec["carbon_tolerance_pct"] == 8.0
        assert format_scheduler_objective(dec) == "CARBON_CONSTRAINED (8% tolerance)"

        factors = compute_decision_factors(dec, deadline_iso=dec.get("selected_end"))
        assert factors["carbon_abatement_pct"] == 37.3
        assert factors["cost_score_pct"] == -14.2  # truthfully negative, not hidden
        assert factors["slot_headroom_pct"] == pytest.approx(59.0)

        rows = build_candidate_rows(dec)
        assert len(rows) == 2
        rejected = [r for r in rows if not r["feasible"]][0]
        assert rejected["decision_label"] == "Exceeds Carbon Budget"

    def test_both_views_share_the_identical_helper_functions(self):
        """Structural guarantee against the two dashboard views ever
        re-diverging into independent fabricated implementations."""
        import app.dashboard.views.scheduling_engine as se_view
        import app.dashboard.views.workloads as wl_view

        assert se_view.compute_decision_factors is wl_view.compute_decision_factors
        assert se_view.format_candidate_table is wl_view.format_candidate_table
        assert se_view.format_scheduler_objective is wl_view.format_scheduler_objective
