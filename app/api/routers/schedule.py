"""
Agent 2 — DECIDE
FastAPI router for schedule endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.decide.service import schedule_and_store
from app.ingest.jobs import get_job
from app.shared.database import get_db
from app.shared.models import JobStatus

router = APIRouter()


@router.post("/schedule/{job_id}")
def trigger_schedule(job_id: str, db: Session = Depends(get_db)):
    """
    Manually trigger scheduling for a specific job.
    Normally scheduling is triggered automatically by the DECIDE background loop.
    """
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status not in (JobStatus.SUBMITTED,):
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is in status {job.status} — only SUBMITTED jobs can be scheduled",
        )
    try:
        decision = schedule_and_store(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "job_id": decision.job_id,
        "selected_start": decision.selected_start.isoformat(),
        "selected_end": decision.selected_end.isoformat(),
        "carbon_intensity": decision.carbon_intensity,
        "electricity_cost": decision.electricity_cost,
        "carbon_emission": decision.carbon_emission,
        "reason": decision.reason,
        "budget_remaining": decision.budget_remaining,
        "carbon_avoided": decision.carbon_avoided,
        "cost_difference": decision.cost_difference,
    }
