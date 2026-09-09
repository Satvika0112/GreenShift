"""
Agent 2 — DECIDE
Carbon-First, Cost-Aware and Constraint-First Scheduler.

DECIDE POLICY:
GreenShift uses deterministic constraint-first lexicographic optimization.

HARD CONSTRAINTS (Checked First):
1. Deadline (start + runtime <= deadline)
2. SLA requirements (completion on or before deadline)
3. Region eligibility (supported regional plan and grid zone)
4. CPU feasibility (current cluster free CPU >= requested CPU)
5. RAM feasibility (current cluster free RAM >= requested RAM)
6. GPU feasibility (current cluster free GPU >= requested GPU)
7. Carbon budget ONLY when explicitly provided by the user (carbon_emission <= carbon_budget_kg)
8. Trustworthy carbon telemetry availability

OPTIMIZATION RANKING (Lexicographic Order):
1. Minimize total workload carbon emissions (kg CO2)
2. Minimize electricity cost (USD)
3. Earliest start time (deterministic final tie-breaker)

Ranking tuple: (carbon_emission_kg, electricity_cost, selected_start)

No arbitrary weights. No weighted CCS score. No silent carbon budget relaxation.

NOTE ON RESOURCE FEASIBILITY:
Resource feasibility is evaluated against current Kubernetes cluster capacity.
Future capacity forecasting is outside the current MVP scope.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

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
from app.shared.metrics import (
    record_scheduler_request,
    record_scheduler_success,
    record_scheduler_infeasible,
)
from app.shared.models import (
    CarbonDataPoint,
    ScheduleDecision,
    TariffDataPoint,
)

logger = logging.getLogger(__name__)

SLOT_RESOLUTION_MINUTES = 60
CARBON_EPSILON = 1e-6  # Precision threshold for carbon emissions comparison
COST_EPSILON = 1e-6    # Precision threshold for electricity cost comparison


class CandidateRejectionReason:
    CARBON_THRESHOLD = "CARBON_THRESHOLD"
    CARBON_BUDGET_EXCEEDED = "CARBON_THRESHOLD"
    DEADLINE_VIOLATION = "SLA_VIOLATION"
    SLA_VIOLATION = "SLA_VIOLATION"
    INSUFFICIENT_CPU = "INSUFFICIENT_CPU"
    INSUFFICIENT_RAM = "INSUFFICIENT_RAM"
    INSUFFICIENT_MEMORY = "INSUFFICIENT_RAM"
    GPU_UNAVAILABLE = "GPU_UNAVAILABLE"
    INSUFFICIENT_GPU = "GPU_UNAVAILABLE"
    POLICY_RESTRICTION = "POLICY_RESTRICTION"
    REGION_INELIGIBLE = "POLICY_RESTRICTION"
    CARBON_DATA_UNAVAILABLE = "CARBON_DATA_UNAVAILABLE"
    COST_DATA_UNAVAILABLE = "COST_DATA_UNAVAILABLE"
    COST_THRESHOLD = "COST_THRESHOLD"


@dataclass
class CandidateEvaluation:
    start_time: datetime
    end_time: datetime
    feasible: bool
    rejection_reasons: List[str] = field(default_factory=list)
    carbon_intensity: Optional[float] = None
    carbon_emission_kg: Optional[float] = None
    electricity_cost: Optional[float] = None
    tariff_usd: Optional[float] = None
    native_rate: Optional[float] = None
    is_fallback_carbon: bool = False


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
) -> Optional[float]:
    """
    Return the carbon intensity (gCO2/kWh) for a given timestamp if trustworthy data exists.
    Returns None if carbon telemetry is missing or untrustworthy.
    """
    if not carbon_curve:
        return None

    best = min(carbon_curve, key=lambda p: abs((p.timestamp - timestamp).total_seconds()))
    diff = abs((best.timestamp - timestamp).total_seconds())

    # If the nearest data point is more than 2 hours away and not explicitly tagged as a fallback
    if diff > 7200 and not getattr(best, "is_fallback", False):
        logger.warning(
            "No carbon data near %s (nearest: %s, diff: %.0fs) — untrustworthy for optimization",
            timestamp,
            best.timestamp,
            diff,
        )
        return None

    return best.carbon_gco2_kwh


def _interpolate_tariff(
    timestamp: datetime,
    tariff_curve: List[TariffDataPoint],
    region_id: Optional[str] = None,
) -> Optional[float]:
    """Return the tariff ($/kWh) for a given timestamp."""
    if tariff_curve:
        best = min(tariff_curve, key=lambda p: abs((p.timestamp - timestamp).total_seconds()))
        diff = abs((best.timestamp - timestamp).total_seconds())
        if diff <= 7200:
            return best.price_per_kwh

    # Fallback via regional tariff template / service if available
    if region_id:
        try:
            cfg = get_region_config(region_id)
            fx = get_fx_rate_to_usd(cfg.currency)
            template = load_raw_tariff_template(region=region_id)
            if template:
                _, local_hour = utc_to_local(timestamp, region_id)
                row = template.get(local_hour)
                if row and "rate" in row:
                    return float(row["rate"]) * fx
        except Exception as exc:
            logger.debug("Failed tariff fallback resolution for %s: %s", region_id, exc)

    return None


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

    # Non-deferrable workloads: only evaluate the earliest feasible start slot
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
    Core deterministic constraint-first, carbon-first scheduling engine.

    Lexicographic optimization ranking:
      1. Hard constraints (Deadline, SLA, Region, CPU/RAM/GPU, Carbon Budget, Carbon Telemetry)
      2. Minimum total workload carbon emissions (kg CO2)
      3. Minimum electricity cost (USD)
      4. Earliest start time (deterministic final tie-breaker)
    """
    import time
    t0 = time.perf_counter()
    record_scheduler_request()
    try:
        decision = _execute_schedule_job(
            job_id=job_id,
            team_id=team_id,
            deadline=deadline,
            runtime_minutes=runtime_minutes,
            power_kw=power_kw,
            region=region,
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            carbon_budget_kg=carbon_budget_kg,
            energy_kwh=energy_kwh,
            earliest_start_time=earliest_start_time,
            deferrable=deferrable,
            job_type=job_type,
            tariff_plan=tariff_plan,
            cpu_request=cpu_request,
            memory_request=memory_request,
            gpu_request=gpu_request,
        )
        record_scheduler_success(time.perf_counter() - t0)
        return decision
    except Exception as exc:
        record_scheduler_infeasible(time.perf_counter() - t0)
        raise


def _execute_schedule_job(
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
    now = datetime.now(timezone.utc)

    # 1. Hard Constraint: Region Eligibility
    region_eligible = True
    try:
        region_id = resolve_region_id(region)
        cfg = get_region_config(region_id)
        plan = tariff_plan or select_tariff_plan_for_job(
            region_id, job_type=job_type, timestamp=earliest_start_time or now
        )
    except Exception as exc:
        region_eligible = False
        region_id = region
        cfg = None
        plan = tariff_plan or "default"

    # 2. Calculate Workload Energy
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
        start_bound = earliest_start_time

    is_deferrable = True if deferrable is None else bool(deferrable)

    logger.info(
        "DECIDE carbon-first scheduling job %s | region=%s | plan=%s | runtime=%dm | energy=%.4fkWh | bound=%s | deadline=%s",
        job_id, region_id, plan, runtime_minutes, energy, start_bound.isoformat(), deadline.isoformat(),
    )

    # 3. Hard Constraints: Cluster Resource Feasibility (CPU, RAM, GPU)
    # Resource feasibility is evaluated against current Kubernetes cluster capacity.
    # Future capacity forecasting is outside the current MVP scope.
    cluster_state = collect_cluster_state()
    cpu_cores = _parse_cpu_string(cpu_request)
    mem_mib = _parse_memory_string(memory_request)
    is_resource_ok, resource_msg = cluster_state.is_resource_feasible(
        cpu_request_cores=cpu_cores,
        memory_request_mib=mem_mib,
        gpu_request=gpu_request,
    )

    # 4. Hard Constraints: Generate candidate slots within deadline
    candidates = _generate_candidate_slots(start_bound, deadline, runtime_minutes, deferrable=is_deferrable)
    if not candidates:
        raise ValueError(
            f"Job {job_id}: deadline {deadline} is too soon for {runtime_minutes}min runtime starting at {start_bound}"
        )

    # 5. Evaluate all candidate slots against hard constraints
    evaluations: List[CandidateEvaluation] = []
    feasible_candidates: List[CandidateEvaluation] = []

    for start in candidates:
        reasons: List[str] = []
        end = start + timedelta(minutes=runtime_minutes)

        # A. Deadline & SLA constraint
        if end > deadline:
            reasons.append(CandidateRejectionReason.DEADLINE_VIOLATION)
            reasons.append(CandidateRejectionReason.SLA_VIOLATION)

        # B. Region Eligibility Constraint
        if not region_eligible:
            reasons.append(CandidateRejectionReason.REGION_INELIGIBLE)

        # C. Cluster Resource Constraints (Current Capacity)
        if not is_resource_ok:
            if cluster_state.allocatable_cpu_cores is not None and cluster_state.free_cpu_cores < cpu_cores:
                reasons.append(CandidateRejectionReason.INSUFFICIENT_CPU)
            if cluster_state.allocatable_memory_mib is not None and cluster_state.free_memory_mib < mem_mib:
                reasons.append(CandidateRejectionReason.INSUFFICIENT_RAM)
            if gpu_request > 0 and cluster_state.free_gpus < gpu_request:
                reasons.append(CandidateRejectionReason.INSUFFICIENT_GPU)
            if not reasons:
                reasons.append(f"RESOURCE_UNAVAILABLE: {resource_msg}")

        # D. Carbon Telemetry Availability
        c_intensity = _interpolate_carbon(start, carbon_curve)
        if c_intensity is None:
            reasons.append(CandidateRejectionReason.CARBON_DATA_UNAVAILABLE)
            c_kg = None
        else:
            c_kg = _carbon_kg(energy, c_intensity)

        # E. Electricity Tariff Price Availability
        t_price = _interpolate_tariff(start, tariff_curve, region_id=region_id)
        if t_price is None:
            reasons.append(CandidateRejectionReason.COST_DATA_UNAVAILABLE)
            cost = None
        else:
            cost = _cost_usd(energy, t_price)

        # F. Strict Carbon Budget Hard Constraint (No relaxation)
        if carbon_budget_kg is not None and c_kg is not None:
            if c_kg > carbon_budget_kg:
                reasons.append(CandidateRejectionReason.CARBON_BUDGET_EXCEEDED)

        cand_eval = CandidateEvaluation(
            start_time=start,
            end_time=end,
            feasible=(len(reasons) == 0),
            rejection_reasons=reasons,
            carbon_intensity=c_intensity,
            carbon_emission_kg=c_kg,
            electricity_cost=cost,
            tariff_usd=t_price,
        )
        evaluations.append(cand_eval)
        if cand_eval.feasible:
            feasible_candidates.append(cand_eval)

    # 6. Infeasibility Handling (Never silently relax hard constraints)
    if not feasible_candidates:
        # Check specific root causes for clean, actionable error messages:
        if carbon_budget_kg is not None and all(
            CandidateRejectionReason.CARBON_BUDGET_EXCEEDED in e.rejection_reasons
            for e in evaluations
            if CandidateRejectionReason.CARBON_DATA_UNAVAILABLE not in e.rejection_reasons
        ):
            raise ValueError(
                f"Job {job_id}: No execution window satisfies the specified carbon budget of {carbon_budget_kg} kg CO2 within deadline {deadline}."
            )

        if all(CandidateRejectionReason.CARBON_DATA_UNAVAILABLE in e.rejection_reasons for e in evaluations):
            raise ValueError(
                f"Job {job_id}: Carbon data is unavailable for all candidate execution windows within deadline {deadline}."
            )

        if not is_resource_ok:
            raise ValueError(
                f"Job {job_id}: Insufficient cluster capacity for requested resources ({resource_msg})."
            )

        all_reasons = sorted(set(r for e in evaluations for r in e.rejection_reasons))
        raise ValueError(
            f"Job {job_id}: No feasible execution window found within deadline {deadline}. Rejection reasons: {', '.join(all_reasons)}"
        )

    # 7. Lexicographic Ranking Policy (CARBON-FIRST):
    # Primary:    Minimize total workload carbon emissions (kg CO2)
    # Secondary:  Minimize electricity cost ($ USD)
    # Tie-breaker: Earliest start time (datetime)
    feasible_candidates.sort(
        key=lambda c: (
            round((c.carbon_emission_kg or 0.0) / CARBON_EPSILON) * CARBON_EPSILON,
            round((c.electricity_cost or 0.0) / COST_EPSILON) * COST_EPSILON,
            c.start_time,
        )
    )
    best = feasible_candidates[0]

    best_start = best.start_time
    best_end = best.end_time
    best_intensity = best.carbon_intensity if best.carbon_intensity is not None else 0.0
    best_carbon = best.carbon_emission_kg if best.carbon_emission_kg is not None else 0.0
    best_cost = best.electricity_cost if best.electricity_cost is not None else 0.0
    best_tariff_usd = best.tariff_usd if best.tariff_usd is not None else 0.0
    best_native_rate = _get_native_rate_at_slot(region_id, plan, best_start, best_tariff_usd)

    # Build candidates explainability array
    candidates_list = []
    for rank_idx, cand in enumerate(feasible_candidates, start=1):
        candidates_list.append({
            "slot_start": cand.start_time.isoformat(),
            "slot_end": cand.end_time.isoformat(),
            "carbon_intensity": round(cand.carbon_intensity or 0.0, 2),
            "carbon_emission": round(cand.carbon_emission_kg or 0.0, 6),
            "electricity_cost": round(cand.electricity_cost or 0.0, 6),
            "tariff_rate": round(cand.tariff_usd or 0.0, 6),
            "feasible": True,
            "rank": rank_idx,
            "score": round(1.0 / (1.0 + (cand.carbon_emission_kg or 0.0)), 4),
        })

    # Build rejected candidates explainability array
    rejected_candidates_list = []
    for cand in evaluations:
        if not cand.feasible:
            rejected_candidates_list.append({
                "slot_start": cand.start_time.isoformat(),
                "slot_end": cand.end_time.isoformat(),
                "feasible": False,
                "rejection_reasons": cand.rejection_reasons,
                "primary_rejection_reason": cand.rejection_reasons[0] if cand.rejection_reasons else "CONSTRAINT_VIOLATION",
                "carbon_intensity": round(cand.carbon_intensity or 0.0, 2) if cand.carbon_intensity is not None else None,
                "carbon_emission": round(cand.carbon_emission_kg or 0.0, 6) if cand.carbon_emission_kg is not None else None,
                "electricity_cost": round(cand.electricity_cost or 0.0, 6) if cand.electricity_cost is not None else None,
            })

    # Recommended candidate dictionary
    recommended_candidate = {
        "slot_start": best_start.isoformat(),
        "slot_end": best_end.isoformat(),
        "carbon_intensity": round(best_intensity, 2),
        "carbon_emission": round(best_carbon, 6),
        "electricity_cost": round(best_cost, 6),
        "rank": 1,
        "score": round(1.0 / (1.0 + best_carbon), 4),
        "reason": "Optimal carbon-first window meeting all SLA and resource constraints",
    }

    # 8. Decision Explainability Summary
    candidates_evaluated = len(evaluations)
    feasible_candidates_count = len(feasible_candidates)
    rejection_summary: Dict[str, int] = {}
    for ev in evaluations:
        for r_code in ev.rejection_reasons:
            rejection_summary[r_code] = rejection_summary.get(r_code, 0) + 1
    rejection_reasons = sorted(list(rejection_summary.keys()))

    scheduler_objective = "CARBON_FIRST"
    deterministic_ranking = 1

    if not is_deferrable:
        reason = (
            f"Non-deferrable workload scheduled at earliest feasible start window "
            f"(Carbon: {best_carbon:.4f} kg CO2, Cost: ${best_cost:.4f})"
        )
    else:
        reason = (
            f"Lowest-carbon feasible window ({best_carbon:.4f} kg CO2). "
            f"Electricity cost (${best_cost:.4f}) was used as secondary tie-breaker, "
            f"and earliest start time ({best_start.isoformat()}) as deterministic final tie-breaker."
        )

    # 9. Baseline Scenario: Immediate execution at earliest candidate slot
    baseline_start = candidates[0]
    baseline_end = baseline_start + timedelta(minutes=runtime_minutes)
    baseline_intensity = _interpolate_carbon(baseline_start, carbon_curve)
    if baseline_intensity is None:
        baseline_intensity = best_intensity
    baseline_tariff_usd = _interpolate_tariff(baseline_start, tariff_curve, region_id=region_id)
    if baseline_tariff_usd is None:
        baseline_tariff_usd = best_tariff_usd
    baseline_native_rate = _get_native_rate_at_slot(region_id, plan, baseline_start, baseline_tariff_usd)

    # 10. Compute Quantitative Impact via Baseline vs GreenShift Impact Calculator
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
        currency=cfg.currency if cfg else "USD",
    )

    budget_remaining = (carbon_budget_kg - best_carbon) if carbon_budget_kg is not None else None

    # Determine INR rate for backwards compatibility
    inr_to_usd = float(os.environ.get("TARIFF_INR_TO_USD", str(settings.tariff_inr_to_usd)))
    if cfg and cfg.currency == "INR":
        tariff_inr = best_native_rate
    elif inr_to_usd > 0:
        tariff_inr = round(best_tariff_usd / inr_to_usd, 4)
    else:
        tariff_inr = None

    logger.info(
        "DECIDE outcome: job=%s | selected=%s | carbon=%.4fkg | cost=$%.4f (%s %.2f) | avoided=%.4fkg (%.1f%%) | SLA=%s | evaluated=%d | feasible=%d",
        job_id,
        best_start.isoformat(),
        best_carbon,
        best_cost,
        cfg.currency if cfg else "USD",
        impact.greenshift.native_cost,
        impact.carbon_avoided_kg,
        impact.carbon_reduction_pct,
        impact.sla_met,
        candidates_evaluated,
        feasible_candidates_count,
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
        currency=cfg.currency if cfg else "USD",
        native_cost=impact.greenshift.native_cost,
        baseline_native_cost=impact.baseline.native_cost,
        tariff_inr_per_kwh=tariff_inr,
        tariff_category=plan,
        reason=reason,
        budget_remaining=round(budget_remaining, 6) if budget_remaining is not None else None,
        objective=scheduler_objective,
        scheduler_objective=scheduler_objective,
        candidates_evaluated=candidates_evaluated,
        feasible_candidates_count=feasible_candidates_count,
        rejection_summary=rejection_summary,
        rejection_reasons=rejection_reasons,
        deterministic_ranking=deterministic_ranking,
        deterministic_rank=deterministic_ranking,
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
        candidates=candidates_list,
        rejected_candidates=rejected_candidates_list,
        recommended_candidate=recommended_candidate,
    )
