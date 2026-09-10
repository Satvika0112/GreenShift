"""
Agent 1 — INGEST
FastAPI router — all ingest endpoints.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.ingest.jobs import submit_job, get_job, list_jobs, update_job_status
from app.ingest.service import (
    fetch_and_store_carbon,
    fetch_and_store_tariff,
    ingest_job,
    load_csv_jobs_to_db,
    get_ingest_status,
)
from app.shared.database import get_db
from app.shared.rate_limiter import limiter
from app.shared.auth import get_current_user, require_roles
from app.shared.models import (
    JobSubmitRequest,
    JobSubmitResponse,
    JobStatus,
    CarbonDataPoint,
    TariffDataPoint,
    UserORM,
    UserRole,
    EventType,
)
from app.shared.utils import utcnow, get_logger

logger = get_logger(__name__)

router = APIRouter()


# ─── Job endpoints ────────────────────────────────────────────────────────────

@router.post("/jobs", response_model=JobSubmitResponse, status_code=201)
@limiter.limit("60/minute")
def submit_new_job(
    request: Request,
    body: JobSubmitRequest,
    auto_schedule: bool = Query(False, description="Automatically trigger Carbon-Aware scheduling upon submission"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(UserRole.PLATFORM_ADMIN, UserRole.COMPANY_ADMIN, UserRole.COMPANY_USER)),
):
    """Submit a new deferrable compute job with input validation, tenant isolation, and lifecycle state tracking."""
    from app.shared.timezone import normalize_to_utc
    try:
        user_role_val = current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role)
        if user_role_val == "COMPANY_USER" and current_user.team_id:
            if body.team_id and body.team_id != current_user.team_id:
                raise HTTPException(
                    status_code=403,
                    detail=f"User for team '{current_user.team_id}' cannot submit jobs for team '{body.team_id}'",
                )
        req_tz = getattr(body, "timezone", None)
        normalized_deadline = normalize_to_utc(body.deadline, region=body.region, timezone_name=req_tz)
        if normalized_deadline <= utcnow():
            raise HTTPException(status_code=400, detail="Deadline must be in the future")
        body.deadline = normalized_deadline
        job = ingest_job(
            db,
            body,
            tenant_id=current_user.tenant_id,
            company_name=current_user.company_name,
            submitted_by_user_id=current_user.id,
        )

        # Record validation audit event
        try:
            from app.trust.ledger import append_event
            append_event(db, EventType.JOB_VALIDATED, job_id=job.job_id, payload={
                "team_id": job.team_id,
                "tenant_id": job.tenant_id,
                "company_name": job.company_name,
                "region": job.region,
                "deadline": job.deadline.isoformat(),
                "runtime_minutes": job.runtime_minutes,
            })
        except Exception:
            pass

        if auto_schedule:
            try:
                from app.decide.service import schedule_and_store
                schedule_and_store(db, job, record_audit=True)
                db.refresh(job)
            except Exception as sched_err:
                logger.warning(f"Immediate auto-scheduling failed for {job.job_id}: {sched_err}")

        return JobSubmitResponse(
            job_id=job.job_id,
            status=job.status,
            submitted_at=job.submitted_at,
            name=job.workload_name,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Error submitting job: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while ingesting the workload.")


@router.post("/jobs/bulk-load", response_model=dict)
@limiter.limit("20/minute")
def bulk_load_jobs_from_csv(
    request: Request,
    csv_path: Optional[str] = Query(None, description="Optional path to job CSV"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(UserRole.PLATFORM_ADMIN, UserRole.COMPANY_USER)),
):
    """
    Bulk-load jobs from the configured or specified workload CSV file into the database.
    """
    try:
        count, errors = load_csv_jobs_to_db(db, csv_path=csv_path)
        return {
            "status": "success" if count > 0 or not errors else "partial",
            "jobs_loaded": count,
            "errors_count": len(errors),
            "errors": errors[:50],  # cap to top 50 error messages
        }
    except Exception as exc:
        logger.error(f"Error in bulk loading jobs: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while bulk-loading jobs.")


@router.get("/jobs", response_model=List[dict])
def list_all_jobs(
    team_id: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID (Platform Admin only)"),
    status: Optional[JobStatus] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """List jobs with strict tenant isolation. Platform Admins can see all or filter by tenant."""
    try:
        from app.api.tenant_scope import get_tenant_jobs
        jobs = get_tenant_jobs(
            db=db,
            identity=current_user,
            tenant_id=tenant_id,
            team_id=team_id,
            status=status,
            limit=limit,
        )
        res = []
        for j in jobs:
            item = {
                "job_id": j.job_id,
                "name": j.workload_name,
                "team_id": j.team_id,
                "tenant_id": j.tenant_id,
                "company_name": j.company_name,
                "job_type": j.job_type,
                "priority": j.priority,
                "status": j.status,
                "submitted_at": j.submitted_at.isoformat(),
                "earliest_start_time": j.earliest_start_time.isoformat() if j.earliest_start_time else None,
                "deadline": j.deadline.isoformat(),
                "runtime_minutes": j.runtime_minutes,
                "power_kw": j.power_kw,
                "energy_kwh": j.energy_kwh,
                "deferrable": j.deferrable,
                "region": j.region,
                "container_image": j.container_image,
                "cpu_request": j.cpu_request,
                "memory_request": j.memory_request,
                "carbon_budget_kg": j.carbon_budget_kg,
                "selected_start": j.schedule_decision.selected_start.isoformat() if j.schedule_decision else None,
                "selected_end": j.schedule_decision.selected_end.isoformat() if j.schedule_decision else None,
                "carbon_intensity": j.schedule_decision.carbon_intensity if j.schedule_decision else None,
                "carbon_emission": j.schedule_decision.carbon_emission if j.schedule_decision else None,
                "electricity_cost": j.schedule_decision.electricity_cost if j.schedule_decision else None,
                "native_cost": getattr(j.schedule_decision, "native_cost", None) if j.schedule_decision else None,
                "currency": getattr(j.schedule_decision, "currency", "USD") if j.schedule_decision else "USD",
                "kubernetes_job_name": j.kubernetes_execution.kubernetes_job_name if j.kubernetes_execution else None,
                "kubernetes_namespace": j.kubernetes_execution.kubernetes_namespace if j.kubernetes_execution else None,
                "k8s_status": j.kubernetes_execution.k8s_status if j.kubernetes_execution else None,
                "pod_name": j.kubernetes_execution.pod_name if j.kubernetes_execution else None,
                "actual_start": j.kubernetes_execution.actual_start.isoformat() if j.kubernetes_execution and j.kubernetes_execution.actual_start else None,
                "actual_end": j.kubernetes_execution.actual_end.isoformat() if j.kubernetes_execution and j.kubernetes_execution.actual_end else None,
            }
            res.append(item)
        return res
    except Exception as exc:
        logger.error(f"Error listing jobs: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while listing jobs.")


@router.get("/jobs/{job_id}")
def get_job_detail(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Get full details for a specific job with strict tenant isolation."""
    from app.api.tenant_scope import get_tenant_jobs
    job = get_tenant_jobs(db, identity=current_user, job_id=job_id)

    result = {
        "job_id": job.job_id,
        "name": job.workload_name,
        "team_id": job.team_id,
        "tenant_id": job.tenant_id,
        "company_name": job.company_name,
        "job_type": job.job_type,
        "priority": job.priority,
        "status": job.status,
        "submitted_at": job.submitted_at.isoformat(),
        "earliest_start_time": job.earliest_start_time.isoformat() if job.earliest_start_time else None,
        "deadline": job.deadline.isoformat(),
        "runtime_minutes": job.runtime_minutes,
        "power_kw": job.power_kw,
        "energy_kwh": job.energy_kwh,
        "deferrable": job.deferrable,
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
            "region_id": getattr(sd, "region_id", "IN-TG"),
            "tariff_plan": getattr(sd, "tariff_plan", None),
            "currency": getattr(sd, "currency", "USD"),
            "native_cost": getattr(sd, "native_cost", None),
            "baseline_native_cost": getattr(sd, "baseline_native_cost", None),
            "tariff_inr_per_kwh": sd.tariff_inr_per_kwh,
            "tariff_category": sd.tariff_category,
            "reason": sd.reason,
            "budget_remaining": sd.budget_remaining,
            "objective": getattr(sd, "scheduler_objective", "CARBON_FIRST") or "CARBON_FIRST",
            "scheduler_objective": getattr(sd, "scheduler_objective", "CARBON_FIRST") or "CARBON_FIRST",
            "candidates_evaluated": getattr(sd, "candidates_evaluated", 0) or 0,
            "feasible_candidates_count": getattr(sd, "feasible_candidates_count", 0) or 0,
            "rejection_summary": getattr(sd, "rejection_summary", {}) or {},
            "rejection_reasons": list((getattr(sd, "rejection_summary", {}) or {}).keys()),
            "deterministic_ranking": getattr(sd, "deterministic_rank", 1) or 1,
            "deterministic_rank": getattr(sd, "deterministic_rank", 1) or 1,
            "baseline_start": sd.baseline_start.isoformat() if sd.baseline_start else None,
            "baseline_end": sd.baseline_end.isoformat() if getattr(sd, "baseline_end", None) else None,
            "baseline_carbon_emission": sd.baseline_carbon_emission,
            "baseline_cost": sd.baseline_cost,
            "carbon_avoided": sd.carbon_avoided,
            "cost_difference": sd.cost_difference,
            "carbon_reduction_pct": getattr(sd, "carbon_reduction_pct", None),
            "cost_reduction_pct": getattr(sd, "cost_reduction_pct", None),
            "scheduling_delay_hours": getattr(sd, "scheduling_delay_hours", None),
            "sla_met": getattr(sd, "sla_met", True),
            "candidates": getattr(sd, "candidates_json", None),
            "rejected_candidates": getattr(sd, "rejected_candidates_json", None),
            "recommended_candidate": getattr(sd, "recommended_candidate_json", None),
        }

    if job.kubernetes_execution:
        try:
            from app.dispatch.dispatcher import refresh_job_status
            job.kubernetes_execution = refresh_job_status(db, job.kubernetes_execution)
        except Exception:
            pass
        ke = job.kubernetes_execution
        result["status"] = ke.gs_status
        result["kubernetes_job_name"] = ke.kubernetes_job_name
        result["pod_name"] = ke.pod_name or f"{ke.kubernetes_job_name}-pod"
        result["kubernetes"] = {
            "kubernetes_job_name": ke.kubernetes_job_name,
            "kubernetes_namespace": ke.kubernetes_namespace,
            "pod_name": ke.pod_name or f"{ke.kubernetes_job_name}-pod",
            "planned_start": ke.planned_start.isoformat(),
            "actual_start": ke.actual_start.isoformat() if ke.actual_start else None,
            "actual_end": ke.actual_end.isoformat() if ke.actual_end else None,
            "k8s_status": ke.k8s_status,
            "gs_status": ke.gs_status,
        }

    return result


@router.get("/jobs/{job_id}/history")
def get_job_history(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Get the complete operational lifecycle history and audit trail for a job with tenant isolation."""
    from app.api.tenant_scope import get_tenant_jobs
    job = get_tenant_jobs(db, identity=current_user, job_id=job_id)

    from app.trust.ledger import get_job_audit
    audit_trail = get_job_audit(db, job_id)

    detail = get_job_detail(job_id, db, current_user=current_user)
    detail["audit_events"] = [e.model_dump() for e in audit_trail]
    return detail


@router.post("/jobs/{job_id}/cancel", response_model=dict, summary="Cancel an active or pending workload")
def cancel_workload(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Cancel a job in SUBMITTED, VALIDATED, SCHEDULED, or PENDING_APPROVAL status.
    Enforces tenant isolation and RBAC authorization.
    """
    from app.api.tenant_scope import get_tenant_jobs
    from app.shared.auth import is_company_member
    job = get_tenant_jobs(db, identity=current_user, job_id=job_id)

    user_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if not is_company_member(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role lacks authorization to cancel workloads",
        )

    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job in terminal status '{job.status}'",
        )

    now = utcnow()
    job.status = JobStatus.CANCELLED
    job.updated_at = now
    if job.kubernetes_execution:
        job.kubernetes_execution.gs_status = JobStatus.CANCELLED
        job.kubernetes_execution.updated_at = now
    db.commit()

    try:
        from app.trust.ledger import append_event
        append_event(
            db,
            EventType.JOB_CANCELLED,
            job_id=job.job_id,
            payload={
                "cancelled_by": current_user.username,
                "role": user_role,
                "team_id": job.team_id,
                "tenant_id": job.tenant_id,
                "company_name": job.company_name,
                "reason": "Cancelled by authorized user",
            },
        )
    except Exception as exc:
        logger.warning(f"Failed to record audit event for job cancellation: {exc}")

    logger.info("Job %s CANCELLED by %s (%s)", job_id, current_user.username, user_role)
    return {
        "job_id": job_id,
        "status": JobStatus.CANCELLED.value,
        "message": f"Job {job_id} cancelled successfully",
    }


@router.get("/analytics/carbon/{region}")
def get_carbon_analytics(
    region: str,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Retrieve historical carbon intensity observations from PostgreSQL for analytics."""
    from app.shared.models import CarbonDataPointORM
    from app.ingest.regional_registry import resolve_region_id

    canonical_region = resolve_region_id(region)
    records = (
        db.query(CarbonDataPointORM)
        .filter(CarbonDataPointORM.region == canonical_region)
        .order_by(CarbonDataPointORM.timestamp.desc())
        .limit(limit)
        .all()
    )

    return {
        "region": canonical_region,
        "count": len(records),
        "history": [
            {
                "id": r.id,
                "timestamp_utc": r.timestamp.isoformat() if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc).isoformat(),
                "carbon_intensity": r.carbon_gco2_kwh,
                "source": r.source,
                "is_fallback": r.is_fallback,
                "created_at": r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in records
        ],
    }


# ─── Data sources status endpoint ─────────────────────────────────────────────

@router.get("/data-sources/status", response_model=dict)
def get_status(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Return status of all configured data sources without exposing secrets."""
    return get_ingest_status(db)


# ─── Regional Data Layer endpoints ────────────────────────────────────────────

@router.get("/regions", response_model=List[dict])
def list_regions_endpoint():
    """
    Return all supported regions with metadata, Electricity Maps zones,
    and tariff plans.
    """
    from app.ingest.regional_registry import list_supported_regions
    return [
        {
            "region_id": r.region_id,
            "country": r.country,
            "region_name": r.region_name,
            "timezone": r.timezone_name,
            "currency": r.currency,
            "electricity_maps_zone": r.electricity_maps_zone,
            "default_plan": r.default_plan,
            "supported_tariff_plans": [
                {
                    "plan_id": p.plan_id,
                    "display_name": p.display_name,
                    "description": p.description,
                    "is_industrial": p.is_industrial,
                    "is_commercial": p.is_commercial,
                    "is_flat": p.is_flat,
                    "default_rate": p.default_rate,
                }
                for p in r.plans.values()
            ],
            "aliases": r.aliases,
            "is_active": True,
        }
        for r in list_supported_regions()
    ]


@router.get("/regions/{region_id}", response_model=dict)
def get_region_endpoint(region_id: str):
    """Return resolved regional configuration for a given region or alias."""
    from app.ingest.regional_registry import get_region_config
    try:
        r = get_region_config(region_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "region_id": r.region_id,
        "country": r.country,
        "region_name": r.region_name,
        "timezone": r.timezone_name,
        "currency": r.currency,
        "electricity_maps_zone": r.electricity_maps_zone,
        "default_plan": r.default_plan,
        "supported_tariff_plans": [
            {
                "plan_id": p.plan_id,
                "display_name": p.display_name,
                "description": p.description,
                "is_industrial": p.is_industrial,
                "is_commercial": p.is_commercial,
                "is_flat": p.is_flat,
                "default_rate": p.default_rate,
            }
            for p in r.plans.values()
        ],
        "aliases": r.aliases,
        "is_active": True,
    }


@router.get("/regional/inventory", response_model=dict)
def get_regional_inventory_endpoint():
    """Return supported regions, active plans, and data source mappings."""
    from app.ingest.regional_tariff_loader import get_regional_tariff_inventory
    from app.ingest.regional_registry import list_supported_regions
    regions = [
        {
            "region_id": r.region_id,
            "country": r.country,
            "region_name": r.region_name,
            "timezone": r.timezone_name,
            "currency": r.currency,
            "em_zone": r.electricity_maps_zone,
            "plans": [p.display_name for p in r.plans.values()],
        }
        for r in list_supported_regions()
    ]
    return {
        "supported_regions": regions,
        "inventory": get_regional_tariff_inventory(),
    }


@router.get("/regional/tariffs", response_model=dict)
def get_regional_tariff_endpoint(
    region: str = Query("IN-TG", description="Grid region code (IN-TG, IN-GJ, IN-HP, IN-WB)"),
    tariff_plan: Optional[str] = Query(None, description="Tariff plan override"),
    job_type: Optional[str] = Query(None, description="Job type for plan resolution"),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
):
    """Fetch canonical regional tariff curve with full schema metadata."""
    from app.ingest.regional_tariff_loader import get_regional_tariff_curve
    now = utcnow()
    start = start or now
    end = end or (now + timedelta(hours=24))
    try:
        records = get_regional_tariff_curve(
            region=region,
            start_time=start,
            end_time=end,
            tariff_plan=tariff_plan,
            job_type=job_type,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "region_id": region,
        "data": [r.model_dump(mode="json") for r in records],
    }


# ─── Master ToD Tariff Endpoints ─────────────────────────────────────────────

@router.get("/tariffs/regions", response_model=dict)
def list_tariff_regions():
    """List all available regions and their metadata from the master ToD tariff dataset."""
    from app.shared.tariff_service import get_available_regions, get_currency_for_region
    from app.shared.timezone import get_region_timezone_name

    regions = []
    for reg_id in get_available_regions():
        tz = get_region_timezone_name(reg_id, default_tz="UTC")
        curr = get_currency_for_region(reg_id)
        regions.append({
            "region": reg_id,
            "region_id": reg_id,
            "timezone": tz,
            "currency": curr,
        })
    return {
        "count": len(regions),
        "regions": regions,
    }


@router.get("/tariffs/{region}", response_model=dict)
def get_region_hourly_tariffs(
    region: str,
    season: Optional[str] = Query(None, description="Optional season filter (e.g. Summer, Winter)"),
    date: Optional[datetime] = Query(None, description="Optional date for auto seasonal resolution (e.g. 2026-07-15T12:00:00Z)"),
):
    """Retrieve 24-hour tariff profile for a region from the master dataset."""
    from app.shared.tariff_service import (
        determine_season_for_region,
        get_currency_for_region,
        get_hourly_tariffs,
        validate_region,
    )
    if not validate_region(region):
        raise HTTPException(status_code=404, detail=f"Region '{region}' not found in master tariff dataset")

    resolved_season = season
    if not resolved_season and date is not None:
        resolved_season = determine_season_for_region(region, date)

    data = get_hourly_tariffs(region, season=resolved_season)
    currency = get_currency_for_region(region)
    active_season = data[0].get("season", "All-Year") if data else "All-Year"

    return {
        "region": region,
        "region_id": region,
        "currency": currency,
        "season": resolved_season or active_season,
        "tariffs": data,
    }


@router.get("/tariffs/{region}/current", response_model=dict)
def get_current_tariff(
    region: str,
    timestamp: Optional[datetime] = Query(None, description="Optional UTC timestamp (defaults to current time)"),
    season: Optional[str] = Query(None, description="Optional season override"),
):
    """
    Retrieve active tariff for a region at the current or specified UTC timestamp,
    correctly converted to regional local time.
    """
    from app.shared.tariff_service import (
        get_currency_for_region,
        get_tariff_for_region_and_time,
        validate_region,
    )
    if not validate_region(region):
        raise HTTPException(status_code=404, detail=f"Region '{region}' not found in master tariff dataset")
    ts = timestamp or utcnow()
    t_info = get_tariff_for_region_and_time(region, ts, season=season)
    currency = get_currency_for_region(region)

    return {
        "region": region,
        "region_id": region,
        "currency": currency,
        "current_tariff": {
            "utc_timestamp": t_info["utc_timestamp"].isoformat(),
            "local_timestamp": t_info["local_timestamp"].isoformat(),
            "local_hour": t_info["local_hour"],
            "timezone": t_info["timezone"],
            "time_interval": t_info["time_interval"],
            "time_of_day": t_info["time_of_day"],
            "base_charge": t_info["base_charge"],
            "adder_charge": t_info["adder_charge"],
            "effective_price": t_info["effective_price"],
            "currency": t_info["currency"],
            "tariff_type": t_info["tariff_type"],
            "season": t_info["season"],
            "price_per_kwh_usd": t_info["price_per_kwh_usd"],
        },
    }



# ─── Carbon data endpoints ────────────────────────────────────────────────────

@router.get("/carbon", response_model=dict)
def get_carbon_data_endpoint(
    region: str = Query(..., description="Grid region code"),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
):
    """Fetch carbon intensity curve for a region and time window."""
    now = utcnow()
    start = start or now
    end = end or (now + timedelta(hours=24))
    try:
        data = fetch_and_store_carbon(db, region, start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "region": region,
        "data": [
            {
                "timestamp": p.timestamp.isoformat(),
                "region": p.region,
                "carbon_gco2_kwh": p.carbon_gco2_kwh,
                "source": p.source,
                "em_zone": p.em_zone,
                "is_fallback": p.is_fallback,
            }
            for p in data
        ],
    }


@router.get("/carbon/current", response_model=dict)
def get_current_carbon_endpoint(
    region: str = Query("IN-TG", description="Grid region code"),
    db: Session = Depends(get_db),
):
    """Fetch the latest carbon reading for a specific region."""
    now = utcnow()
    try:
        data = fetch_and_store_carbon(db, region, now, now + timedelta(hours=1))
        if data:
            p = data[0]
            return {
                "region": region,
                "carbon_gco2_kwh": p.carbon_gco2_kwh,
                "timestamp": p.timestamp.isoformat(),
                "source": p.source,
                "is_fallback": p.is_fallback,
            }
    except Exception:
        pass
    return {
        "region": region,
        "carbon_gco2_kwh": 380.0,
        "timestamp": now.isoformat(),
        "source": "default",
        "is_fallback": True,
    }


# ─── Tariff data endpoints ────────────────────────────────────────────────────

@router.get("/tariff", response_model=dict)
def get_tariff_data_endpoint(
    region: str = Query(..., description="Grid region code"),
    job_type: Optional[str] = Query(None, description="Optional job type for tariff selection"),
    tariff_plan: Optional[str] = Query(None, description="Optional tariff plan override"),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
):
    """Fetch electricity tariff curve for a region and time window."""
    now = utcnow()
    start = start or now
    end = end or (now + timedelta(hours=24))
    try:
        data = fetch_and_store_tariff(db, region, start, end, job_type=job_type, tariff_plan=tariff_plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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


# ─── Dynamic Arrival Simulation Endpoint ──────────────────────────────────────

@router.post("/simulation/arrival/run", response_model=dict)
def run_dynamic_arrival_simulation_endpoint(
    speed: float = Query(60.0, description="Simulation speed multiplier (e.g. 60.0 = 1 real sec is 60 sim sec; <=0 for instant jump)"),
    max_jobs: Optional[int] = Query(None, description="Max jobs to simulate"),
    csv_path: Optional[str] = Query(None, description="Custom dataset path"),
    start_time: Optional[datetime] = Query(None, description="Simulation clock start time (UTC)"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(UserRole.PLATFORM_ADMIN, UserRole.COMPANY_ADMIN, UserRole.COMPANY_USER)),
):
    """
    Execute a dynamic workload arrival simulation run, releasing jobs chronologically
    by submit_time into the existing ingestion and decide pipeline.
    """
    from app.arrival.simulator import DynamicArrivalSimulator, SimulationConfig
    try:
        config = SimulationConfig(
            dataset_path=csv_path or "data/greenshift_workloads_final.csv",
            simulation_speed=speed,
            max_jobs=max_jobs,
            simulation_start_time=start_time,
            auto_schedule=True,
        )
        simulator = DynamicArrivalSimulator(config=config, db=db)
        summary = simulator.run(db=db)
        return summary.model_dump(mode="json")
    except Exception as exc:
        logger.error(f"Error running simulation: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred during arrival simulation execution.")

