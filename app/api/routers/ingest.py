"""
Agent 1 — INGEST
FastAPI router — all ingest endpoints.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ingest.jobs import submit_job, get_job, list_jobs, update_job_status
from app.ingest.service import fetch_and_store_carbon, fetch_and_store_tariff, ingest_job
from app.shared.database import get_db
from app.shared.models import (
    JobSubmitRequest,
    JobSubmitResponse,
    JobStatus,
    CarbonDataPoint,
    TariffDataPoint,
)
from app.shared.utils import utcnow

router = APIRouter()


# ─── Job endpoints ────────────────────────────────────────────────────────────

@router.post("/jobs", response_model=JobSubmitResponse, status_code=201)
def submit_new_job(request: JobSubmitRequest, db: Session = Depends(get_db)):
    """Submit a new deferrable compute job."""
    if request.deadline <= utcnow():
        raise HTTPException(status_code=400, detail="Deadline must be in the future")
    job = ingest_job(db, request)
    return JobSubmitResponse(
        job_id=job.job_id,
        status=job.status,
        submitted_at=job.submitted_at,
    )


@router.get("/jobs", response_model=List[dict])
def list_all_jobs(
    team_id: Optional[str] = Query(None),
    status: Optional[JobStatus] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """List jobs, optionally filtered by team_id and/or status."""
    jobs = list_jobs(db, team_id=team_id, status=status, limit=limit)
    return [
        {
            "job_id": j.job_id,
            "team_id": j.team_id,
            "status": j.status,
            "submitted_at": j.submitted_at.isoformat(),
            "deadline": j.deadline.isoformat(),
            "runtime_minutes": j.runtime_minutes,
            "power_kw": j.power_kw,
            "region": j.region,
            "container_image": j.container_image,
        }
        for j in jobs
    ]


@router.get("/jobs/{job_id}")
def get_job_detail(job_id: str, db: Session = Depends(get_db)):
    """Get full details for a specific job."""
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    result = {
        "job_id": job.job_id,
        "team_id": job.team_id,
        "status": job.status,
        "submitted_at": job.submitted_at.isoformat(),
        "deadline": job.deadline.isoformat(),
        "runtime_minutes": job.runtime_minutes,
        "power_kw": job.power_kw,
        "region": job.region,
        "container_image": job.container_image,
        "cpu_request": job.cpu_request,
        "memory_request": job.memory_request,
        "carbon_budget_kg": job.carbon_budget_kg,
    }

    if job.schedule_decision:
        sd = job.schedule_decision
        result["schedule_decision"] = {
            "selected_start": sd.selected_start.isoformat(),
            "selected_end": sd.selected_end.isoformat(),
            "carbon_intensity": sd.carbon_intensity,
            "electricity_cost": sd.electricity_cost,
            "carbon_emission": sd.carbon_emission,
            "reason": sd.reason,
            "budget_remaining": sd.budget_remaining,
            "carbon_avoided": sd.carbon_avoided,
            "cost_difference": sd.cost_difference,
        }

    if job.kubernetes_execution:
        ke = job.kubernetes_execution
        result["kubernetes"] = {
            "kubernetes_job_name": ke.kubernetes_job_name,
            "kubernetes_namespace": ke.kubernetes_namespace,
            "pod_name": ke.pod_name,
            "planned_start": ke.planned_start.isoformat(),
            "actual_start": ke.actual_start.isoformat() if ke.actual_start else None,
            "actual_end": ke.actual_end.isoformat() if ke.actual_end else None,
            "k8s_status": ke.k8s_status,
            "gs_status": ke.gs_status,
        }

    return result


# ─── Carbon data endpoints ────────────────────────────────────────────────────

@router.get("/carbon", response_model=dict)
def get_carbon_data(
    region: str = Query(..., description="Grid region code"),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
):
    """Fetch carbon intensity curve for a region and time window."""
    now = utcnow()
    start = start or now
    end = end or (now + timedelta(hours=24))
    data = fetch_and_store_carbon(db, region, start, end)
    return {
        "region": region,
        "data": [
            {
                "timestamp": p.timestamp.isoformat(),
                "region": p.region,
                "carbon_gco2_kwh": p.carbon_gco2_kwh,
            }
            for p in data
        ],
    }


# ─── Tariff data endpoints ────────────────────────────────────────────────────

@router.get("/tariff", response_model=dict)
def get_tariff_data(
    region: str = Query(..., description="Grid region code"),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
):
    """Fetch electricity tariff curve for a region and time window."""
    now = utcnow()
    start = start or now
    end = end or (now + timedelta(hours=24))
    data = fetch_and_store_tariff(db, region, start, end)
    return {
        "region": region,
        "data": [
            {
                "timestamp": p.timestamp.isoformat(),
                "region": p.region,
                "price_per_kwh": p.price_per_kwh,
            }
            for p in data
        ],
    }
