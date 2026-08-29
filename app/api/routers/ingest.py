"""
Agent 1 — INGEST
FastAPI router — all ingest endpoints.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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


@router.post("/jobs/bulk-load", response_model=dict)
def bulk_load_jobs_from_csv(
    csv_path: Optional[str] = Query(None, description="Optional path to job CSV"),
    db: Session = Depends(get_db),
):
    """
    Bulk-load jobs from the configured or specified workload CSV file into the database.
    """
    count, errors = load_csv_jobs_to_db(db, csv_path=csv_path)
    return {
        "status": "success" if count > 0 or not errors else "partial",
        "jobs_loaded": count,
        "errors_count": len(errors),
        "errors": errors[:50],  # cap to top 50 error messages
    }


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


# ─── Data sources status endpoint ─────────────────────────────────────────────

@router.get("/data-sources/status", response_model=dict)
def get_status(db: Session = Depends(get_db)):
    """Return status of all configured data sources without exposing secrets."""
    return get_ingest_status(db)


# ─── Regional Data Layer endpoints ────────────────────────────────────────────

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
    records = get_regional_tariff_curve(
        region=region,
        start_time=start,
        end_time=end,
        tariff_plan=tariff_plan,
        job_type=job_type,
        db=db,
    )
    return {
        "region_id": region,
        "data": [r.model_dump(mode="json") for r in records],
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
    data = fetch_and_store_tariff(db, region, start, end, job_type=job_type, tariff_plan=tariff_plan)
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
):
    """
    Execute a dynamic workload arrival simulation run, releasing jobs chronologically
    by submit_time into the existing ingestion and decide pipeline.
    """
    from app.arrival.simulator import DynamicArrivalSimulator, SimulationConfig
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
