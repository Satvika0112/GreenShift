"""
Fleet Impact Analytics Engine for GreenShift.
Computes comprehensive carbon, cost, SLA, and distribution analytics
across all scheduled workloads.
"""

from __future__ import annotations

import logging
import os
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.shared.models import JobORM, ScheduleDecisionORM
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)


@dataclass
class RegionImpactSummary:
    job_count: int = 0
    total_carbon_avoided_kg: float = 0.0
    avg_carbon_reduction_pct: float = 0.0
    total_cost_saved_usd: float = 0.0
    total_cost_saved_inr: float = 0.0
    sla_compliance_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TeamImpactSummary:
    job_count: int = 0
    total_carbon_avoided_kg: float = 0.0
    avg_carbon_reduction_pct: float = 0.0
    total_cost_saved_usd: float = 0.0
    total_cost_saved_inr: float = 0.0
    sla_compliance_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JobTypeImpactSummary:
    job_count: int = 0
    total_carbon_avoided_kg: float = 0.0
    avg_carbon_reduction_pct: float = 0.0
    total_cost_saved_usd: float = 0.0
    total_cost_saved_inr: float = 0.0
    sla_compliance_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FleetImpactReport:
    # ── Headline metrics ──
    total_jobs_analyzed: int = 0
    total_jobs_with_decisions: int = 0

    total_energy_kwh: float = 0.0

    total_baseline_carbon_kg: float = 0.0
    total_greenshift_carbon_kg: float = 0.0
    total_carbon_avoided_kg: float = 0.0
    avg_carbon_reduction_pct: float = 0.0       # MEAN of per-job carbon_reduction_pct
    median_carbon_reduction_pct: float = 0.0
    p90_carbon_reduction_pct: float = 0.0       # 90th percentile

    total_baseline_cost_usd: float = 0.0
    total_greenshift_cost_usd: float = 0.0
    total_cost_saved_usd: float = 0.0
    avg_cost_reduction_pct: float = 0.0
    median_cost_reduction_pct: float = 0.0

    total_baseline_cost_inr: float = 0.0         # Native INR totals
    total_greenshift_cost_inr: float = 0.0
    total_cost_saved_inr: float = 0.0

    avg_scheduling_delay_hours: float = 0.0
    sla_met_count: int = 0
    sla_miss_count: int = 0
    sla_compliance_pct: float = 0.0

    jobs_with_positive_carbon_savings: int = 0   # How many jobs ACTUALLY saved carbon
    jobs_with_negative_carbon_savings: int = 0   # Cost-optimized but carbon-worse
    jobs_with_zero_impact: int = 0

    # ── Regional breakdown ──
    by_region: Dict[str, RegionImpactSummary] = field(default_factory=dict)

    # ── Per-team breakdown ──
    by_team: Dict[str, TeamImpactSummary] = field(default_factory=dict)

    # ── Per job-type breakdown ──
    by_job_type: Dict[str, JobTypeImpactSummary] = field(default_factory=dict)

    # ── Distribution data (for charts) ──
    carbon_reduction_distribution: List[float] = field(default_factory=list)
    cost_reduction_distribution: List[float] = field(default_factory=list)
    delay_hours_distribution: List[float] = field(default_factory=list)

    # ── Time-of-day analysis ──
    baseline_hour_distribution: Dict[int, int] = field(default_factory=lambda: {h: 0 for h in range(24)})
    greenshift_hour_distribution: Dict[int, int] = field(default_factory=lambda: {h: 0 for h in range(24)})

    # ── Metadata ──
    generated_at: str = ""
    experiment_id: Optional[str] = None
    filters_applied: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def _calculate_p90(values: List[float]) -> float:
    if not values:
        return 0.0
    try:
        import numpy as np
        return float(np.percentile(values, 90))
    except Exception:
        sorted_vals = sorted(values)
        idx = int(round(0.9 * (len(sorted_vals) - 1)))
        return float(sorted_vals[idx])


def compute_fleet_impact(
    db: Session,
    team_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    region_id: Optional[str] = None,
    job_type: Optional[str] = None,
    experiment_id: Optional[str] = None,
) -> FleetImpactReport:
    """
    Compute comprehensive fleet impact metrics from ScheduleDecisionORM and JobORM.
    Handles filters, null values, currency conversion, and distribution analysis.
    """
    filters_applied: Dict[str, str] = {}
    if tenant_id:
        filters_applied["tenant_id"] = tenant_id
    if team_id:
        filters_applied["team_id"] = team_id
    if region_id:
        filters_applied["region_id"] = region_id
    if job_type:
        filters_applied["job_type"] = job_type

    query = db.query(ScheduleDecisionORM, JobORM).join(JobORM, ScheduleDecisionORM.job_id == JobORM.job_id)

    if tenant_id:
        query = query.filter(JobORM.tenant_id == tenant_id)
    if team_id:
        query = query.filter(JobORM.team_id == team_id)
    if region_id:
        query = query.filter(
            (ScheduleDecisionORM.region_id == region_id) | (JobORM.region == region_id)
        )
    if job_type:
        query = query.filter(JobORM.job_type == job_type)

    rows = query.all()

    # Total jobs query count respecting filters
    job_query = db.query(JobORM)
    if tenant_id:
        job_query = job_query.filter(JobORM.tenant_id == tenant_id)
    if team_id:
        job_query = job_query.filter(JobORM.team_id == team_id)
    if region_id:
        job_query = job_query.filter(JobORM.region == region_id)
    if job_type:
        job_query = job_query.filter(JobORM.job_type == job_type)
    total_jobs_analyzed = job_query.count()

    generated_at_iso = datetime.now(timezone.utc).isoformat()

    if not rows:
        return FleetImpactReport(
            total_jobs_analyzed=total_jobs_analyzed,
            total_jobs_with_decisions=0,
            generated_at=generated_at_iso,
            experiment_id=experiment_id,
            filters_applied=filters_applied,
        )

    inr_to_usd = float(os.environ.get("TARIFF_INR_TO_USD", "0.012"))
    if inr_to_usd <= 0:
        inr_to_usd = 0.012

    total_energy_kwh = 0.0
    total_baseline_carbon_kg = 0.0
    total_greenshift_carbon_kg = 0.0
    total_carbon_avoided_kg = 0.0

    total_baseline_cost_usd = 0.0
    total_greenshift_cost_usd = 0.0
    total_cost_saved_usd = 0.0

    total_baseline_cost_inr = 0.0
    total_greenshift_cost_inr = 0.0
    total_cost_saved_inr = 0.0

    total_delay_hours = 0.0
    sla_met_count = 0
    sla_miss_count = 0

    jobs_positive_carbon = 0
    jobs_negative_carbon = 0
    jobs_zero_impact = 0

    carbon_reductions: List[float] = []
    cost_reductions: List[float] = []
    delays: List[float] = []

    baseline_hours: Dict[int, int] = {h: 0 for h in range(24)}
    greenshift_hours: Dict[int, int] = {h: 0 for h in range(24)}

    # Group aggregators: key -> dict of lists/sums
    region_groups: Dict[str, Dict[str, Any]] = {}
    team_groups: Dict[str, Dict[str, Any]] = {}
    job_type_groups: Dict[str, Dict[str, Any]] = {}

    for sd, job in rows:
        energy = float(job.energy_kwh or 0.0)
        total_energy_kwh += energy

        # Carbon metrics
        b_carbon = float(sd.baseline_carbon_emission if sd.baseline_carbon_emission is not None else (sd.carbon_emission or 0.0))
        gs_carbon = float(sd.carbon_emission or 0.0)
        c_avoided = float(sd.carbon_avoided if sd.carbon_avoided is not None else (b_carbon - gs_carbon))

        total_baseline_carbon_kg += b_carbon
        total_greenshift_carbon_kg += gs_carbon
        total_carbon_avoided_kg += c_avoided

        c_red_pct = float(sd.carbon_reduction_pct if sd.carbon_reduction_pct is not None else ((c_avoided / b_carbon * 100.0) if b_carbon > 0 else 0.0))
        carbon_reductions.append(round(c_red_pct, 4))

        if c_avoided > 1e-6:
            jobs_positive_carbon += 1
        elif c_avoided < -1e-6:
            jobs_negative_carbon += 1
        else:
            jobs_zero_impact += 1

        # Cost metrics (USD)
        b_cost = float(sd.baseline_cost if sd.baseline_cost is not None else (sd.electricity_cost or 0.0))
        gs_cost = float(sd.electricity_cost or 0.0)
        cost_diff = float(sd.cost_difference if sd.cost_difference is not None else (b_cost - gs_cost))

        total_baseline_cost_usd += b_cost
        total_greenshift_cost_usd += gs_cost
        total_cost_saved_usd += cost_diff

        cost_red_pct = float(sd.cost_reduction_pct if sd.cost_reduction_pct is not None else ((cost_diff / b_cost * 100.0) if b_cost > 0 else 0.0))
        cost_reductions.append(round(cost_red_pct, 4))

        # Cost metrics (INR)
        b_inr = float(sd.baseline_native_cost if sd.baseline_native_cost is not None else (b_cost / inr_to_usd))
        gs_inr = float(sd.native_cost if sd.native_cost is not None else (gs_cost / inr_to_usd))
        saved_inr = b_inr - gs_inr

        total_baseline_cost_inr += b_inr
        total_greenshift_cost_inr += gs_inr
        total_cost_saved_inr += saved_inr

        # Delay & SLA
        delay = float(sd.scheduling_delay_hours or 0.0)
        total_delay_hours += delay
        delays.append(round(delay, 4))

        sla = bool(sd.sla_met if sd.sla_met is not None else True)
        if sla:
            sla_met_count += 1
        else:
            sla_miss_count += 1

        # Hours
        if sd.baseline_start:
            baseline_hours[sd.baseline_start.hour] += 1
        elif sd.selected_start:
            baseline_hours[sd.selected_start.hour] += 1

        if sd.selected_start:
            greenshift_hours[sd.selected_start.hour] += 1

        # Breakdown helper
        reg_key = str(sd.region_id or job.region or "UNKNOWN")
        team_key = str(job.team_id or "UNKNOWN")
        jt_key = str(job.job_type or "UNKNOWN")

        for key, bucket in [(reg_key, region_groups), (team_key, team_groups), (jt_key, job_type_groups)]:
            if key not in bucket:
                bucket[key] = {
                    "count": 0,
                    "c_avoided": 0.0,
                    "c_red_list": [],
                    "cost_saved_usd": 0.0,
                    "cost_saved_inr": 0.0,
                    "sla_met": 0,
                }
            bucket[key]["count"] += 1
            bucket[key]["c_avoided"] += c_avoided
            bucket[key]["c_red_list"].append(c_red_pct)
            bucket[key]["cost_saved_usd"] += cost_diff
            bucket[key]["cost_saved_inr"] += saved_inr
            if sla:
                bucket[key]["sla_met"] += 1

    n_decisions = len(rows)

    avg_carbon_red = float(statistics.mean(carbon_reductions)) if carbon_reductions else 0.0
    med_carbon_red = float(statistics.median(carbon_reductions)) if carbon_reductions else 0.0
    p90_carbon_red = _calculate_p90(carbon_reductions)

    avg_cost_red = float(statistics.mean(cost_reductions)) if cost_reductions else 0.0
    med_cost_red = float(statistics.median(cost_reductions)) if cost_reductions else 0.0

    avg_delay = float(total_delay_hours / n_decisions) if n_decisions else 0.0
    sla_compliance = float((sla_met_count / n_decisions) * 100.0) if n_decisions else 100.0

    # Build summaries
    by_region: Dict[str, RegionImpactSummary] = {}
    for r_k, r_v in region_groups.items():
        cnt = r_v["count"]
        by_region[r_k] = RegionImpactSummary(
            job_count=cnt,
            total_carbon_avoided_kg=round(r_v["c_avoided"], 4),
            avg_carbon_reduction_pct=round(statistics.mean(r_v["c_red_list"]) if r_v["c_red_list"] else 0.0, 2),
            total_cost_saved_usd=round(r_v["cost_saved_usd"], 4),
            total_cost_saved_inr=round(r_v["cost_saved_inr"], 2),
            sla_compliance_pct=round((r_v["sla_met"] / cnt * 100.0) if cnt else 100.0, 2),
        )

    by_team: Dict[str, TeamImpactSummary] = {}
    for t_k, t_v in team_groups.items():
        cnt = t_v["count"]
        by_team[t_k] = TeamImpactSummary(
            job_count=cnt,
            total_carbon_avoided_kg=round(t_v["c_avoided"], 4),
            avg_carbon_reduction_pct=round(statistics.mean(t_v["c_red_list"]) if t_v["c_red_list"] else 0.0, 2),
            total_cost_saved_usd=round(t_v["cost_saved_usd"], 4),
            total_cost_saved_inr=round(t_v["cost_saved_inr"], 2),
            sla_compliance_pct=round((t_v["sla_met"] / cnt * 100.0) if cnt else 100.0, 2),
        )

    by_job_type: Dict[str, JobTypeImpactSummary] = {}
    for j_k, j_v in job_type_groups.items():
        cnt = j_v["count"]
        by_job_type[j_k] = JobTypeImpactSummary(
            job_count=cnt,
            total_carbon_avoided_kg=round(j_v["c_avoided"], 4),
            avg_carbon_reduction_pct=round(statistics.mean(j_v["c_red_list"]) if j_v["c_red_list"] else 0.0, 2),
            total_cost_saved_usd=round(j_v["cost_saved_usd"], 4),
            total_cost_saved_inr=round(j_v["cost_saved_inr"], 2),
            sla_compliance_pct=round((j_v["sla_met"] / cnt * 100.0) if cnt else 100.0, 2),
        )

    return FleetImpactReport(
        total_jobs_analyzed=total_jobs_analyzed,
        total_jobs_with_decisions=n_decisions,
        total_energy_kwh=round(total_energy_kwh, 2),
        total_baseline_carbon_kg=round(total_baseline_carbon_kg, 4),
        total_greenshift_carbon_kg=round(total_greenshift_carbon_kg, 4),
        total_carbon_avoided_kg=round(total_carbon_avoided_kg, 4),
        avg_carbon_reduction_pct=round(avg_carbon_red, 2),
        median_carbon_reduction_pct=round(med_carbon_red, 2),
        p90_carbon_reduction_pct=round(p90_carbon_red, 2),
        total_baseline_cost_usd=round(total_baseline_cost_usd, 4),
        total_greenshift_cost_usd=round(total_greenshift_cost_usd, 4),
        total_cost_saved_usd=round(total_cost_saved_usd, 4),
        avg_cost_reduction_pct=round(avg_cost_red, 2),
        median_cost_reduction_pct=round(med_cost_red, 2),
        total_baseline_cost_inr=round(total_baseline_cost_inr, 2),
        total_greenshift_cost_inr=round(total_greenshift_cost_inr, 2),
        total_cost_saved_inr=round(total_cost_saved_inr, 2),
        avg_scheduling_delay_hours=round(avg_delay, 2),
        sla_met_count=sla_met_count,
        sla_miss_count=sla_miss_count,
        sla_compliance_pct=round(sla_compliance, 2),
        jobs_with_positive_carbon_savings=jobs_positive_carbon,
        jobs_with_negative_carbon_savings=jobs_negative_carbon,
        jobs_with_zero_impact=jobs_zero_impact,
        by_region=by_region,
        by_team=by_team,
        by_job_type=by_job_type,
        carbon_reduction_distribution=carbon_reductions,
        cost_reduction_distribution=cost_reductions,
        delay_hours_distribution=delays,
        baseline_hour_distribution=baseline_hours,
        greenshift_hour_distribution=greenshift_hours,
        generated_at=generated_at_iso,
        experiment_id=experiment_id,
        filters_applied=filters_applied,
    )
