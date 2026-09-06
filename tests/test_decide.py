"""
Tests for Agent 2 — DECIDE (Carbon-First Scheduler).

Covers:
1. Unit calculations (energy, carbon, cost)
2. Candidate slot generation and non-deferrable handling
3. Interpolation and missing telemetry handling (no fabrication of 500.0)
4. Carbon-first optimization:
   - TEST A: Carbon wins over cost
   - TEST B: Cost breaks carbon tie
   - TEST C: Deterministic earliest start time tie-break
   - TEST D: Strict carbon budget enforcement (no relaxation, raises ValueError)
   - TEST E: Deadline enforcement
   - TEST F: Cluster resource feasibility checks
   - TEST G: Non-deferrable workloads
   - TEST H: Missing carbon telemetry rejection
   - TEST I: Approval gate transition to PENDING_APPROVAL
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from app.decide.scheduler import (
    schedule_job,
    _energy_kwh,
    _carbon_kg,
    _cost_usd,
    _generate_candidate_slots,
    _interpolate_carbon,
    _interpolate_tariff,
    CandidateRejectionReason,
)
from app.shared.models import CarbonDataPoint, TariffDataPoint, ScheduleDecision, JobStatus, JobSubmitRequest
from app.ingest.jobs import submit_job
from app.decide.service import schedule_and_store
from app.shared.utils import utcnow


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
            assert s <= latest_allowed + timedelta(minutes=1)

    def test_non_deferrable_returns_only_earliest_slot(self, now):
        deadline = now + timedelta(hours=10)
        slots = _generate_candidate_slots(now, deadline, runtime_minutes=60, deferrable=False)
        assert len(slots) == 1
        assert slots[0] == now


# ─── Interpolation & Telemetry Handling ───────────────────────────────────────

class TestInterpolation:
    def test_exact_timestamp_returns_value(self, now, carbon_curve):
        val = _interpolate_carbon(now, carbon_curve)
        assert val == pytest.approx(300.0)

    def test_nearest_neighbour(self, now, carbon_curve):
        ts = now + timedelta(hours=2, minutes=20)
        val = _interpolate_carbon(ts, carbon_curve)
        assert val in (carbon_curve[2].carbon_gco2_kwh, carbon_curve[3].carbon_gco2_kwh)

    def test_empty_curve_returns_none_not_fabricated_value(self, now):
        val = _interpolate_carbon(now, [])
        assert val is None

    def test_empty_tariff_returns_none(self, now):
        val = _interpolate_tariff(now, [])
        assert val is None


# ─── Carbon-First Scheduler Tests ─────────────────────────────────────────────

class TestScheduler:
    def test_schedule_selects_lowest_carbon_slot(self, now, carbon_curve, tariff_curve):
        """Scheduler should select the slot with lowest carbon intensity (carbon-first)."""
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
        assert decision.selected_end <= deadline + timedelta(minutes=1)
        delta = (decision.selected_end - decision.selected_start).total_seconds() / 60
        assert abs(delta - 60) < 2

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
        expected = decision.baseline_carbon_emission - decision.carbon_emission
        assert abs((decision.carbon_avoided or 0) - max(0.0, expected)) < 1e-6

    def test_schedule_raises_if_no_feasible_window(self, now, carbon_curve, tariff_curve):
        """Should raise ValueError if deadline is before earliest start."""
        with pytest.raises(ValueError, match="deadline"):
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

    def test_strict_carbon_budget_raises_value_error_no_relaxation(self, now, carbon_curve, tariff_curve):
        """TEST D: Impossibly small budget must raise ValueError without silent budget relaxation."""
        with pytest.raises(ValueError, match="carbon budget"):
            schedule_job(
                job_id="JOB-BUDGET",
                team_id="TEST",
                deadline=now + timedelta(hours=12),
                runtime_minutes=60,
                power_kw=0.5,
                region="IN-WE",
                carbon_curve=carbon_curve,
                tariff_curve=tariff_curve,
                carbon_budget_kg=0.000001,  # Impossibly small budget
            )

    def test_a_carbon_wins_over_cost(self, now):
        """
        TEST A — CARBON WINS OVER COST
        Slot A: Carbon = 2.0 kg, Cost = $0.05
        Slot B: Carbon = 1.0 kg, Cost = $0.15
        Expected: Slot B selected (lower carbon).
        """
        # Power = 10 kW, runtime = 60m -> 10 kWh energy
        # Hour 0: 200 gCO2/kWh -> 2.0 kg, price $0.005 -> $0.05
        # Hour 1: 100 gCO2/kWh -> 1.0 kg, price $0.015 -> $0.15
        carbon_curve = [
            CarbonDataPoint(timestamp=now, region="IN-TG", carbon_gco2_kwh=200.0),
            CarbonDataPoint(timestamp=now + timedelta(hours=1), region="IN-TG", carbon_gco2_kwh=100.0),
        ]
        tariff_curve = [
            TariffDataPoint(timestamp=now, region="IN-TG", price_per_kwh=0.005),
            TariffDataPoint(timestamp=now + timedelta(hours=1), region="IN-TG", price_per_kwh=0.015),
        ]
        decision = schedule_job(
            job_id="JOB-CARBON-WINS",
            team_id="ml",
            deadline=now + timedelta(hours=3),
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-TG",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            earliest_start_time=now,
        )
        assert decision.selected_start == now + timedelta(hours=1)
        assert decision.carbon_emission == pytest.approx(1.0)
        assert decision.electricity_cost == pytest.approx(0.15)

    def test_b_cost_breaks_carbon_tie(self, now):
        """
        TEST B — COST BREAKS CARBON TIE
        Slot A: Carbon = 1.0 kg, Cost = $0.05
        Slot B: Carbon = 1.0 kg, Cost = $0.10
        Expected: Slot A selected (equal carbon, cheaper cost).
        """
        carbon_curve = [
            CarbonDataPoint(timestamp=now, region="IN-TG", carbon_gco2_kwh=100.0),
            CarbonDataPoint(timestamp=now + timedelta(hours=1), region="IN-TG", carbon_gco2_kwh=100.0),
        ]
        tariff_curve = [
            TariffDataPoint(timestamp=now, region="IN-TG", price_per_kwh=0.005),
            TariffDataPoint(timestamp=now + timedelta(hours=1), region="IN-TG", price_per_kwh=0.010),
        ]
        decision = schedule_job(
            job_id="JOB-COST-TIE",
            team_id="ml",
            deadline=now + timedelta(hours=3),
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-TG",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            earliest_start_time=now,
        )
        assert decision.selected_start == now
        assert decision.electricity_cost == pytest.approx(0.05)

    def test_c_deterministic_start_time_tiebreak(self, now):
        """
        TEST C — DETERMINISTIC START TIME TIE-BREAK
        Slot A (10:00): Carbon = 1.0 kg, Cost = $0.10
        Slot B (11:00): Carbon = 1.0 kg, Cost = $0.10
        Expected: Slot A selected (earliest start time).
        """
        carbon_curve = [
            CarbonDataPoint(timestamp=now, region="IN-TG", carbon_gco2_kwh=100.0),
            CarbonDataPoint(timestamp=now + timedelta(hours=1), region="IN-TG", carbon_gco2_kwh=100.0),
        ]
        tariff_curve = [
            TariffDataPoint(timestamp=now, region="IN-TG", price_per_kwh=0.010),
            TariffDataPoint(timestamp=now + timedelta(hours=1), region="IN-TG", price_per_kwh=0.010),
        ]
        decision = schedule_job(
            job_id="JOB-TIME-TIE",
            team_id="ml",
            deadline=now + timedelta(hours=3),
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-TG",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            earliest_start_time=now,
        )
        assert decision.selected_start == now

    def test_g_non_deferrable_workload(self, now):
        """
        TEST G — NON-DEFERRABLE WORKLOAD
        Should only consider the earliest start window even if future slots have lower carbon.
        """
        carbon_curve = [
            CarbonDataPoint(timestamp=now, region="IN-TG", carbon_gco2_kwh=300.0),
            CarbonDataPoint(timestamp=now + timedelta(hours=1), region="IN-TG", carbon_gco2_kwh=50.0),
        ]
        tariff_curve = [
            TariffDataPoint(timestamp=now, region="IN-TG", price_per_kwh=0.10),
            TariffDataPoint(timestamp=now + timedelta(hours=1), region="IN-TG", price_per_kwh=0.05),
        ]
        decision = schedule_job(
            job_id="JOB-NON-DEFERRABLE",
            team_id="ops",
            deadline=now + timedelta(hours=4),
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-TG",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            deferrable=False,
            earliest_start_time=now,
        )
        assert decision.selected_start == now
        assert "Non-deferrable" in decision.reason

    def test_h_missing_carbon_data_raises_value_error(self, now):
        """
        TEST H — MISSING CARBON DATA
        When no trustworthy carbon telemetry is available, scheduler must not use fabricated 500.0.
        """
        with pytest.raises(ValueError, match="Carbon data is unavailable"):
            schedule_job(
                job_id="JOB-NO-CARBON",
                team_id="ops",
                deadline=now + timedelta(hours=4),
                runtime_minutes=60,
                power_kw=5.0,
                region="IN-TG",
                carbon_curve=[],  # Empty curve
                tariff_curve=[TariffDataPoint(timestamp=now, region="IN-TG", price_per_kwh=0.08)],
                earliest_start_time=now,
            )

    @patch("app.decide.scheduler.collect_cluster_state")
    def test_f_resource_constraint_rejection(self, mock_collect, now, carbon_curve, tariff_curve):
        """
        TEST F — RESOURCE CONSTRAINT
        When cluster resources are insufficient for CPU/RAM/GPU, scheduling fails with clear error.
        """
        mock_snapshot = MagicMock()
        mock_snapshot.is_resource_feasible.return_value = (False, "Insufficient CPU: requested 64.0 cores, free 8.0 cores")
        mock_snapshot.allocatable_cpu_cores = 8.0
        mock_snapshot.free_cpu_cores = 8.0
        mock_snapshot.allocatable_memory_mib = 16384.0
        mock_snapshot.free_memory_mib = 16384.0
        mock_snapshot.free_gpus = 0
        mock_collect.return_value = mock_snapshot

        with pytest.raises(ValueError, match="Insufficient cluster capacity"):
            schedule_job(
                job_id="JOB-HIGH-RESOURCE",
                team_id="ops",
                deadline=now + timedelta(hours=4),
                runtime_minutes=60,
                power_kw=5.0,
                region="IN-TG",
                carbon_curve=carbon_curve,
                tariff_curve=tariff_curve,
                cpu_request="64000m",
                earliest_start_time=now,
            )

    def test_i_approval_gate_integration(self, db):
        """
        TEST I — APPROVAL GATE INTEGRATION
        After scheduling, job status transitions to PENDING_APPROVAL and no K8s job exists.
        """
        req = JobSubmitRequest(
            job_id="JOB-DECIDE-APPROVAL-TEST",
            team_id="data-platform",
            deadline=utcnow() + timedelta(hours=8),
            runtime_minutes=45,
            power_kw=4.0,
            region="IN-GJ",
            container_image="greenshift/sim:v1",
        )
        job = submit_job(db, req)
        assert job.status == JobStatus.SUBMITTED

        decision = schedule_and_store(db, job, record_audit=True)
        db.refresh(job)

        assert job.status == JobStatus.PENDING_APPROVAL
        assert job.schedule_decision is not None
        assert decision.id == job.schedule_decision.id
        assert job.kubernetes_execution is None
