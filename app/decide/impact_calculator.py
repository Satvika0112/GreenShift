"""
Agent 2 — DECIDE / BASELINE & IMPACT CALCULATOR
Quantitative evaluation comparing Baseline (immediate) vs GreenShift (optimized).

Calculates:
- Baseline: immediate execution emissions, cost (USD & native), completion time
- GreenShift: optimized slot emissions, cost (USD & native), completion time
- Impact: carbon avoided, carbon reduction %, cost avoided, cost reduction %,
  scheduling delay, and SLA compliance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WorkloadScenarioMetrics:
    start_time: datetime
    end_time: datetime
    carbon_intensity_gco2_kwh: float
    carbon_emission_kg: float
    price_per_kwh_usd: float
    electricity_cost_usd: float
    native_rate_per_kwh: float
    native_cost: float
    currency: str


@dataclass
class ImpactComparisonResult:
    baseline: WorkloadScenarioMetrics
    greenshift: WorkloadScenarioMetrics
    carbon_avoided_kg: float
    carbon_reduction_pct: float
    cost_avoided_usd: float
    cost_reduction_pct: float
    native_cost_avoided: float
    scheduling_delay_hours: float
    sla_met: bool
    deadline: datetime


def calculate_impact(
    energy_kwh: float,
    deadline: datetime,
    baseline_start: datetime,
    baseline_carbon_intensity: float,
    baseline_price_usd: float,
    baseline_native_rate: float,
    selected_start: datetime,
    selected_carbon_intensity: float,
    selected_price_usd: float,
    selected_native_rate: float,
    runtime_minutes: int,
    currency: str = "USD",
) -> ImpactComparisonResult:
    """
    Compute rigorous Baseline vs GreenShift comparative impact metrics.
    """
    runtime_delta = timedelta(minutes=runtime_minutes)

    # 1. Baseline scenario
    baseline_end = baseline_start + runtime_delta
    baseline_carbon_kg = (energy_kwh * baseline_carbon_intensity) / 1000.0
    baseline_cost_usd = energy_kwh * baseline_price_usd
    baseline_native_cost = energy_kwh * baseline_native_rate

    baseline_metrics = WorkloadScenarioMetrics(
        start_time=baseline_start,
        end_time=baseline_end,
        carbon_intensity_gco2_kwh=round(baseline_carbon_intensity, 2),
        carbon_emission_kg=round(baseline_carbon_kg, 6),
        price_per_kwh_usd=round(baseline_price_usd, 6),
        electricity_cost_usd=round(baseline_cost_usd, 6),
        native_rate_per_kwh=round(baseline_native_rate, 4),
        native_cost=round(baseline_native_cost, 4),
        currency=currency,
    )

    # 2. GreenShift scenario
    selected_end = selected_start + runtime_delta
    selected_carbon_kg = (energy_kwh * selected_carbon_intensity) / 1000.0
    selected_cost_usd = energy_kwh * selected_price_usd
    selected_native_cost = energy_kwh * selected_native_rate

    greenshift_metrics = WorkloadScenarioMetrics(
        start_time=selected_start,
        end_time=selected_end,
        carbon_intensity_gco2_kwh=round(selected_carbon_intensity, 2),
        carbon_emission_kg=round(selected_carbon_kg, 6),
        price_per_kwh_usd=round(selected_price_usd, 6),
        electricity_cost_usd=round(selected_cost_usd, 6),
        native_rate_per_kwh=round(selected_native_rate, 4),
        native_cost=round(selected_native_cost, 4),
        currency=currency,
    )

    # 3. Comparative metrics
    carbon_avoided = max(0.0, baseline_carbon_kg - selected_carbon_kg)
    carbon_reduction_pct = (
        (carbon_avoided / baseline_carbon_kg * 100.0) if baseline_carbon_kg > 0 else 0.0
    )

    cost_avoided_usd = baseline_cost_usd - selected_cost_usd
    cost_reduction_pct = (
        (cost_avoided_usd / baseline_cost_usd * 100.0) if baseline_cost_usd > 0 else 0.0
    )

    native_cost_avoided = baseline_native_cost - selected_native_cost
    delay_hours = max(0.0, (selected_start - baseline_start).total_seconds() / 3600.0)
    sla_met = bool(selected_end <= deadline + timedelta(seconds=1))

    return ImpactComparisonResult(
        baseline=baseline_metrics,
        greenshift=greenshift_metrics,
        carbon_avoided_kg=round(carbon_avoided, 6),
        carbon_reduction_pct=round(max(0.0, carbon_reduction_pct), 2),
        cost_avoided_usd=round(cost_avoided_usd, 6),
        cost_reduction_pct=round(cost_reduction_pct, 2),
        native_cost_avoided=round(native_cost_avoided, 4),
        scheduling_delay_hours=round(delay_hours, 2),
        sla_met=sla_met,
        deadline=deadline,
    )
