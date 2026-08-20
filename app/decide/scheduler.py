"""
Agent 2 — DECIDE
Carbon-Aware Greedy Scheduling Algorithm.

Algorithm:
1. Generate all feasible 1-hour slots between now and (deadline - runtime).
2. For each slot, look up carbon intensity and tariff.
3. Calculate energy, carbon emission, and cost for each slot.
4. Filter slots that exceed the team's carbon budget.
5. Select the slot with the lowest carbon emission (primary) and lowest cost (tiebreaker).
6. Calculate baseline (earliest feasible slot) for comparison.
7. Return a ScheduleDecision.

This module does NOT call Kubernetes. It only produces scheduling decisions.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from app.shared.models import (
    CarbonDataPoint,
    TariffDataPoint,
    ScheduleDecision,
)

logger = logging.getLogger(__name__)

# Slot resolution: evaluate windows every N minutes
SLOT_RESOLUTION_MINUTES = 60


def _energy_kwh(power_kw: float, runtime_minutes: int) -> float:
    """Calculate energy in kWh."""
    return power_kw * (runtime_minutes / 60.0)


def _carbon_kg(energy_kwh: float, carbon_gco2_kwh: float) -> float:
    """Calculate carbon emissions in kg CO2."""
    return energy_kwh * carbon_gco2_kwh / 1000.0


def _cost_usd(energy_kwh: float, price_per_kwh: float) -> float:
    """Calculate electricity cost in USD (or local currency)."""
    return energy_kwh * price_per_kwh


def _interpolate_carbon(
    timestamp: datetime,
    carbon_curve: List[CarbonDataPoint],
) -> float:
    """
    Return the carbon intensity for a given timestamp.
    Uses nearest-neighbour lookup. Returns a high sentinel value if not found.
    """
    if not carbon_curve:
        return 500.0  # high fallback

    # Find nearest point
    best = min(carbon_curve, key=lambda p: abs((p.timestamp - timestamp).total_seconds()))
    diff = abs((best.timestamp - timestamp).total_seconds())
    if diff > 7200:  # more than 2 hours away — unreliable
        logger.warning("No carbon data near %s (nearest: %s, diff: %.0fs)", timestamp, best.timestamp, diff)
        return 500.0
    return best.carbon_gco2_kwh


def _interpolate_tariff(
    timestamp: datetime,
    tariff_curve: List[TariffDataPoint],
) -> float:
    """
    Return the tariff for a given timestamp.
    Uses nearest-neighbour lookup. Returns a high sentinel value if not found.
    """
    if not tariff_curve:
        return 1.0

    best = min(tariff_curve, key=lambda p: abs((p.timestamp - timestamp).total_seconds()))
    diff = abs((best.timestamp - timestamp).total_seconds())
    if diff > 7200:
        return 1.0
    return best.price_per_kwh


def _generate_candidate_slots(
    now: datetime,
    deadline: datetime,
    runtime_minutes: int,
) -> List[datetime]:
    """
    Generate candidate start times at hourly resolution.
    The latest possible start is deadline - runtime.
    """
    runtime_delta = timedelta(minutes=runtime_minutes)
    latest_start = deadline - runtime_delta

    if latest_start <= now:
        return []  # no feasible window

    slots = []
    candidate = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while candidate <= latest_start:
        slots.append(candidate)
        candidate += timedelta(minutes=SLOT_RESOLUTION_MINUTES)

    # Also include 'now' (immediate start) as a candidate
    if now <= latest_start:
        slots.insert(0, now)

    return slots


def schedule_job(
    job_id: str,
    team_id: str,
    deadline: datetime,
    runtime_minutes: int,
    power_kw: float,
    region: str,
    carbon_curve: List[CarbonDataPoint],
    tariff_curve: List[TariffDataPoint],
    carbon_budget_kg: Optional[float] = None,
) -> ScheduleDecision:
    """
    Core scheduling algorithm.

    Args:
        job_id:           GreenShift job ID
        team_id:          Team identifier
        deadline:         Latest end time for the job
        runtime_minutes:  Expected runtime
        power_kw:         Average power draw
        region:           Grid region
        carbon_curve:     Hourly carbon intensity points
        tariff_curve:     Hourly tariff points
        carbon_budget_kg: Optional max carbon budget

    Returns:
        ScheduleDecision with the selected window and comparison metrics.

    Raises:
        ValueError: If no feasible scheduling window exists.
    """
    now = datetime.now(timezone.utc)
    energy = _energy_kwh(power_kw, runtime_minutes)

    # Ensure all datetimes are UTC-aware
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    logger.info(
        "Scheduling job %s | runtime=%dm | power=%.2fkW | energy=%.4fkWh | deadline=%s",
        job_id,
        runtime_minutes,
        power_kw,
        energy,
        deadline.isoformat(),
    )

    # Generate candidate slots
    candidates = _generate_candidate_slots(now, deadline, runtime_minutes)
    if not candidates:
        raise ValueError(
            f"Job {job_id}: deadline {deadline} is too soon for {runtime_minutes}min runtime"
        )

    # Score each slot
    scored: List[Tuple[datetime, float, float]] = []  # (start, carbon_kg, cost)
    for start in candidates:
        c_intensity = _interpolate_carbon(start, carbon_curve)
        tariff = _interpolate_tariff(start, tariff_curve)
        c_kg = _carbon_kg(energy, c_intensity)
        cost = _cost_usd(energy, tariff)

        # Budget filter
        if carbon_budget_kg is not None and c_kg > carbon_budget_kg:
            logger.debug("Slot %s filtered: c_kg=%.4f > budget=%.4f", start, c_kg, carbon_budget_kg)
            continue

        scored.append((start, c_kg, cost))

    if not scored:
        # All slots exceed budget — relax and pick the lowest
        logger.warning("Job %s: all slots exceed budget — selecting minimum-carbon slot anyway", job_id)
        for start in candidates:
            c_intensity = _interpolate_carbon(start, carbon_curve)
            tariff = _interpolate_tariff(start, tariff_curve)
            scored.append((start, _carbon_kg(energy, c_intensity), _cost_usd(energy, tariff)))
        reason = "Budget constraint relaxed — no slot within budget; selected minimum-carbon slot"
    else:
        reason = "Lowest carbon window within deadline and budget"

    # Select best slot: primary = lowest carbon, secondary = lowest cost
    best_start, best_carbon, best_cost = min(scored, key=lambda x: (x[1], x[2]))
    best_end = best_start + timedelta(minutes=runtime_minutes)
    best_intensity = _interpolate_carbon(best_start, carbon_curve)
    best_tariff = _interpolate_tariff(best_start, tariff_curve)

    # Baseline: earliest feasible slot
    baseline_start = candidates[0]
    baseline_intensity = _interpolate_carbon(baseline_start, carbon_curve)
    baseline_tariff = _interpolate_tariff(baseline_start, tariff_curve)
    baseline_carbon = _carbon_kg(energy, baseline_intensity)
    baseline_cost = _cost_usd(energy, baseline_tariff)

    carbon_avoided = max(0.0, baseline_carbon - best_carbon)
    cost_difference = baseline_cost - best_cost
    budget_remaining = (carbon_budget_kg - best_carbon) if carbon_budget_kg else None

    logger.info(
        "Job %s → selected_start=%s | carbon=%.4fkg | cost=%.4f | avoided=%.4fkg",
        job_id,
        best_start.isoformat(),
        best_carbon,
        best_cost,
        carbon_avoided,
    )

    return ScheduleDecision(
        job_id=job_id,
        selected_start=best_start,
        selected_end=best_end,
        carbon_intensity=round(best_intensity, 2),
        electricity_cost=round(best_tariff, 4),
        carbon_emission=round(best_carbon, 6),
        reason=reason,
        budget_remaining=round(budget_remaining, 6) if budget_remaining is not None else None,
        baseline_start=baseline_start,
        baseline_carbon_emission=round(baseline_carbon, 6),
        baseline_cost=round(baseline_cost, 6),
        carbon_avoided=round(carbon_avoided, 6),
        cost_difference=round(cost_difference, 6),
    )
