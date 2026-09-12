"""
FastAPI Router for Contention-Aware Batch Scheduling & ML Demand Forecasting.
Provides endpoints for batch scheduling, demand forecaster training, status inspection,
and slot capacity contention visualization.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.tenant_scope import is_team_restricted
from app.decide.demand_forecaster import DemandForecaster, get_demand_forecaster
from app.decide.service import schedule_batch_and_store
from app.decide.slot_capacity import SlotCapacityRegistry
from app.dispatch.k8s_state_collector import collect_cluster_state, _parse_cpu_string, _parse_memory_string
from app.shared.auth import AuthenticatedIdentity, get_current_identity, is_platform_admin, require_platform_admin
from app.shared.database import get_db
from app.shared.models import JobORM, JobStatus, ScheduleDecisionORM

logger = logging.getLogger(__name__)

router = APIRouter()


class BatchScheduleRequest(BaseModel):
    job_ids: Optional[List[str]] = Field(None, description="List of specific job IDs to schedule. If omitted, all submitted jobs are scheduled.")
    use_demand_forecast: bool = Field(True, description="Whether to apply ML demand forecast soft penalty (Layer 2)")
    max_jobs: Optional[int] = Field(None, description="Maximum jobs to schedule in this batch")
    record_audit: bool = Field(True, description="Whether to write audit trail events")


@router.post("/schedule/batch", summary="Batch Schedule Submitted Jobs")
def schedule_batch_endpoint(
    http_request: Request,
    request: Optional[BatchScheduleRequest] = None,
    use_ml: Optional[bool] = Query(None, description="Query param override for use_demand_forecast"),
    max_jobs: Optional[int] = Query(None, description="Query param override for max_jobs"),
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(get_current_identity),
) -> Dict[str, Any]:
    """
    Batch-schedule jobs with discrete slot capacity enforcement (Layer 1)
    and optional ML demand forecast soft signal (Layer 2).

    Scoped identically to every other job-mutating endpoint via the shared
    tenant/team model: Platform Admin may batch-schedule any job; Company
    Admin is limited to their own company's jobs across all its teams;
    Company User is limited to their own team's jobs. An explicit job_ids
    list can only narrow this scope, never widen it.
    """
    use_ml_flag = True
    record_audit = True
    job_ids_filter = None
    limit_val = max_jobs

    if request is not None:
        use_ml_flag = request.use_demand_forecast
        record_audit = request.record_audit
        job_ids_filter = request.job_ids
        if request.max_jobs is not None:
            limit_val = request.max_jobs

    if use_ml is not None:
        use_ml_flag = use_ml

    query = db.query(JobORM)
    if job_ids_filter:
        query = query.filter(JobORM.job_id.in_(job_ids_filter))
    else:
        # SUBMITTED is the only pre-decision status a job can hold — there is
        # no JobStatus.PENDING (single-job /schedule/{job_id} enforces the
        # same SUBMITTED-only precondition; see app/api/routers/schedule.py).
        query = query.filter(JobORM.status == JobStatus.SUBMITTED)

    # Tenant/team isolation — same rule as app.api.tenant_scope.get_tenant_jobs:
    # every non-Platform-Admin caller is locked to their own tenant; a plain
    # Company User is additionally locked to their own team.
    if identity and not is_platform_admin(identity):
        if identity.tenant_id:
            query = query.filter(JobORM.tenant_id == identity.tenant_id)
        if is_team_restricted(identity):
            query = query.filter(JobORM.team_id == getattr(identity, "team_id", None))

    query = query.order_by(JobORM.created_at.asc())
    if limit_val is not None and limit_val > 0:
        query = query.limit(limit_val)

    jobs = query.all()

    if not jobs:
        return {
            "status": "success",
            "jobs_scheduled": 0,
            "spilled_from_preferred_count": 0,
            "spill_rate_pct": 0.0,
            "ml_advisor_applied": False,
            "message": "No eligible jobs pending scheduling",
            "decisions": [],
        }

    decisions = schedule_batch_and_store(
        db=db,
        jobs=jobs,
        use_demand_forecast=use_ml_flag,
        record_audit=record_audit,
        actor=identity,
        request_id=getattr(http_request.state, "request_id", None),
    )

    spilled_count = sum(1 for d in decisions if getattr(d, "spilled_from_preferred", False))
    return {
        "status": "success",
        "jobs_scheduled": len(decisions),
        "spilled_from_preferred_count": spilled_count,
        "spill_rate_pct": round(spilled_count / len(decisions) * 100.0, 1) if decisions else 0.0,
        "ml_advisor_applied": any(getattr(d, "ml_advisor_used", False) for d in decisions),
        "decisions": [d.model_dump(mode="json") for d in decisions],
    }


@router.post("/demand-forecaster/train", summary="Train ML Demand Forecaster")
def train_demand_model(
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(require_platform_admin),
) -> Dict[str, Any]:
    """
    Train the GradientBoosting demand forecasting model on historical job arrival timestamps (JobORM.submitted_at).
    Never queries or trains on scheduler decisions, strictly preserving causality.

    Platform Admin only: this (re)trains one global, fleet-wide model shared
    by every tenant — not a per-company resource a Company Admin owns.
    """
    forecaster = get_demand_forecaster()
    meta = forecaster.train(db)
    return {
        "status": meta.get("status", "success"),
        "metadata": meta,
    }


@router.get("/demand-forecaster/status", summary="Get Forecaster Training Status")
def get_forecaster_status(
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(get_current_identity),
) -> Dict[str, Any]:
    """
    Inspect the status, sample count, and training parameters of the ML demand forecaster.
    Any authenticated user may view this — it is global, aggregate model
    metadata, not tenant-scoped data.
    """
    forecaster = get_demand_forecaster()
    total_jobs = db.query(JobORM).count()
    status_info = forecaster.get_status()
    status_info["historical_job_count"] = total_jobs
    status_info["model_type"] = "GradientBoostingRegressor (n=50, depth=4)" if forecaster.is_trained else None
    return status_info


@router.get("/scheduler/capacity-map", summary="Get Slot Capacity & Contention Map")
def get_capacity_map(
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(get_current_identity),
) -> Dict[str, Any]:
    """
    Return slot allocation, CPU utilization percentages, and contention hotspots
    across all scheduled decisions in the system.
    """
    cluster_state = collect_cluster_state()
    registry = SlotCapacityRegistry(default_snapshot=cluster_state)

    decisions = db.query(ScheduleDecisionORM).all()
    for sd in decisions:
        job = db.query(JobORM).filter(JobORM.job_id == sd.job_id).first()
        if job and sd.selected_start:
            cpu = _parse_cpu_string(job.cpu_request or "500m")
            mem = _parse_memory_string(job.memory_request or "512Mi")
            gpu = int(getattr(job, "gpu_request", 0) or 0)
            duration_hours = (job.runtime_minutes or 60) / 60.0
            region = sd.region_id or job.region or "us-east-1"
            registry.allocate(region, sd.selected_start, duration_hours, cpu, mem, gpu)

    contention = registry.get_contention_map()
    summary = registry.get_summary()

    return {
        "summary": summary,
        "cluster_limits": {
            "max_cpu_cores": registry.default_max_cpu,
            "max_memory_mib": registry.default_max_mem_mib,
            "max_gpus": registry.default_max_gpus,
        },
        "contention_map": contention,
    }
