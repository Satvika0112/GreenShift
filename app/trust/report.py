"""
Agent 4 — TRUST
BRSR-Style Sustainability Report Generator.

Generates a structured sustainability report in the style of India's
Business Responsibility and Sustainability Report (BRSR) framework.

The report covers:
  - Carbon emissions (Scope 2 — purchased electricity)
  - Energy consumption
  - Carbon avoided vs baseline
  - Cost savings
  - Job-level SLA performance
  - Audit chain integrity

Output formats:
  - dict (for API/JSON)
  - CSV string (for download)
  - Markdown summary

Usage:
    from app.trust.report import generate_report
    report = generate_report(db)
"""

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.analytics.fleet_impact import _resolve_currency
from app.shared.models import (
    AuditEventORM,
    JobORM,
    JobStatus,
    KubernetesExecutionORM,
    ScheduleDecisionORM,
)
from app.trust.ledger import verify_chain

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SLA calculation
# ─────────────────────────────────────────────────────────────────────────────

def _calculate_sla(job: JobORM) -> dict:
    """
    Calculate SLA performance for a single job.

    SLA = job completed before its deadline.
    A miss = job FAILED or completed AFTER the deadline.
    """
    deadline = job.deadline
    if deadline and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    status = job.status
    ke: Optional[KubernetesExecutionORM] = job.kubernetes_execution

    actual_end = None
    if ke and ke.actual_end:
        actual_end = ke.actual_end
        if actual_end.tzinfo is None:
            actual_end = actual_end.replace(tzinfo=timezone.utc)

    sla_met = False
    sla_miss = False
    lateness_minutes: Optional[float] = None

    if status == JobStatus.COMPLETED:
        if actual_end and deadline:
            sla_met = actual_end <= deadline
            sla_miss = not sla_met
            if sla_miss:
                lateness_minutes = round((actual_end - deadline).total_seconds() / 60, 2)
        else:
            sla_met = True  # completed but no actual_end recorded
    elif status == JobStatus.FAILED:
        sla_miss = True

    return {
        "sla_met": sla_met,
        "sla_miss": sla_miss,
        "lateness_minutes": lateness_minutes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-job metrics
# ─────────────────────────────────────────────────────────────────────────────

def _job_row(job: JobORM) -> dict:
    """Build a single job's report row."""
    sd: Optional[ScheduleDecisionORM] = job.schedule_decision
    ke: Optional[KubernetesExecutionORM] = job.kubernetes_execution
    sla = _calculate_sla(job)

    # Energy: kWh = power_kw × runtime_hours
    energy_kwh = job.power_kw * (job.runtime_minutes / 60.0)

    return {
        # Identity
        "job_id":               job.job_id,
        "team_id":              job.team_id,
        "status":               job.status.value,
        "region":               job.region,
        "submitted_at":         job.submitted_at.isoformat() if job.submitted_at else None,
        "deadline":             job.deadline.isoformat() if job.deadline else None,

        # Workload specs
        "runtime_minutes":      job.runtime_minutes,
        "power_kw":             job.power_kw,
        "energy_kwh":           round(energy_kwh, 6),
        "container_image":      job.container_image,
        "cpu_request":          job.cpu_request,
        "memory_request":       job.memory_request,
        "carbon_budget_kg":     job.carbon_budget_kg,

        # Schedule decision
        "selected_start":       sd.selected_start.isoformat() if sd else None,
        "selected_end":         sd.selected_end.isoformat() if sd else None,
        "carbon_intensity_gco2_kwh": sd.carbon_intensity if sd else None,
        # sd.electricity_cost is already a TOTAL (energy_kwh * price_per_kwh_usd
        # — see app.shared.models.ScheduleDecision.electricity_cost), so the
        # per-kWh rate is that total divided by energy, not the total itself.
        "electricity_cost_per_kwh":  (sd.electricity_cost / energy_kwh) if sd and energy_kwh else None,

        # Emissions (Scope 2 — purchased electricity)
        "greenshift_carbon_kg": sd.carbon_emission if sd else None,
        "baseline_carbon_kg":   sd.baseline_carbon_emission if sd else None,
        "carbon_avoided_kg":    sd.carbon_avoided if sd else None,

        # Cost — sd.electricity_cost is already the total cost (see above);
        # previously multiplied by energy_kwh a second time here, inflating
        # every greenshift_cost_usd (and therefore every aggregate derived
        # from it) by a factor of energy_kwh.
        "greenshift_cost_usd":  sd.electricity_cost if sd else None,
        "baseline_cost_usd":    sd.baseline_cost if sd else None,
        "cost_difference_usd":  sd.cost_difference if sd else None,
        "budget_remaining_kg":  sd.budget_remaining if sd else None,

        # Native-currency cost — the execution region's real currency (see
        # app.analytics.fleet_impact._resolve_currency), never assumed to be
        # INR. Only meaningful together with `currency` below; never sum
        # these across rows without grouping by it first.
        "greenshift_cost_native":  sd.native_cost if sd else None,
        "baseline_cost_native":    sd.baseline_native_cost if sd else None,
        "currency":                _resolve_currency(job, sd) if sd else None,

        # Scheduling delay
        "scheduling_delay_hours": sd.scheduling_delay_hours if sd else None,

        # Carbon reduction percentage per job
        "carbon_reduction_pct": sd.carbon_reduction_pct if sd else None,

        # Kubernetes execution
        "k8s_job_name":         ke.kubernetes_job_name if ke else None,
        "k8s_namespace":        ke.kubernetes_namespace if ke else None,
        "pod_name":             ke.pod_name if ke else None,
        "planned_start":        ke.planned_start.isoformat() if ke else None,
        "actual_start":         ke.actual_start.isoformat() if ke and ke.actual_start else None,
        "actual_end":           ke.actual_end.isoformat() if ke and ke.actual_end else None,
        "k8s_status":           ke.k8s_status if ke else None,

        # SLA
        "sla_met":              sla["sla_met"],
        "sla_miss":             sla["sla_miss"],
        "lateness_minutes":     sla["lateness_minutes"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate summary
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_by_region(rows: List[dict]) -> dict:
    """Regional breakdown — required for BRSR geographic disclosure."""
    regions = {}
    for r in rows:
        region = r.get("region", "UNKNOWN") or "UNKNOWN"
        if region not in regions:
            regions[region] = {
                "job_count": 0,
                "energy_kwh": 0.0,
                "carbon_avoided_kg": 0.0,
                "cost_saved_usd": 0.0,
                "sla_met": 0,
            }
        regions[region]["job_count"] += 1
        regions[region]["energy_kwh"] += r.get("energy_kwh", 0) or 0
        regions[region]["carbon_avoided_kg"] += r.get("carbon_avoided_kg", 0) or 0
        regions[region]["cost_saved_usd"] += r.get("cost_difference_usd", 0) or 0
        if r.get("sla_met"):
            regions[region]["sla_met"] += 1

    for reg, data in regions.items():
        data["energy_kwh"] = round(data["energy_kwh"], 4)
        data["carbon_avoided_kg"] = round(data["carbon_avoided_kg"], 4)
        data["cost_saved_usd"] = round(data["cost_saved_usd"], 4)
    return regions


def _aggregate(rows: List[dict]) -> dict:
    """Compute aggregate sustainability metrics across all jobs."""
    scheduled_rows = [r for r in rows if r["greenshift_carbon_kg"] is not None]

    total_jobs       = len(rows)
    completed        = sum(1 for r in rows if r["status"] == "COMPLETED")
    failed           = sum(1 for r in rows if r["status"] == "FAILED")
    sla_met          = sum(1 for r in rows if r["sla_met"])
    sla_misses       = sum(1 for r in rows if r["sla_miss"])

    total_energy_kwh      = sum(r["energy_kwh"] for r in rows)
    total_gs_carbon       = sum(r["greenshift_carbon_kg"] or 0 for r in rows)
    total_baseline_carbon = sum(r["baseline_carbon_kg"] or 0 for r in rows)
    total_carbon_avoided  = sum(r["carbon_avoided_kg"] or 0 for r in rows)
    total_gs_cost         = sum(r["greenshift_cost_usd"] or 0 for r in rows)
    total_baseline_cost   = sum(r["baseline_cost_usd"] or 0 for r in rows)
    total_cost_saved      = sum(r["cost_difference_usd"] or 0 for r in rows)

    # Currency-separated native savings — a report can span multiple
    # execution regions/currencies (INR/USD/AUD/...), so these are grouped
    # by each row's actual `currency`, never blindly summed into a single
    # figure mislabeled as one currency (see app.analytics.fleet_impact,
    # which fixes the identical issue for /impact/fleet).
    cost_saved_by_currency: Dict[str, float] = {}
    for r in rows:
        gs_native = r.get("greenshift_cost_native")
        base_native = r.get("baseline_cost_native")
        if gs_native is None or base_native is None:
            continue
        currency = r.get("currency") or "UNKNOWN"
        cost_saved_by_currency[currency] = cost_saved_by_currency.get(currency, 0.0) + (base_native - gs_native)

    delays = [r["scheduling_delay_hours"] for r in scheduled_rows if r.get("scheduling_delay_hours") is not None]
    avg_delay = (sum(delays) / len(delays)) if delays else 0.0

    positive_count = sum(1 for r in rows if (r.get("carbon_avoided_kg") or 0) > 0)
    negative_count = sum(1 for r in rows if (r.get("carbon_avoided_kg") or 0) < 0)

    avg_intensity = (
        sum(r["carbon_intensity_gco2_kwh"] for r in scheduled_rows if r["carbon_intensity_gco2_kwh"])
        / len(scheduled_rows)
        if scheduled_rows else 0.0
    )

    carbon_reduction_pct = (
        (total_carbon_avoided / total_baseline_carbon * 100)
        if total_baseline_carbon > 0 else 0.0
    )
    sla_performance_pct = (sla_met / total_jobs * 100) if total_jobs > 0 else 100.0

    return {
        "total_jobs":                  total_jobs,
        "completed_jobs":              completed,
        "failed_jobs":                 failed,
        "sla_met":                     sla_met,
        "sla_misses":                  sla_misses,
        "sla_performance_pct":         round(sla_performance_pct, 2),
        "total_energy_kwh":            round(total_energy_kwh, 6),
        "total_greenshift_carbon_kg":  round(total_gs_carbon, 6),
        "total_baseline_carbon_kg":    round(total_baseline_carbon, 6),
        "total_carbon_avoided_kg":     round(total_carbon_avoided, 6),
        "carbon_reduction_pct":        round(carbon_reduction_pct, 2),
        "avg_carbon_intensity_gco2_kwh": round(avg_intensity, 2),
        "total_greenshift_cost_usd":   round(total_gs_cost, 6),
        "total_baseline_cost_usd":     round(total_baseline_cost, 6),
        "total_cost_saved_usd":        round(total_cost_saved, 6),

        # Energy intensity (kWh per job — efficiency metric)
        "energy_intensity_kwh_per_job": round(total_energy_kwh / total_jobs, 4) if total_jobs > 0 else 0.0,

        # GHG emissions intensity (kg CO₂ per kWh — how clean is the energy?)
        "ghg_intensity_kg_per_kwh": round(total_gs_carbon / total_energy_kwh, 6) if total_energy_kwh > 0 else 0.0,

        # Regional breakdown (BRSR requires geographic disclosure)
        "by_region": _aggregate_by_region(rows),

        # Native-currency cost saved, alongside USD — currency-separated,
        # never a single cross-region sum (see comment at cost_saved_by_currency above).
        "cost_saved_by_currency": {c: round(v, 4) for c, v in cost_saved_by_currency.items()},

        # Scheduling efficiency
        "avg_scheduling_delay_hours": round(avg_delay, 2),
        "jobs_with_positive_carbon_savings": positive_count,
        "jobs_with_negative_carbon_savings": negative_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(
    db: Session,
    team_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
) -> dict:
    """
    Generate a full BRSR-style sustainability report.

    Args:
        db:         SQLAlchemy session.
        team_id:    Filter by team (optional).
        start_date: Filter jobs submitted on/after this date (optional).
        end_date:   Filter jobs submitted on/before this date (optional).
        tenant_id:  Filter jobs by tenant (optional).

    Returns:
        dict with keys: metadata, summary, jobs, audit
    """
    query = db.query(JobORM)
    if tenant_id:
        query = query.filter(JobORM.tenant_id == tenant_id)
    if team_id:
        query = query.filter(JobORM.team_id == team_id)
    if start_date:
        query = query.filter(JobORM.submitted_at >= start_date)
    if end_date:
        query = query.filter(JobORM.submitted_at <= end_date)
    jobs = query.all()

    rows = [_job_row(j) for j in jobs]
    summary = _aggregate(rows)
    audit_result = verify_chain(db)

    generated_at = datetime.now(timezone.utc).isoformat()

    return {
        "metadata": {
            "report_type":    "GreenShift BRSR-Aligned Sustainability Report",  # "Aligned" not "Compliant"
            "generated_at":   generated_at,
            "framework":      "BRSR (Business Responsibility and Sustainability Reporting) — Aligned",
            "scope":          "Scope 2 — Purchased Electricity (Compute Workloads)",
            "methodology":    (
                "Carbon intensity from Electricity Maps API / regional CSV datasets. "
                "Tariff data from Indian DISCOM Time-of-Day schedules. "
                "Baseline = immediate execution at earliest feasible slot."
            ),
            "data_quality_notes": {
                "carbon_source": "Electricity Maps API with CSV and controlled fallback",
                "tariff_source": "Indian regional DISCOM ToD tariff CSVs (FY2026-27)",
                "limitations": (
                    "Scope 2 only. Scope 1 (direct) and Scope 3 (supply chain) "
                    "are outside current measurement scope."
                ),
            },
            "team_filter":    team_id or "ALL",
            "date_from":      start_date.isoformat() if start_date else "ALL",
            "date_to":        end_date.isoformat() if end_date else "ALL",
            "total_jobs":     len(rows),
        },
        "summary": summary,
        "jobs": rows,
        "audit": {
            "chain_valid":  audit_result.valid,
            "event_count":  audit_result.event_count,
            "message":      audit_result.message,
        },
    }


def generate_csv(
    db: Session,
    team_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """
    Generate a CSV string of the full job-level report.
    Suitable for BRSR annual report data export.

    Returns:
        CSV string (utf-8).
    """
    report = generate_report(db, team_id=team_id, start_date=start_date, end_date=end_date, tenant_id=tenant_id)
    rows = report["jobs"]

    if not rows:
        return "No data"

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def generate_markdown_summary(db: Session, tenant_id: Optional[str] = None) -> str:
    """Generate a markdown summary of the sustainability report."""
    report = generate_report(db, tenant_id=tenant_id)
    s = report["summary"]
    m = report["metadata"]

    lines = [
        f"# 🌿 GreenShift BRSR-Aligned Sustainability Report",
        f"**Generated:** {m['generated_at']}",
        f"",
        f"## Energy & Carbon",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total Energy Consumed | {s['total_energy_kwh']:.4f} kWh |",
        f"| GreenShift Carbon Emissions | {s['total_greenshift_carbon_kg']:.4f} kg CO₂ |",
        f"| Baseline Carbon Emissions | {s['total_baseline_carbon_kg']:.4f} kg CO₂ |",
        f"| **Carbon Avoided** | **{s['total_carbon_avoided_kg']:.4f} kg CO₂** |",
        f"| Carbon Reduction | {s['carbon_reduction_pct']:.1f}% |",
        f"| Avg Carbon Intensity | {s['avg_carbon_intensity_gco2_kwh']:.1f} gCO₂/kWh |",
        f"| Energy Intensity | {s['energy_intensity_kwh_per_job']:.4f} kWh/job |",
        f"| GHG Emissions Intensity | {s['ghg_intensity_kg_per_kwh']:.6f} kg CO₂/kWh |",
        f"",
        f"## Cost",
        f"| Metric | Value (USD) |",
        f"|---|---|",
        f"| GreenShift Cost | ${s['total_greenshift_cost_usd']:.4f} |",
        f"| Baseline Cost | ${s['total_baseline_cost_usd']:.4f} |",
        f"| **Cost Saved** | **${s['total_cost_saved_usd']:.4f}** |",
        f"",
        # Native-currency savings, currency-separated — never a single sum
        # across regions with different currencies (see cost_saved_by_currency
        # in app.trust.report._aggregate / app.analytics.fleet_impact).
        f"**Cost Saved (native currency, by region currency):** "
        + (
            ", ".join(f"{amt:.2f} {cur}" for cur, amt in s.get("cost_saved_by_currency", {}).items())
            or "Not available"
        ),
        f"",
        f"## Regional Breakdown",
        f"| Region | Jobs | Energy (kWh) | Carbon Avoided (kg) | Cost Saved (USD) | SLA Met |",
        f"|---|---|---|---|---|---|",
    ]

    for reg, rstats in s.get("by_region", {}).items():
        lines.append(
            f"| {reg} | {rstats['job_count']} | {rstats['energy_kwh']:.2f} | "
            f"{rstats['carbon_avoided_kg']:.2f} | ${rstats['cost_saved_usd']:.2f} | {rstats['sla_met']} |"
        )

    lines.extend([
        f"",
        f"## Jobs & SLA",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total Jobs | {s['total_jobs']} |",
        f"| Completed | {s['completed_jobs']} |",
        f"| Failed | {s['failed_jobs']} |",
        f"| SLA Met | {s['sla_met']} ({s['sla_performance_pct']:.1f}%) |",
        f"| SLA Misses | {s['sla_misses']} |",
        f"| Avg Scheduling Delay | {s['avg_scheduling_delay_hours']:.2f} hrs |",
        f"",
        f"## Audit",
        f"| Chain Status | {'✅ VALID' if report['audit']['chain_valid'] else '❌ BROKEN'} |",
        f"| Event Count | {report['audit']['event_count']} |",
        f"",
        f"## Methodology & Data Quality",
        f"- **Scope**: Scope 2 — Purchased Electricity (Compute Workloads)",
        f"- **Carbon data**: Electricity Maps API with CSV and controlled fallback",
        f"- **Tariff data**: Indian regional DISCOM Time-of-Day tariff CSVs",
        f"- **Baseline method**: Immediate execution at earliest feasible slot",
        f"- **Limitations**: Scope 1 and Scope 3 emissions outside current measurement scope",
    ])

    return "\n".join(lines)
