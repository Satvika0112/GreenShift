"""
Agent 5 — PRESENT
FastAPI dashboard summary router.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.shared.database import get_db
from app.shared.auth import get_current_user
from app.shared.models import JobORM, JobStatus, AuditEventORM, ScheduleDecisionORM, UserORM
from app.shared.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/dashboard/summary")
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Aggregate summary data for the Streamlit dashboard."""
    try:
        # Job counts
        jobs = db.query(JobORM).all()
        status_counts = {s.value: 0 for s in JobStatus}
        for j in jobs:
            status_counts[j.status.value] += 1

        # Carbon + cost aggregates
        decisions = db.query(ScheduleDecisionORM).all()
        total_baseline_carbon = sum((d.baseline_carbon_emission or 0) for d in decisions)
        total_gs_carbon = sum((d.carbon_emission or 0) for d in decisions)
        total_avoided = sum((d.carbon_avoided or 0) for d in decisions)
        total_baseline_cost = sum((d.baseline_cost or 0) for d in decisions)
        total_gs_cost = sum((d.electricity_cost or 0) for d in decisions)
        total_cost_saved = sum((d.cost_difference or 0) for d in decisions)

        # Audit
        event_count = db.query(AuditEventORM).count()

        return {
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

