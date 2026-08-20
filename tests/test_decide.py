"""
Tests for Agent 2 — DECIDE (Scheduler)
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.decide.scheduler import (
    schedule_job,
    _energy_kwh,
    _carbon_kg,
    _cost_usd,
    _generate_candidate_slots,
    _interpolate_carbon,
    _interpolate_tariff,
)
from app.shared.models import CarbonDataPoint, TariffDataPoint, ScheduleDecision


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def now():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


@pytest.fixture()
def carbon_curve(now):
    return [
        CarbonDataPoint(
            timestamp=now + timedelta(hours=i),
            region="IN-WE",
            carbon_gco2_kwh=300.0 - i * 20,  # decreasing: hour 0=300, hour 11=80
        )
        for i in range(12)
    ]


@pytest.fixture()
def tariff_curve(now):
    return [
        TariffDataPoint(
            timestamp=now + timedelta(hours=i),
            region="IN-WE",
            price_per_kwh=0.10 - i * 0.005,  # decreasing
        )
        for i in range(12)
    ]


# ─── Unit calculations ────────────────────────────────────────────────────────

class TestCalculations:
    def test_energy_kwh(self):
        assert _energy_kwh(2.0, 60) == pytest.approx(2.0)
        assert _energy_kwh(0.5, 30) == pytest.approx(0.25)

    def test_carbon_kg(self):
        # 0.25 kWh × 400 gCO2/kWh / 1000 = 0.1 kg
        assert _carbon_kg(0.25, 400.0) == pytest.approx(0.1)

    def test_cost_usd(self):
        # 0.25 kWh × $0.10/kWh = $0.025
        assert _cost_usd(0.25, 0.10) == pytest.approx(0.025)


# ─── Candidate slot generation ────────────────────────────────────────────────

class TestCandidateSlots:
    def test_returns_slots(self, now):
        deadline = now + timedelta(hours=10)
        slots = _generate_candidate_slots(now, deadline, runtime_minutes=60)
        assert len(slots) > 0

    def test_no_slots_if_deadline_too_soon(self, now):
        deadline = now + timedelta(minutes=30)
        slots = _generate_candidate_slots(now, deadline, runtime_minutes=60)
        assert slots == []

    def test_latest_start_respected(self, now):
        deadline = now + timedelta(hours=6)
        runtime = 120
        slots = _generate_candidate_slots(now, deadline, runtime_minutes=runtime)
        latest_allowed = deadline - timedelta(minutes=runtime)
        for s in slots:
            assert s <= latest_allowed + timedelta(minutes=1)  # small tolerance


# ─── Interpolation ────────────────────────────────────────────────────────────

class TestInterpolation:
    def test_exact_timestamp_returns_value(self, now, carbon_curve):
        val = _interpolate_carbon(now, carbon_curve)
        assert val == pytest.approx(300.0)

    def test_nearest_neighbour(self, now, carbon_curve):
        # Midpoint between hour 2 and hour 3 — should pick nearest
        ts = now + timedelta(hours=2, minutes=20)
        val = _interpolate_carbon(ts, carbon_curve)
        assert val in (carbon_curve[2].carbon_gco2_kwh, carbon_curve[3].carbon_gco2_kwh)

    def test_empty_curve_returns_sentinel(self, now):
        val = _interpolate_carbon(now, [])
        assert val == 500.0

    def test_tariff_empty_returns_sentinel(self, now):
        val = _interpolate_tariff(now, [])
        assert val == 1.0


# ─── Full scheduler ───────────────────────────────────────────────────────────

class TestScheduler:
    def test_schedule_selects_lowest_carbon_slot(self, now, carbon_curve, tariff_curve):
        """Scheduler should select the slot with lowest carbon intensity."""
        decision = schedule_job(
            job_id="JOB-TEST",
            team_id="TEST",
            deadline=now + timedelta(hours=12),
            runtime_minutes=60,
            power_kw=0.5,
            region="IN-WE",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
        )
        # carbon_curve is decreasing, so latest slots are lowest carbon
        assert isinstance(decision, ScheduleDecision)
        assert decision.carbon_emission < decision.baseline_carbon_emission

    def test_schedule_returns_valid_window(self, now, carbon_curve, tariff_curve):
        deadline = now + timedelta(hours=12)
        decision = schedule_job(
            job_id="JOB-TEST2",
            team_id="TEST",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=0.5,
            region="IN-WE",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
        )
        # selected_end should be within deadline
        assert decision.selected_end <= deadline + timedelta(minutes=1)
        # selected_end should be selected_start + runtime
        delta = (decision.selected_end - decision.selected_start).total_seconds() / 60
        assert abs(delta - 60) < 2  # within 2 minutes

    def test_schedule_calculates_carbon_avoided(self, now, carbon_curve, tariff_curve):
        decision = schedule_job(
            job_id="JOB-TEST3",
            team_id="TEST",
            deadline=now + timedelta(hours=12),
            runtime_minutes=60,
            power_kw=0.5,
            region="IN-WE",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
        )
        # carbon_avoided = baseline - greenshift
        expected = decision.baseline_carbon_emission - decision.carbon_emission
        assert abs((decision.carbon_avoided or 0) - max(0.0, expected)) < 1e-6

    def test_schedule_raises_if_no_feasible_window(self, now, carbon_curve, tariff_curve):
        """Should raise ValueError if deadline is before earliest start."""
        with pytest.raises(ValueError):
            schedule_job(
                job_id="JOB-IMPOSSIBLE",
                team_id="TEST",
                deadline=now + timedelta(minutes=10),
                runtime_minutes=60,
                power_kw=0.5,
                region="IN-WE",
                carbon_curve=carbon_curve,
                tariff_curve=tariff_curve,
            )

    def test_budget_constraint_filters_slots(self, now, carbon_curve, tariff_curve):
        """Very tight budget should trigger budget relaxation fallback."""
        decision = schedule_job(
            job_id="JOB-BUDGET",
            team_id="TEST",
            deadline=now + timedelta(hours=12),
            runtime_minutes=60,
            power_kw=0.5,
            region="IN-WE",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            carbon_budget_kg=0.000001,  # impossibly small
        )
        # Should still return a decision (with relaxed budget)
        assert isinstance(decision, ScheduleDecision)
        assert "relaxed" in decision.reason.lower() or "budget" in decision.reason.lower()
