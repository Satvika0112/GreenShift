"""
Agent 2 — DECIDE
Carbon-Aware and Cost-Optimizing Scheduler.

DECIDE POLICY:
Hard constraints MUST be checked first:
1. Carbon budget (carbon_emission <= carbon_budget_kg)
2. Deadline (start + runtime <= deadline)
3. SLA (completion on or before deadline)
4. CPU availability (cluster free CPU >= requested CPU)
5. RAM availability (cluster free RAM >= requested RAM)
6. GPU availability (cluster free GPU >= requested GPU)
7. Region restrictions (supported regional plan and grid zone)

After hard constraints pass:
8. Minimize electricity cost (cost_usd).
9. Tie-breaker: Lower carbon emission if costs are equal or nearly equal (within epsilon).

No arbitrary weights. No weighted CCS score.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from app.decide.impact_calculator import calculate_impact
from app.dispatch.k8s_state_collector import (
    collect_cluster_state,
    _parse_cpu_string,
    _parse_memory_string,
)
from app.ingest.regional_registry import (
    get_fx_rate_to_usd,
    get_region_config,
    resolve_region_id,
    select_tariff_plan_for_job,
    utc_to_local,
)
from app.ingest.regional_tariff_loader import (
    get_tariff_csv_path,
    load_raw_tariff_template,
)
from app.shared.tariff_service import get_tariff_for_region_and_time
from app.shared.config import settings
from app.shared.models import (
    CarbonDataPoint,
    ScheduleDecision,
    TariffDataPoint,
)

logger = logging.getLogger(__name__)

SLOT_RESOLUTION_MINUTES = 60
COST_EPSILON = 1e-6  # Nearly equal threshold for tie-breaker


def _energy_kwh(power_kw: float, runtime_minutes: int) -> float:
    """Calculate energy in kWh."""
    return power_kw * (runtime_minutes / 60.0)


def _carbon_kg(energy_kwh: float, carbon_gco2_kwh: float) -> float:
    """Calculate carbon emissions in kg CO2."""
    return energy_kwh * carbon_gco2_kwh / 1000.0


def _cost_usd(energy_kwh: float, price_per_kwh: float) -> float:
    """Calculate electricity cost in USD."""
    return energy_kwh * price_per_kwh


def _interpolate_carbon(
    timestamp: datetime,
    carbon_curve: List[CarbonDataPoint],
) -> float:
    """Return the carbon intensity for a given timestamp."""
    if not carbon_curve:
        return 500.0

    best = min(carbon_curve, key=lambda p: abs((p.timestamp - timestamp).total_seconds()))
    diff = abs((best.timestamp - timestamp).total_seconds())
    if diff > 7200:
        logger.warning("No carbon data near %s (nearest: %s, diff: %.0fs)", timestamp, best.timestamp, diff)
        return 500.0
    return best.carbon_gco2_kwh


def _interpolate_tariff(
    timestamp: datetime,
    tariff_curve: List[TariffDataPoint],
) -> float:
    """Return the tariff ($/kWh) for a given timestamp."""
    if not tariff_curve:
        return 1.0

    best = min(tariff_curve, key=lambda p: abs((p.timestamp - timestamp).total_seconds()))
    diff = abs((best.timestamp - timestamp).total_seconds())
    if diff > 7200:
        return 1.0
    return best.price_per_kwh


def _get_native_rate_at_slot(
    region_id: str,
    tariff_plan: str,
    timestamp: datetime,
    fallback_usd_price: float,
) -> float:
    """Look up native currency tariff rate at given timestamp."""
    try:
        tariff_entry = get_tariff_for_region_and_time(region_id, timestamp)
        if tariff_entry and "effective_price" in tariff_entry:
            return float(tariff_entry["effective_price"])
    except Exception as exc:
        logger.debug("Failed to get tariff from tariff_service for region=%s: %s", region_id, exc)

    cfg = get_region_config(region_id)
    template = load_raw_tariff_template(region=region_id)
    if template:
        _, local_hour = utc_to_local(timestamp, region_id)
        row = template.get(local_hour)
        if row and "rate" in row:
            return float(row["rate"])

    # Fallback via inverse FX rate
    fx = get_fx_rate_to_usd(cfg.currency)
    if fx > 0:
        return round(fallback_usd_price / fx, 4)
    return fallback_usd_price


def _generate_candidate_slots(
    start_bound: datetime,
    deadline: datetime,
    runtime_minutes: int,
    deferrable: bool = True,
) -> List[datetime]:
    """Generate candidate start times at hourly resolution within deadline."""
    runtime_delta = timedelta(minutes=runtime_minutes)
    latest_start = deadline - runtime_delta

    if latest_start < start_bound:
        return []

    if not deferrable:
        return [start_bound]

    slots = []
    candidate = start_bound.replace(minute=0, second=0, microsecond=0)
    if candidate < start_bound:
        candidate += timedelta(hours=1)

    while candidate <= latest_start:
        slots.append(candidate)
        candidate += timedelta(minutes=SLOT_RESOLUTION_MINUTES)

    if start_bound <= latest_start and (not slots or slots[0] != start_bound):
        slots.insert(0, start_bound)

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
    energy_kwh: Optional[float] = None,
    earliest_start_time: Optional[datetime] = None,
    deferrable: Optional[bool] = None,
    job_type: Optional[str] = None,
    tariff_plan: Optional[str] = None,
    cpu_request: str = "500m",
    memory_request: str = "512Mi",
    gpu_request: int = 0,
) -> ScheduleDecision:
    """
    Core scheduling algorithm adhering to the GreenShift Target Architecture.
    """
    now = datetime.now(timezone.utc)

    # 1. Resolve Region & Plan
    region_id = resolve_region_id(region)
    cfg = get_region_config(region_id)
    plan = tariff_plan or select_tariff_plan_for_job(
        region_id, job_type=job_type, timestamp=earliest_start_time or now
    )

    # 2. Calculate Energy
    if energy_kwh is not None and energy_kwh > 0:
        energy = float(energy_kwh)
    else:
        energy = _energy_kwh(power_kw, runtime_minutes)

    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    start_bound = now
    if earliest_start_time is not None:
        if earliest_start_time.tzinfo is None:
            earliest_start_time = earliest_start_time.replace(tzinfo=timezone.utc)
        start_bound = max(now, earliest_start_time)

    is_deferrable = True if deferrable is None else bool(deferrable)

    logger.info(
        "DECIDE scheduling job %s | region=%s | plan=%s | runtime=%dm | energy=%.4fkWh | bound=%s | deadline=%s",
        job_id, region_id, plan, runtime_minutes, energy, start_bound.isoformat(), deadline.isoformat(),
    )

    # 3. Check Cluster Resource Feasibility (Hard constraints 4, 5, 6)
    cluster_state = collect_cluster_state()
    cpu_cores = _parse_cpu_string(cpu_request)
    mem_mib = _parse_memory_string(memory_request)
    feasible, msg = cluster_state.is_resource_feasible(
        cpu_request_cores=cpu_cores,
        memory_request_mib=mem_mib,
        gpu_request=gpu_request,
    )
    if not feasible:
        logger.warning("Cluster resource constraint warning for job %s: %s", job_id, msg)

    # 4. Generate candidate slots within deadline (Hard constraints 2, 3)
    candidates = _generate_candidate_slots(start_bound, deadline, runtime_minutes, deferrable=is_deferrable)
    if not candidates:
        raise ValueError(
            f"Job {job_id}: deadline {deadline} is too soon for {runtime_minutes}min runtime starting at {start_bound}"
        )

    # 5. Score slots and apply Hard Constraint 1 (Carbon Budget)
    scored: List[Tuple[datetime, float, float]] = []  # (start, cost_usd, carbon_kg)
    for start in candidates:
        c_intensity = _interpolate_carbon(start, carbon_curve)
        t_price = _interpolate_tariff(start, tariff_curve)
        c_kg = _carbon_kg(energy, c_intensity)
        cost = _cost_usd(energy, t_price)

        # Carbon budget constraint
        if carbon_budget_kg is not None and c_kg > carbon_budget_kg:
            logger.debug("Slot %s filtered by budget constraint: c_kg=%.4f > budget=%.4f", start, c_kg, carbon_budget_kg)
            continue

        # Tuple: (start, cost, carbon)
        scored.append((start, cost, c_kg))

    if not scored:
        # Relax budget if no slot passes, picking lowest cost & carbon
        logger.warning("Job %s: all slots exceed budget — selecting optimal feasible slot", job_id)
        for start in candidates:
            c_intensity = _interpolate_carbon(start, carbon_curve)
            t_price = _interpolate_tariff(start, tariff_curve)
            scored.append((start, _cost_usd(energy, t_price), _carbon_kg(energy, c_intensity)))
        reason = "Budget constraint relaxed — selected optimal cost slot with carbon tiebreaker"
    elif not is_deferrable:
        reason = "Non-deferrable workload scheduled at earliest feasible start window"
    else:
        reason = "Optimal cost slot with carbon tiebreaker within deadline and budget"

    # 6. Optimization Policy:
    # Primary: Minimize electricity cost.
    # Secondary: Tie-breaker with lower carbon emission when costs are equal / within COST_EPSILON.
    # Key sort: (cost rounded to epsilon precision, carbon_kg)
    scored.sort(key=lambda x: (round(x[1] / COST_EPSILON) * COST_EPSILON, x[2]))
    best_start, best_cost, best_carbon = scored[0]

    best_end = best_start + timedelta(minutes=runtime_minutes)
    best_intensity = _interpolate_carbon(best_start, carbon_curve)
    best_tariff_usd = _interpolate_tariff(best_start, tariff_curve)
    best_native_rate = _get_native_rate_at_slot(region_id, plan, best_start, best_tariff_usd)

    # 7. Baseline Scenario: Immediate execution at earliest candidate slot
    baseline_start = candidates[0]
    baseline_end = baseline_start + timedelta(minutes=runtime_minutes)
    baseline_intensity = _interpolate_carbon(baseline_start, carbon_curve)
    baseline_tariff_usd = _interpolate_tariff(baseline_start, tariff_curve)
    baseline_native_rate = _get_native_rate_at_slot(region_id, plan, baseline_start, baseline_tariff_usd)

    # 8. Compute Impact via Baseline & Impact Calculator
    impact = calculate_impact(
        energy_kwh=energy,
        deadline=deadline,
        baseline_start=baseline_start,
        baseline_carbon_intensity=baseline_intensity,
        baseline_price_usd=baseline_tariff_usd,
        baseline_native_rate=baseline_native_rate,
        selected_start=best_start,
        selected_carbon_intensity=best_intensity,
        selected_price_usd=best_tariff_usd,
        selected_native_rate=best_native_rate,
        runtime_minutes=runtime_minutes,
        currency=cfg.currency,
    )

    budget_remaining = (carbon_budget_kg - best_carbon) if carbon_budget_kg else None

    # Determine INR rate for backwards compatibility with tests / API
    inr_to_usd = float(os.environ.get("TARIFF_INR_TO_USD", str(settings.tariff_inr_to_usd)))
    if cfg.currency == "INR":
        tariff_inr = best_native_rate
    elif inr_to_usd > 0:
        tariff_inr = round(best_tariff_usd / inr_to_usd, 4)
    else:
        tariff_inr = None

    logger.info(
        "DECIDE outcome: job=%s | selected=%s | cost=$%.4f (%s %.2f) | carbon=%.4fkg | avoided=%.4fkg (%.1f%%) | SLA=%s",
        job_id,
        best_start.isoformat(),
        best_cost,
        cfg.currency,
        impact.greenshift.native_cost,
        best_carbon,
        impact.carbon_avoided_kg,
        impact.carbon_reduction_pct,
        impact.sla_met,
    )

    return ScheduleDecision(
        job_id=job_id,
        selected_start=best_start,
        selected_end=best_end,
        carbon_intensity=round(best_intensity, 2),
        electricity_cost=round(best_cost, 6),
        carbon_emission=round(best_carbon, 6),
        region_id=region_id,
        tariff_plan=plan,
        currency=cfg.currency,
        native_cost=impact.greenshift.native_cost,
        baseline_native_cost=impact.baseline.native_cost,
        tariff_inr_per_kwh=tariff_inr,
        tariff_category=plan,
        reason=reason,
        budget_remaining=round(budget_remaining, 6) if budget_remaining is not None else None,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        baseline_carbon_emission=impact.baseline.carbon_emission_kg,
        baseline_cost=impact.baseline.electricity_cost_usd,
        carbon_avoided=impact.carbon_avoided_kg,
        cost_difference=impact.cost_avoided_usd,
        carbon_reduction_pct=impact.carbon_reduction_pct,
        cost_reduction_pct=impact.cost_reduction_pct,
        scheduling_delay_hours=impact.scheduling_delay_hours,
        sla_met=impact.sla_met,
    )
