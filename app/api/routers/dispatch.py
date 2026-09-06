"""
Agent 3 — DISPATCH
FastAPI router for dispatch endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dispatch.dispatcher import (
    dispatch_job,
    refresh_job_status,
    DispatchError,
    DispatchBlockedError,
    DispatchPermissionError,
)
from app.dispatch.kubernetes_client import check_kubernetes_available
from app.ingest.jobs import get_job
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.models import JobStatus, UserORM

router = APIRouter()


@router.post("/dispatch/{job_id}")
def trigger_dispatch(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Manually trigger Kubernetes dispatch for a scheduled job.
    Strictly validates user authorization, job approval status, and schedule ownership.
    """
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    try:
        execution = dispatch_job(db, job, user=current_user)
    except (DispatchPermissionError, DispatchBlockedError, DispatchError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "job_id": job_id,
        "kubernetes_job_name": execution.kubernetes_job_name,
        "namespace": execution.kubernetes_namespace,
        "status": execution.gs_status,
    }


@router.get("/dispatch/{job_id}/status")
@router.get("/execution/{job_id}")
def get_dispatch_status(job_id: str, db: Session = Depends(get_db)):
    """Get the current Kubernetes execution status for a job."""
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.kubernetes_execution is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} has not been dispatched yet")

    execution = job.kubernetes_execution
    try:
        execution = refresh_job_status(db, execution)
    except Exception:
        pass  # Return cached status if refresh fails

    return {
        "job_id": job_id,
        "execution_id": execution.id,
        "kubernetes_job_name": execution.kubernetes_job_name,
        "namespace": execution.kubernetes_namespace,
        "pod_name": execution.pod_name,
        "planned_start": execution.planned_start.isoformat(),
        "actual_start": execution.actual_start.isoformat() if execution.actual_start else None,
        "actual_end": execution.actual_end.isoformat() if execution.actual_end else None,
        "k8s_status": execution.k8s_status,
        "gs_status": execution.gs_status,
        "error_message": execution.error_message,
        "created_at": execution.created_at.isoformat() if execution.created_at else None,
        "updated_at": execution.updated_at.isoformat() if execution.updated_at else None,
    }


@router.get("/kubernetes/health")
def kubernetes_health():
    """Check if the Kubernetes API is reachable."""
    available = check_kubernetes_available()
    return {
        "kubernetes_available": available,
        "namespace": "greenshift",
    }


@router.get("/kubernetes/state", response_model=dict)
def get_cluster_state():
    """Return real-time Kubernetes cluster resources and node telemetry."""
    from app.dispatch.k8s_state_collector import collect_cluster_state
    snapshot = collect_cluster_state()
    return {
        "connected": snapshot.connected,
        "cluster_health": snapshot.cluster_health,
        "total_nodes": snapshot.total_nodes,
        "ready_nodes": snapshot.ready_nodes,
        "total_cpu_cores": snapshot.total_cpu_cores,
        "allocatable_cpu_cores": snapshot.allocatable_cpu_cores,
        "used_cpu_cores": snapshot.used_cpu_cores,
        "free_cpu_cores": snapshot.free_cpu_cores,
        "total_memory_mib": snapshot.total_memory_mib,
        "allocatable_memory_mib": snapshot.allocatable_memory_mib,
        "used_memory_mib": snapshot.used_memory_mib,
        "free_memory_mib": snapshot.free_memory_mib,
        "total_gpus": snapshot.total_gpus,
        "allocatable_gpus": snapshot.allocatable_gpus,
        "used_gpus": snapshot.used_gpus,
        "free_gpus": snapshot.free_gpus,
        "timestamp": snapshot.timestamp.isoformat(),
        "nodes": [
            {
                "name": n.name,
                "status": n.status,
                "cpu_capacity_cores": n.cpu_capacity_cores,
                "cpu_allocatable_cores": n.cpu_allocatable_cores,
                "memory_capacity_mib": n.memory_capacity_mib,
                "memory_allocatable_mib": n.memory_allocatable_mib,
                "gpu_capacity": n.gpu_capacity,
                "gpu_allocatable": n.gpu_allocatable,
                "roles": n.roles,
            }
            for n in snapshot.nodes
        ],
    }
