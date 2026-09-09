"""
Contention-Aware Batch Scheduler (Layer 1 Deterministic + Layer 2 ML Advisor).

Schedules batches of workloads with:
1. Urgency-based ordering (Critical rank, non-deferrable first, tightest slack hours).
2. Hard SlotCapacity constraint enforcement per 1-hour window (Layer 1).
3. Graceful spillover to next feasible slot when preferred slot is full.
4. Soft ML Demand Forecaster guidance to gently nudge away from congested slots (Layer 2).
5. Least-loaded slot fallback if all candidate slots reach capacity.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

from sqlalchemy.orm import Session

from app.decide.demand_forecaster import DemandForecaster, get_demand_forecaster
from app.decide.impact_calculator import calculate_impact
from app.decide.scheduler import (
    CandidateRejectionReason,
    _generate_candidate_slots,
    _energy_kwh,
    _carbon_kg,
    _cost_usd,
    _interpolate_carbon,
    _interpolate_tariff,
    _get_native_rate_at_slot,
    CARBON_EPSILON,
    COST_EPSILON,
)
from app.decide.slot_capacity import SlotCapacityRegistry
from app.dispatch.k8s_state_collector import (
    collect_cluster_state,
    _parse_cpu_string,
    _parse_memory_string,
)
from app.ingest.data_sources import get_carbon_data, get_tariff_data
from app.ingest.regional_registry import (
    get_region_config,
    resolve_region_id,
    select_tariff_plan_for_job,
)
from app.shared.config import settings
from app.shared.models import JobORM, ScheduleDecision
from app.shared.utils import utcnow

logger = logging.getLogger("greenshift.batch_scheduler")

CONTENTION_WEIGHT = 0.05  # ML demand penalty weight (max 5% cost uplift)

PRIORITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
}


@dataclass
class BatchCandidate:
    start_time: datetime
    end_time: datetime
    feasible: bool
    rejection_reasons: List[str] = field(default_factory=list)
    carbon_intensity: Optional[float] = None
    carbon_emission_kg: Optional[float] = None
    electricity_cost: Optional[float] = None
    tariff_usd: Optional[float] = None
    demand_pressure: float = 0.0
    effective_cost: Optional[float] = None
    has_capacity: bool = True


def _urgency_key(job: JobORM, now: datetime) -> Tuple[int, int, float, str]:
    """
    Sort key for batch urgency:
    1. Priority level (CRITICAL -> HIGH -> MEDIUM -> LOW)
    2. Non-deferrable first (0) before deferrable (1)
    3. Slack seconds (deadline - earliest_start - runtime) ascending (tighter deadline first)
    4. Deterministic tie-breaker: job_id
    """
    p_rank = PRIORITY_ORDER.get((job.priority or "MEDIUM").upper(), 2)
    non_def_rank = 0 if not job.deferrable else 1

    earliest = job.earliest_start_time or now
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)

    deadline = job.deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    slack_seconds = (deadline - earliest).total_seconds() - (job.runtime_minutes * 60)
    return (p_rank, non_def_rank, slack_seconds, str(job.job_id))


def schedule_batch(
    db: Session,
    jobs: List[JobORM],
    registry: Optional[SlotCapacityRegistry] = None,
    demand_forecaster: Optional[DemandForecaster] = None,
    use_demand_forecast: bool = True,
) -> List[ScheduleDecision]:
    """
    Contention-aware batch scheduling of workloads.

    Args:
        db: SQLAlchemy DB session
        jobs: List of JobORM records to schedule
        registry: Optional SlotCapacityRegistry (defaults to fresh registry initialized from cluster state)
        demand_forecaster: Optional ML forecaster instance (defaults to global singleton)
        use_demand_forecast: Whether to apply ML demand pressure penalties

    Returns:
        List of ScheduleDecision objects matching input jobs
    """
    if not jobs:
        return []

    now = utcnow()
    if registry is None:
        cluster_state = collect_cluster_state()
        registry = SlotCapacityRegistry(default_snapshot=cluster_state)

    if demand_forecaster is None and use_demand_forecast:
        demand_forecaster = get_demand_forecaster()

    ml_active = bool(use_demand_forecast and demand_forecaster and demand_forecaster.is_trained)

    # Sort jobs by urgency ordering
    sorted_jobs = sorted(jobs, key=lambda j: _urgency_key(j, now))

    # Determine batch window bounds across all jobs for regional telemetry pre-fetching
    batch_starts = []
    batch_ends = []
    for j in sorted_jobs:
        sb = j.earliest_start_time or j.submitted_at or now
        if sb.tzinfo is None:
            sb = sb.replace(tzinfo=timezone.utc)
        batch_starts.append(sb)

        dl = j.deadline
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)
        batch_ends.append(dl)

    batch_min_start = min(batch_starts) - timedelta(hours=1)
    batch_max_end = max(batch_ends) + timedelta(hours=2)

    # Caches for telemetry curves (keyed by region and region/plan)
    carbon_cache: Dict[str, Any] = {}
    tariff_cache: Dict[Tuple[str, Optional[str], Optional[str]], Any] = {}

    decisions: List[ScheduleDecision] = []

    for job in sorted_jobs:
        deadline = job.deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        start_bound = job.earliest_start_time or job.submitted_at or now
        if start_bound.tzinfo is None:
            start_bound = start_bound.replace(tzinfo=timezone.utc)

        is_deferrable = True if job.deferrable is None else bool(job.deferrable)

        # Region config and plan
        region_id = resolve_region_id(job.region)
        cfg = get_region_config(region_id)
        plan = getattr(job, "tariff_plan", None) or select_tariff_plan_for_job(
            region_id, job_type=job.job_type, timestamp=start_bound
        )

        # Workload energy
        if job.energy_kwh is not None and job.energy_kwh > 0:
            energy = float(job.energy_kwh)
        else:
            energy = _energy_kwh(job.power_kw, job.runtime_minutes)

        # Workload resources
        cpu_cores = _parse_cpu_string(getattr(job, "cpu_request", "500m"))
        mem_mib = _parse_memory_string(getattr(job, "memory_request", "512Mi"))
        gpu_req = int(getattr(job, "gpu_request", 0) or 0)
        duration_hours = job.runtime_minutes / 60.0

        # Fetch telemetry curves across batch window (single query per region)
        if region_id not in carbon_cache:
            carbon_cache[region_id] = get_carbon_data(region_id, batch_min_start, batch_max_end, db=None)
        carbon_curve = carbon_cache[region_id]

        t_key = (region_id, job.job_type, plan)
        if t_key not in tariff_cache:
            tariff_cache[t_key] = get_tariff_data(region_id, batch_min_start, batch_max_end, job_type=job.job_type, tariff_plan=plan)
        tariff_curve = tariff_cache[t_key]

        # Candidate generation
        candidate_starts = _generate_candidate_slots(start_bound, deadline, job.runtime_minutes, deferrable=is_deferrable)
        if not candidate_starts:
            candidate_starts = [start_bound]

        evaluations: List[BatchCandidate] = []
        for start in candidate_starts:
            reasons: List[str] = []
            end = start + timedelta(minutes=job.runtime_minutes)

            if end > deadline + timedelta(seconds=60):
                reasons.append(CandidateRejectionReason.DEADLINE_VIOLATION)

            # Carbon Telemetry
            c_intensity = _interpolate_carbon(start, carbon_curve)
            if c_intensity is None:
                reasons.append(CandidateRejectionReason.CARBON_DATA_UNAVAILABLE)
                c_kg = None
            else:
                c_kg = _carbon_kg(energy, c_intensity)

            # Tariff Price
            t_price = _interpolate_tariff(start, tariff_curve, region_id=region_id)
            if t_price is None:
                reasons.append(CandidateRejectionReason.COST_DATA_UNAVAILABLE)
                cost = None
            else:
                cost = _cost_usd(energy, t_price)

            # Carbon Budget Check
            if job.carbon_budget_kg is not None and c_kg is not None:
                if c_kg > job.carbon_budget_kg:
                    reasons.append(CandidateRejectionReason.CARBON_BUDGET_EXCEEDED)

            # ML Demand Pressure (Layer 2)
            demand_pressure = 0.0
            effective_cost = cost
            if ml_active and demand_forecaster is not None and cost is not None:
                demand_pressure = demand_forecaster.predict_demand_pressure(start, region_id)
                # Soft contention penalty strictly capped at 5% cost uplift
                effective_cost = cost * (1.0 + CONTENTION_WEIGHT * demand_pressure)

            # Slot Capacity Check (Layer 1)
            fits_capacity = registry.can_fit(region_id, start, duration_hours, cpu_cores, mem_mib, gpu_req)

            cand = BatchCandidate(
                start_time=start,
                end_time=end,
                feasible=(len(reasons) == 0),
                rejection_reasons=reasons,
                carbon_intensity=c_intensity,
                carbon_emission_kg=c_kg,
                electricity_cost=cost,
                tariff_usd=t_price,
                demand_pressure=demand_pressure,
                effective_cost=effective_cost,
                has_capacity=fits_capacity,
            )
            evaluations.append(cand)

        feasible_unconstrained = [c for c in evaluations if c.feasible]
        if not feasible_unconstrained:
            # Fallback: keep job scheduled at earliest start bound rather than dropping
            feasible_unconstrained = evaluations[:1]

        # Preferred slot (unconstrained best based on carbon-first, base cost, start time)
        preferred_sorted = sorted(
            feasible_unconstrained,
            key=lambda c: (
                round((c.carbon_emission_kg or 0.0) / CARBON_EPSILON) * CARBON_EPSILON,
                round((c.electricity_cost or 0.0) / COST_EPSILON) * COST_EPSILON,
                c.start_time,
            )
        )
        preferred_candidate = preferred_sorted[0]
        preferred_start = preferred_candidate.start_time

        # Filter to capacity-feasible candidates
        capacity_feasible = [c for c in feasible_unconstrained if c.has_capacity]

        spilled_from_preferred = False
        if capacity_feasible:
            # Rank capacity-feasible candidates by Carbon-first, effective cost (including ML penalty), start time
            capacity_feasible.sort(
                key=lambda c: (
                    round((c.carbon_emission_kg or 0.0) / CARBON_EPSILON) * CARBON_EPSILON,
                    round((c.effective_cost or 0.0) / COST_EPSILON) * COST_EPSILON,
                    c.start_time,
                )
            )
            chosen = capacity_feasible[0]
            if chosen.start_time != preferred_start:
                spilled_from_preferred = True
        else:
            # Fallback: All candidate slots are at capacity.
            # Select least-loaded slot in window to minimize peak violation.
            spilled_from_preferred = True
            chosen = min(
                feasible_unconstrained,
                key=lambda c: (
                    registry.utilization_at(region_id, c.start_time),
                    round((c.carbon_emission_kg or 0.0) / CARBON_EPSILON) * CARBON_EPSILON,
                    c.start_time,
                )
            )
            logger.warning(
                "Job %s spilled to least-loaded slot %s (util: %.1f%%) due to capacity saturation across all windows",
                job.job_id,
                chosen.start_time.isoformat(),
                registry.utilization_at(region_id, chosen.start_time),
            )

        # Allocate in registry
        registry.allocate(region_id, chosen.start_time, duration_hours, cpu_cores, mem_mib, gpu_req)
        slot_util = registry.utilization_at(region_id, chosen.start_time)

        # Quantitative Impact calculation (vs immediate baseline)
        baseline_start = candidate_starts[0]
        baseline_end = baseline_start + timedelta(minutes=job.runtime_minutes)
        baseline_intensity = _interpolate_carbon(baseline_start, carbon_curve) or chosen.carbon_intensity or 0.0
        baseline_tariff_usd = _interpolate_tariff(baseline_start, tariff_curve, region_id=region_id) or chosen.tariff_usd or 0.0
        baseline_native_rate = _get_native_rate_at_slot(region_id, plan, baseline_start, baseline_tariff_usd)

        chosen_tariff_usd = chosen.tariff_usd if chosen.tariff_usd is not None else 0.0
        chosen_native_rate = _get_native_rate_at_slot(region_id, plan, chosen.start_time, chosen_tariff_usd)

        impact = calculate_impact(
            energy_kwh=energy,
            deadline=deadline,
            baseline_start=baseline_start,
            baseline_carbon_intensity=baseline_intensity,
            baseline_price_usd=baseline_tariff_usd,
            baseline_native_rate=baseline_native_rate,
            selected_start=chosen.start_time,
            selected_carbon_intensity=chosen.carbon_intensity or 0.0,
            selected_price_usd=chosen_tariff_usd,
            selected_native_rate=chosen_native_rate,
            runtime_minutes=job.runtime_minutes,
            currency=cfg.currency if cfg else "USD",
        )

        budget_remaining = None
        if job.carbon_budget_kg is not None and chosen.carbon_emission_kg is not None:
            budget_remaining = round(job.carbon_budget_kg - chosen.carbon_emission_kg, 6)

        # INR rate conversion for backward compatibility
        inr_to_usd = float(os.environ.get("TARIFF_INR_TO_USD", str(settings.tariff_inr_to_usd)))
        if cfg and cfg.currency == "INR":
            tariff_inr = chosen_native_rate
        elif inr_to_usd > 0:
            tariff_inr = round(chosen_tariff_usd / inr_to_usd, 4)
        else:
            tariff_inr = None

        method_str = "batch_contention_aware_ml" if ml_active else "batch_contention_aware"

        if spilled_from_preferred:
            reason = (
                f"Contention-aware batch schedule: Preferred slot {preferred_start.isoformat()} reached "
                f"capacity; job spilled to next optimal feasible slot ({slot_util:.1f}% slot util). "
                f"Carbon: {chosen.carbon_emission_kg:.4f} kg CO2."
            )
        elif not is_deferrable:
            reason = f"Non-deferrable workload allocated at earliest slot ({slot_util:.1f}% slot util)."
        else:
            reason = (
                f"Contention-aware optimal slot selected ({chosen.carbon_emission_kg:.4f} kg CO2, "
                f"${chosen.electricity_cost:.4f}, {slot_util:.1f}% slot util)."
            )

        decision = ScheduleDecision(
            job_id=job.job_id,
            selected_start=chosen.start_time,
            selected_end=chosen.end_time,
            carbon_intensity=round(chosen.carbon_intensity or 0.0, 2),
            electricity_cost=round(chosen.electricity_cost or 0.0, 6),
            carbon_emission=round(chosen.carbon_emission_kg or 0.0, 6),
            region_id=region_id,
            tariff_plan=plan,
            currency=cfg.currency if cfg else "USD",
            native_cost=impact.greenshift.native_cost,
            baseline_native_cost=impact.baseline.native_cost,
            tariff_inr_per_kwh=tariff_inr,
            tariff_category=plan,
            reason=reason,
            budget_remaining=budget_remaining,
            objective="CARBON_FIRST",
            scheduler_objective="CARBON_FIRST",
            candidates_evaluated=len(evaluations),
            feasible_candidates_count=len(feasible_unconstrained),
            rejection_summary={},
            rejection_reasons=[],
            deterministic_ranking=1,
            deterministic_rank=1,
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
            # Contention & ML advisor fields
            scheduling_method=method_str,
            slot_utilization_pct=round(slot_util, 1),
            demand_predicted=round(chosen.demand_pressure, 4),
            spilled_from_preferred=spilled_from_preferred,
            ml_advisor_used=ml_active,
        )
        decisions.append(decision)

    logger.info(
        "Batch scheduled %d jobs | spilled=%d (%.1f%%) | method=%s",
        len(decisions),
        sum(1 for d in decisions if d.spilled_from_preferred),
        (sum(1 for d in decisions if d.spilled_from_preferred) / len(decisions) * 100.0) if decisions else 0.0,
        "batch_contention_aware_ml" if ml_active else "batch_contention_aware",
    )
    return decisions
