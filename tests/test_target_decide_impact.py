"""
Tests for DECIDE Scheduling Policy & Baseline vs GreenShift Impact Calculator.

Covers:
- Hard constraints enforcement (Budget, Deadline, CPU/RAM/GPU)
- Carbon-First optimization as primary objective
- Cost tie-breaker when carbon emissions are equal
- Quantitative Baseline vs GreenShift impact calculation
"""

from datetime import datetime, timedelta, timezone
import pytest

from app.decide.scheduler import schedule_job
from app.decide.impact_calculator import calculate_impact
from app.shared.models import CarbonDataPoint, TariffDataPoint


class TestDecidePolicyAndConstraints:
    def test_deadline_hard_constraint(self):
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(minutes=30)  # Deadline too short for 60m job

        with pytest.raises(ValueError, match="deadline"):
            schedule_job(
                job_id="TEST-DEADLINE",
                team_id="ops",
                deadline=deadline,
                runtime_minutes=60,
                power_kw=5.0,
                region="IN-TG",
                carbon_curve=[CarbonDataPoint(timestamp=now, region="IN-TG", carbon_gco2_kwh=300.0)],
                tariff_curve=[TariffDataPoint(timestamp=now, region="IN-TG", price_per_kwh=0.08)],
                earliest_start_time=now,
            )

    def test_carbon_first_optimization_with_cost_tiebreaker(self):
        """Under Carbon-First policy: lowest carbon wins; if equal carbon, lowest cost wins."""
        start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        deadline = start + timedelta(hours=4)

        # Slot 0: Carbon 300, Cost $0.05
        # Slot 1: Carbon 200, Cost $0.10 (Lower carbon -> wins over Slot 0)
        # Slot 2: Carbon 200, Cost $0.08 (Equal lowest carbon, lower cost -> wins over Slot 1)
        carbon_curve = [
            CarbonDataPoint(timestamp=start, region="IN-TG", carbon_gco2_kwh=300.0),
            CarbonDataPoint(timestamp=start + timedelta(hours=1), region="IN-TG", carbon_gco2_kwh=200.0),
            CarbonDataPoint(timestamp=start + timedelta(hours=2), region="IN-TG", carbon_gco2_kwh=200.0),
        ]
        tariff_curve = [
            TariffDataPoint(timestamp=start, region="IN-TG", price_per_kwh=0.05),
            TariffDataPoint(timestamp=start + timedelta(hours=1), region="IN-TG", price_per_kwh=0.10),
            TariffDataPoint(timestamp=start + timedelta(hours=2), region="IN-TG", price_per_kwh=0.08),
        ]

        decision = schedule_job(
            job_id="TEST-CARBON-FIRST-TIEBREAKER",
            team_id="ml",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-TG",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            earliest_start_time=start,
        )

        # Slot 2 (hours=2) has equal minimum carbon (200 gCO2/kWh -> 2.0 kg) and lower cost ($0.08 vs $0.10)
        assert decision.selected_start == start + timedelta(hours=2)
        assert abs(decision.carbon_emission - (10.0 * 200.0 / 1000.0)) < 1e-5
        assert abs(decision.electricity_cost - (10.0 * 0.08)) < 1e-5

    def test_carbon_budget_constraint(self):
        start = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
        deadline = start + timedelta(hours=3)

        # 10 kW * 1h = 10 kWh. At 500 gCO2/kWh -> 5.0 kg CO2. At 200 gCO2/kWh -> 2.0 kg CO2.
        # Budget = 3.0 kg CO2 -> Filter out slot with 500 gCO2/kWh even if cheaper.
        carbon_curve = [
            CarbonDataPoint(timestamp=start, region="IN-TG", carbon_gco2_kwh=500.0), # 5.0 kg (over budget)
            CarbonDataPoint(timestamp=start + timedelta(hours=1), region="IN-TG", carbon_gco2_kwh=200.0), # 2.0 kg (within budget)
        ]
        tariff_curve = [
            TariffDataPoint(timestamp=start, region="IN-TG", price_per_kwh=0.01),  # Cheaper but over budget
            TariffDataPoint(timestamp=start + timedelta(hours=1), region="IN-TG", price_per_kwh=0.05),
        ]

        decision = schedule_job(
            job_id="TEST-BUDGET",
            team_id="data",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-TG",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            carbon_budget_kg=3.0,
            earliest_start_time=start,
        )

        assert decision.selected_start == start + timedelta(hours=1)
        assert decision.carbon_emission <= 3.0


class TestImpactCalculator:
    def test_impact_calculation_metrics(self):
        baseline_start = datetime.now(timezone.utc)
        selected_start = baseline_start + timedelta(hours=2)
        deadline = baseline_start + timedelta(hours=6)

        impact = calculate_impact(
            energy_kwh=100.0,
            deadline=deadline,
            baseline_start=baseline_start,
            baseline_carbon_intensity=500.0,
            baseline_price_usd=0.10,
            baseline_native_rate=8.33,
            selected_start=selected_start,
            selected_carbon_intensity=250.0,
            selected_price_usd=0.05,
            selected_native_rate=4.17,
            runtime_minutes=120,
            currency="USD",
        )

        # Baseline: 100 kWh * 500 / 1000 = 50 kg CO2 | Cost $10
        # GreenShift: 100 kWh * 250 / 1000 = 25 kg CO2 | Cost $5
        assert impact.baseline.carbon_emission_kg == 50.0
        assert impact.greenshift.carbon_emission_kg == 25.0
        assert impact.carbon_avoided_kg == 25.0
        assert impact.carbon_reduction_pct == 50.0
        assert impact.cost_avoided_usd == 5.0
        assert impact.cost_reduction_pct == 50.0
        assert impact.scheduling_delay_hours == 2.0
        assert impact.sla_met is True
