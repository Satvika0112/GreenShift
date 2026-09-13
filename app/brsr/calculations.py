"""
GreenShift — BRSR GreenShift-Derived Metric Calculations.

Computes the small, honest set of BRSR metrics GreenShift's existing
operational data can genuinely support — Scope 2 electricity emissions,
total energy consumption, and the energy/emission intensity derived from
them — all strictly from real, already-persisted JobORM/ScheduleDecisionORM
rows for the tenant's GreenShift-executed workloads within the report's
reporting period. Every other registry metric remains COMPANY_PROVIDED
because no other GreenShift data genuinely supports it.

IMPORTANT PRODUCT RULE (see docs): this is NOT the same thing as
"carbon avoided by GreenShift" (app.trust.report / app.analytics.fleet_impact
compute that — a counterfactual scheduling-optimization delta). A BRSR
emissions disclosure needs the ABSOLUTE emissions actually incurred, so
these functions sum ScheduleDecisionORM.carbon_emission (the real emission
of the executed workload), never carbon_avoided/baseline_carbon_emission.

Every result carries an honest source_detail payload (methodology, job
count, job ids referenced) so the BRSR audit/lineage trail can always be
traced back to the exact GreenShift records used — never a black box.
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.shared.timezone import ensure_utc

_METHOD_SCOPE2 = (
    "Sum of ScheduleDecisionORM.carbon_emission (kg CO2) for jobs of this tenant "
    "submitted within the reporting period, converted to tCO2e (÷1000). Covers "
    "electricity-related emissions from GreenShift-executed workloads only."
)
_METHOD_ENERGY = (
    "Sum of JobORM.energy_kwh (falling back to power_kw × runtime_hours when "
    "not pre-computed) for jobs of this tenant submitted within the reporting period."
)


def _jobs_in_period(db: Session, tenant_id: str, period_start: datetime, period_end: datetime):
    from app.shared.models import JobORM
    return (
        db.query(JobORM)
        .filter(JobORM.tenant_id == tenant_id, JobORM.submitted_at >= period_start, JobORM.submitted_at <= period_end)
        .all()
    )


def _scope2_emissions_tco2e(db: Session, tenant_id: str, period_start: datetime, period_end: datetime) -> Dict[str, Any]:
    from app.shared.models import JobORM, ScheduleDecisionORM

    rows: List[Tuple[Optional[float], str]] = (
        db.query(ScheduleDecisionORM.carbon_emission, JobORM.job_id)
        .join(JobORM, JobORM.job_id == ScheduleDecisionORM.job_id)
        .filter(JobORM.tenant_id == tenant_id, JobORM.submitted_at >= period_start, JobORM.submitted_at <= period_end)
        .all()
    )
    job_ids = [job_id for carbon_kg, job_id in rows if carbon_kg is not None]
    total_kg = sum(carbon_kg for carbon_kg, _ in rows if carbon_kg is not None)
    total_tco2e = round(total_kg / 1000.0, 6)

    return {
        "value": total_tco2e,
        "source_record": f"{len(job_ids)} GreenShift job(s) with a schedule decision in the reporting period",
        "source_detail": {
            "methodology": _METHOD_SCOPE2,
            "job_count": len(job_ids),
            "job_ids": job_ids[:50],  # cap payload size; full list is derivable from the period filter itself
            "total_kg_co2": round(total_kg, 4),
            "reporting_period_start": ensure_utc(period_start).isoformat(),
            "reporting_period_end": ensure_utc(period_end).isoformat(),
        },
    }


def _energy_consumption_kwh(db: Session, tenant_id: str, period_start: datetime, period_end: datetime) -> Dict[str, Any]:
    jobs = _jobs_in_period(db, tenant_id, period_start, period_end)
    total_kwh = 0.0
    job_ids: List[str] = []
    for job in jobs:
        energy = job.energy_kwh
        if not energy and job.power_kw and job.runtime_minutes:
            energy = job.power_kw * (job.runtime_minutes / 60.0)
        if energy:
            total_kwh += energy
            job_ids.append(job.job_id)

    return {
        "value": round(total_kwh, 4),
        "source_record": f"{len(job_ids)} GreenShift job(s) with energy data in the reporting period",
        "source_detail": {
            "methodology": _METHOD_ENERGY,
            "job_count": len(job_ids),
            "job_ids": job_ids[:50],
            "reporting_period_start": ensure_utc(period_start).isoformat(),
            "reporting_period_end": ensure_utc(period_end).isoformat(),
        },
    }


_METHOD_ENERGY_INTENSITY = (
    "Total JobORM.energy_kwh consumed by this tenant's GreenShift-executed workloads in the "
    "reporting period, divided by the count of GreenShift jobs submitted in that period — the "
    "exact same formula as app.trust.report._aggregate's 'energy_intensity_kwh_per_job'. This is "
    "an operational efficiency proxy (kWh per GreenShift job), NOT intensity per unit of company "
    "revenue/output — GreenShift has no visibility into total company production or turnover."
)
_METHOD_EMISSION_INTENSITY = (
    "Total ScheduleDecisionORM.carbon_emission (kg CO2) for this tenant's GreenShift-executed "
    "workloads in the reporting period, divided by their total energy_kwh — the exact same "
    "formula as app.trust.report._aggregate's 'ghg_intensity_kg_per_kwh'. This is the effective "
    "average grid carbon intensity encountered by GreenShift-scheduled workloads (kg CO2 per kWh "
    "consumed), NOT an emission-per-unit-of-output intensity in the traditional revenue-normalized "
    "BRSR sense."
)


def _period_totals(db: Session, tenant_id: str, period_start: datetime, period_end: datetime) -> Dict[str, Any]:
    """Shared totals for the two intensity metrics — mirrors
    app.trust.report._aggregate's total_jobs/total_energy_kwh/total_greenshift_carbon_kg
    exactly, computed independently here since app.brsr never imports from
    app.trust (kept decoupled — see docs on why the two "BRSR-Aligned"
    surfaces are deliberately separate modules)."""
    from app.shared.models import JobORM, ScheduleDecisionORM

    jobs = _jobs_in_period(db, tenant_id, period_start, period_end)
    total_jobs = len(jobs)
    total_energy_kwh = 0.0
    for job in jobs:
        energy = job.energy_kwh
        if not energy and job.power_kw and job.runtime_minutes:
            energy = job.power_kw * (job.runtime_minutes / 60.0)
        total_energy_kwh += energy or 0.0

    carbon_rows = (
        db.query(ScheduleDecisionORM.carbon_emission)
        .join(JobORM, JobORM.job_id == ScheduleDecisionORM.job_id)
        .filter(JobORM.tenant_id == tenant_id, JobORM.submitted_at >= period_start, JobORM.submitted_at <= period_end)
        .all()
    )
    total_carbon_kg = sum(c for (c,) in carbon_rows if c is not None)

    return {"total_jobs": total_jobs, "total_energy_kwh": total_energy_kwh, "total_carbon_kg": total_carbon_kg}


def _energy_intensity_kwh_per_job(db: Session, tenant_id: str, period_start: datetime, period_end: datetime) -> Dict[str, Any]:
    totals = _period_totals(db, tenant_id, period_start, period_end)
    value = round(totals["total_energy_kwh"] / totals["total_jobs"], 4) if totals["total_jobs"] > 0 else 0.0
    return {
        "value": value,
        "source_record": f"{totals['total_jobs']} GreenShift job(s) in the reporting period",
        "source_detail": {
            "methodology": _METHOD_ENERGY_INTENSITY,
            "total_jobs": totals["total_jobs"],
            "total_energy_kwh": round(totals["total_energy_kwh"], 4),
            "reporting_period_start": ensure_utc(period_start).isoformat(),
            "reporting_period_end": ensure_utc(period_end).isoformat(),
        },
    }


def _emission_intensity_kg_per_kwh(db: Session, tenant_id: str, period_start: datetime, period_end: datetime) -> Dict[str, Any]:
    totals = _period_totals(db, tenant_id, period_start, period_end)
    value = round(totals["total_carbon_kg"] / totals["total_energy_kwh"], 6) if totals["total_energy_kwh"] > 0 else 0.0
    return {
        "value": value,
        "source_record": f"{totals['total_jobs']} GreenShift job(s) in the reporting period",
        "source_detail": {
            "methodology": _METHOD_EMISSION_INTENSITY,
            "total_carbon_kg": round(totals["total_carbon_kg"], 4),
            "total_energy_kwh": round(totals["total_energy_kwh"], 4),
            "reporting_period_start": ensure_utc(period_start).isoformat(),
            "reporting_period_end": ensure_utc(period_end).isoformat(),
        },
    }


_CALCULATORS: Dict[str, Callable[[Session, str, datetime, datetime], Dict[str, Any]]] = {
    "CORE_GHG_SCOPE2": _scope2_emissions_tco2e,
    "P6_SCOPE2_EMISSIONS": _scope2_emissions_tco2e,
    "CORE_ENERGY_CONSUMPTION": _energy_consumption_kwh,
    "P6_TOTAL_ENERGY_CONSUMPTION": _energy_consumption_kwh,
    "CORE_ENERGY_INTENSITY": _energy_intensity_kwh_per_job,
    "P6_ENERGY_INTENSITY": _energy_intensity_kwh_per_job,
    "CORE_EMISSION_INTENSITY": _emission_intensity_kg_per_kwh,
    "P6_EMISSION_INTENSITY": _emission_intensity_kg_per_kwh,
}


def calculate_metric(
    db: Session, metric_code: str, tenant_id: str, period_start: datetime, period_end: datetime
) -> Optional[Dict[str, Any]]:
    """Returns {value, source_record, source_detail} for a
    greenshift_derivable metric, or None if this metric_code has no
    calculator (should not happen for a correctly-flagged registry row —
    callers only invoke this for metrics with greenshift_derivable=True)."""
    calculator = _CALCULATORS.get(metric_code)
    if calculator is None:
        return None
    return calculator(db, tenant_id, period_start, period_end)
