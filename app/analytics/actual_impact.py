"""
Estimated vs. Actual Impact Tracker for GreenShift.
Re-evaluates carbon and electricity tariff data across the real execution window
of completed Kubernetes workloads and analyzes variance against pre-dispatch estimates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ingest.data_sources import get_carbon_data, get_tariff_data
from app.shared.models import JobORM, KubernetesExecutionORM, ScheduleDecisionORM, JobStatus

logger = logging.getLogger(__name__)


@dataclass
class ActualImpactResult:
    job_id: str

    # Estimated (from scheduler)
    estimated_carbon_emission_kg: float
    estimated_cost_usd: float
    estimated_carbon_intensity: float

    # Actual (from real execution window)
    actual_carbon_emission_kg: float
    actual_cost_usd: float
    actual_carbon_intensity: float

    # Variance
    carbon_estimation_error_pct: float   # (actual - estimated) / estimated * 100
    cost_estimation_error_pct: float

    # Was the optimization still beneficial vs baseline?
    actual_vs_baseline_carbon_saved_kg: float
    actual_vs_baseline_carbon_reduction_pct: float
    actual_vs_baseline_cost_saved_usd: float

    estimation_quality: str  # "ACCURATE" (|error| < 5%), "ACCEPTABLE" (< 15%), "POOR" (>= 15%)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FleetActualImpactSummary:
    total_completed_jobs_analyzed: int = 0
    avg_carbon_estimation_error_pct: float = 0.0
    avg_cost_estimation_error_pct: float = 0.0
    jobs_where_optimization_still_beneficial: int = 0
    jobs_where_optimization_backfired: int = 0
    estimation_quality_distribution: Dict[str, int] = field(
        default_factory=lambda: {"ACCURATE": 0, "ACCEPTABLE": 0, "POOR": 0}
    )
    results: List[ActualImpactResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_actual_impact(db: Session, job_id: str) -> Optional[ActualImpactResult]:
    """
    For a completed or executing Kubernetes job with actual_start recorded,
    re-query carbon intensity and tariff at the actual execution window
    and compare against the estimated impact.
    """
    job = db.query(JobORM).filter_by(job_id=job_id).first()
    if not job or not job.schedule_decision:
        return None

    exec_record = db.query(KubernetesExecutionORM).filter_by(job_id=job_id).first()
    if not exec_record or not exec_record.actual_start:
        return None

    sd: ScheduleDecisionORM = job.schedule_decision
    actual_start = exec_record.actual_start
    if actual_start.tzinfo is None:
        actual_start = actual_start.replace(tzinfo=timezone.utc)

    actual_end = exec_record.actual_end
    if not actual_end:
        actual_end = actual_start + timedelta(minutes=job.runtime_minutes or 30)
    elif actual_end.tzinfo is None:
        actual_end = actual_end.replace(tzinfo=timezone.utc)

    # 1. Fetch carbon intensity at actual window
    region = str(sd.region_id or job.region or "IN-TG")
    energy_kwh = float(job.energy_kwh or (job.power_kw * (job.runtime_minutes / 60.0) if job.power_kw else 0.1))

    try:
        c_points = get_carbon_data(region, actual_start, actual_end, db=db)
        actual_carbon_intensity = (
            sum(p.carbon_intensity for p in c_points) / len(c_points)
        ) if c_points else float(sd.carbon_intensity or 350.0)
    except Exception as exc:
        logger.warning("Failed to fetch actual carbon data for %s: %s", job_id, exc)
        actual_carbon_intensity = float(sd.carbon_intensity or 350.0)

    actual_carbon_emission = (actual_carbon_intensity * energy_kwh) / 1000.0

    # 2. Fetch tariff at actual window
    try:
        t_points = get_tariff_data(
            region=region,
            start_time=actual_start,
            end_time=actual_end,
            job_type=job.job_type,
            tariff_plan=sd.tariff_plan,
        )
        actual_price_usd = (
            sum(p.price_per_kwh for p in t_points) / len(t_points)
        ) if t_points else (float(sd.electricity_cost or 0.05) / (energy_kwh if energy_kwh > 0 else 1.0))
    except Exception as exc:
        logger.warning("Failed to fetch actual tariff data for %s: %s", job_id, exc)
        actual_price_usd = float(sd.electricity_cost or 0.05) / (energy_kwh if energy_kwh > 0 else 1.0)

    actual_cost_usd = actual_price_usd * energy_kwh

    # 3. Estimated values
    est_c_emission = float(sd.carbon_emission or 0.0)
    est_cost_usd = float(sd.electricity_cost or 0.0)
    est_c_intensity = float(sd.carbon_intensity or 0.0)

    # 4. Variance calculation
    if est_c_emission > 0:
        carbon_err_pct = ((actual_carbon_emission - est_c_emission) / est_c_emission) * 100.0
    else:
        carbon_err_pct = 0.0

    if est_cost_usd > 0:
        cost_err_pct = ((actual_cost_usd - est_cost_usd) / est_cost_usd) * 100.0
    else:
        cost_err_pct = 0.0

    abs_err = abs(carbon_err_pct)
    if abs_err < 5.0:
        estimation_quality = "ACCURATE"
    elif abs_err < 15.0:
        estimation_quality = "ACCEPTABLE"
    else:
        estimation_quality = "POOR"

    # 5. Baseline comparison
    baseline_carbon = float(sd.baseline_carbon_emission if sd.baseline_carbon_emission is not None else est_c_emission)
    baseline_cost = float(sd.baseline_cost if sd.baseline_cost is not None else est_cost_usd)

    act_saved_carbon = baseline_carbon - actual_carbon_emission
    act_saved_cost = baseline_cost - actual_cost_usd
    act_red_pct = ((act_saved_carbon / baseline_carbon) * 100.0) if baseline_carbon > 0 else 0.0

    return ActualImpactResult(
        job_id=job_id,
        estimated_carbon_emission_kg=round(est_c_emission, 6),
        estimated_cost_usd=round(est_cost_usd, 6),
        estimated_carbon_intensity=round(est_c_intensity, 2),
        actual_carbon_emission_kg=round(actual_carbon_emission, 6),
        actual_cost_usd=round(actual_cost_usd, 6),
        actual_carbon_intensity=round(actual_carbon_intensity, 2),
        carbon_estimation_error_pct=round(carbon_err_pct, 2),
        cost_estimation_error_pct=round(cost_err_pct, 2),
        actual_vs_baseline_carbon_saved_kg=round(act_saved_carbon, 6),
        actual_vs_baseline_carbon_reduction_pct=round(act_red_pct, 2),
        actual_vs_baseline_cost_saved_usd=round(act_saved_cost, 6),
        estimation_quality=estimation_quality,
    )


def compute_fleet_actual_impact(
    db: Session, tenant_id: Optional[str] = None, team_id: Optional[str] = None,
) -> FleetActualImpactSummary:
    """Compute actual vs estimated across all jobs with recorded actual execution
    times. `tenant_id`/`team_id` scope the fleet to one company/team — the
    caller (see app.api.routers.impact) is responsible for deriving these
    from the authenticated identity, never from unauthenticated client input."""
    query = (
        db.query(KubernetesExecutionORM)
        .join(JobORM, JobORM.job_id == KubernetesExecutionORM.job_id)
        .filter(KubernetesExecutionORM.actual_start.isnot(None))
    )
    if tenant_id:
        query = query.filter(JobORM.tenant_id == tenant_id)
    if team_id:
        query = query.filter(JobORM.team_id == team_id)
    executions = query.all()

    results: List[ActualImpactResult] = []
    quality_dist = {"ACCURATE": 0, "ACCEPTABLE": 0, "POOR": 0}
    beneficial_count = 0
    backfired_count = 0

    carbon_errors: List[float] = []
    cost_errors: List[float] = []

    for ex in executions:
        res = compute_actual_impact(db, ex.job_id)
        if res:
            results.append(res)
            carbon_errors.append(res.carbon_estimation_error_pct)
            cost_errors.append(res.cost_estimation_error_pct)
            quality_dist[res.estimation_quality] = quality_dist.get(res.estimation_quality, 0) + 1

            if res.actual_vs_baseline_carbon_saved_kg >= 0:
                beneficial_count += 1
            else:
                backfired_count += 1

    total = len(results)
    avg_carbon_err = round(sum(carbon_errors) / total, 2) if total else 0.0
    avg_cost_err = round(sum(cost_errors) / total, 2) if total else 0.0

    return FleetActualImpactSummary(
        total_completed_jobs_analyzed=total,
        avg_carbon_estimation_error_pct=avg_carbon_err,
        avg_cost_estimation_error_pct=avg_cost_err,
        jobs_where_optimization_still_beneficial=beneficial_count,
        jobs_where_optimization_backfired=backfired_count,
        estimation_quality_distribution=quality_dist,
        results=results,
    )
