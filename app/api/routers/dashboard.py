"""
Agent 5 — PRESENT
FastAPI dashboard summary router.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.shared.database import get_db
from app.shared.auth import require_company_member, AuthenticatedIdentity
from app.shared.models import JobORM, JobStatus, AuditEventORM, ScheduleDecisionORM, UserORM
from app.shared.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/dashboard/summary")
def get_dashboard_summary(
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(require_company_member),
):
    """Aggregate summary data for the Streamlit dashboard."""
    try:
        # Job counts
        from app.shared.auth import is_platform_admin
        if identity and identity.tenant_id and not is_platform_admin(identity):
            jobs = db.query(JobORM).filter(JobORM.tenant_id == identity.tenant_id).all()
            job_ids = [j.job_id for j in jobs]
            decisions = db.query(ScheduleDecisionORM).filter(ScheduleDecisionORM.job_id.in_(job_ids)).all() if job_ids else []
            event_count = db.query(AuditEventORM).filter(AuditEventORM.job_id.in_(job_ids)).count() if job_ids else 0
        else:
            jobs = db.query(JobORM).all()
            decisions = db.query(ScheduleDecisionORM).all()
            event_count = db.query(AuditEventORM).count()

        status_counts = {s.value: 0 for s in JobStatus}
        for j in jobs:
            status_counts[j.status.value] += 1

        # Carbon + cost aggregates
        total_baseline_carbon = sum((d.baseline_carbon_emission or 0) for d in decisions)
        total_gs_carbon = sum((d.carbon_emission or 0) for d in decisions)
        total_avoided = sum((d.carbon_avoided or 0) for d in decisions)
        total_baseline_cost = sum((d.baseline_cost or 0) for d in decisions)
        total_gs_cost = sum((d.electricity_cost or 0) for d in decisions)
        total_cost_saved = sum((d.cost_difference or 0) for d in decisions)

        active_count = (
            status_counts.get("RUNNING", 0)
            + status_counts.get("QUEUED", 0)
            + status_counts.get("DISPATCHING", 0)
        )
        return {
            "total_jobs": len(jobs),
            "active_jobs": active_count,
            "jobs": {
                "total": len(jobs),
                **status_counts,
            },
            "carbon": {
                "baseline_emissions_kg": round(total_baseline_carbon, 6),
                "greenshift_emissions_kg": round(total_gs_carbon, 6),
                "carbon_avoided_kg": round(total_avoided, 6),
            },
            "cost": {
                "baseline_cost": round(total_baseline_cost, 6),
                "greenshift_cost": round(total_gs_cost, 6),
                "cost_difference": round(total_cost_saved, 6),
            },
            "audit": {
                "event_count": event_count,
            },
        }
    except Exception as exc:
        logger.error(f"Error computing dashboard summary: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while generating dashboard metrics.")

