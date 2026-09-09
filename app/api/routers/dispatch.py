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

from app.shared.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/dispatch/{job_id}")
def trigger_dispatch(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Manually trigger Kubernetes dispatch for a scheduled job.
    Strictly validates tenant isolation, user authorization, job approval status, and schedule ownership.
    """
    from app.api.tenant_scope import get_tenant_jobs
    job = get_tenant_jobs(db, identity=current_user, job_id=job_id)

    try:
        execution = dispatch_job(db, job, user=current_user)
    except (DispatchPermissionError, DispatchBlockedError, DispatchError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Dispatch failed for job {job_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while dispatching the workload.")

    return {
        "job_id": job_id,
        "kubernetes_job_name": execution.kubernetes_job_name,
        "namespace": execution.kubernetes_namespace,
        "status": execution.gs_status,
        "gs_status": execution.gs_status,
        "pod_name": execution.pod_name or f"{execution.kubernetes_job_name}-pod",
    }


@router.get("/dispatch/{job_id}/status")
@router.get("/execution/{job_id}")
def get_dispatch_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Get the current Kubernetes execution status for a job with tenant isolation."""
    from app.api.tenant_scope import get_tenant_jobs
    job = get_tenant_jobs(db, identity=current_user, job_id=job_id)
    if job.kubernetes_execution is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} has not been dispatched yet")

    execution = job.kubernetes_execution
    try:
        execution = refresh_job_status(db, execution)
    except Exception as exc:
        logger.debug("Error refreshing live job status from k8s for %s: %s", job_id, exc)
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


@router.get("/dispatch/executions")
def list_dispatch_executions(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Retrieve all execution records."""
    from app.shared.models import KubernetesExecutionORM
    executions = db.query(KubernetesExecutionORM).order_by(KubernetesExecutionORM.created_at.desc()).limit(100).all()
    return [
        {
            "job_id": e.job_id,
            "execution_id": e.id,
            "kubernetes_job_name": e.kubernetes_job_name,
            "namespace": e.kubernetes_namespace,
            "pod_name": e.pod_name,
            "planned_start": e.planned_start.isoformat() if e.planned_start else None,
            "actual_start": e.actual_start.isoformat() if e.actual_start else None,
            "actual_end": e.actual_end.isoformat() if e.actual_end else None,
            "k8s_status": e.k8s_status,
            "gs_status": e.gs_status,
            "error_message": e.error_message,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "updated_at": e.updated_at.isoformat() if e.updated_at else None,
        }
        for e in executions
    ]


@router.get("/kubernetes/health")
def kubernetes_health(
    current_user: UserORM = Depends(get_current_user),
):
    """Check if the Kubernetes API is reachable."""
    available = check_kubernetes_available()
    return {
        "kubernetes_available": available,
        "namespace": "greenshift",
    }


@router.get("/kubernetes/state", response_model=dict)
def get_cluster_state(
    current_user: UserORM = Depends(get_current_user),
):
    """Return real-time Kubernetes cluster resources and node telemetry."""
    from app.dispatch.k8s_state_collector import collect_cluster_state
    try:
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
                    "cpu_used_cores": n.cpu_used_cores,
                    "cpu_free_cores": n.cpu_free_cores,
                    "memory_capacity_mib": n.memory_capacity_mib,
                    "memory_allocatable_mib": n.memory_allocatable_mib,
                    "memory_used_mib": n.memory_used_mib,
                    "memory_free_mib": n.memory_free_mib,
                    "gpu_capacity": n.gpu_capacity,
                    "gpu_allocatable": n.gpu_allocatable,
                    "gpu_used": n.gpu_used,
                    "gpu_free": n.gpu_free,
                    "roles": n.roles,
                }
                for n in snapshot.nodes
            ],
        }
    except Exception as exc:
        logger.error(f"Error collecting cluster state: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while collecting Kubernetes cluster telemetry.")


@router.get("/dispatch/workers")
def get_active_workers(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Show active dispatcher workers and their claim stats."""
    from sqlalchemy import func
    from app.shared.models import JobORM

    workers = (
        db.query(
            JobORM.claimed_by,
            func.count(JobORM.job_id).label("active_claims"),
            func.min(JobORM.claimed_at).label("oldest_claim"),
        )
        .filter(JobORM.status == JobStatus.CLAIMING)
        .filter(JobORM.claimed_by.isnot(None))
        .group_by(JobORM.claimed_by)
        .all()
    )

    return {
        "active_workers": [
            {
                "worker_id": w.claimed_by,
                "active_claims": w.active_claims,
                "oldest_claim": w.oldest_claim.isoformat() if w.oldest_claim else None,
            }
            for w in workers
        ],
        "dispatch_queue": {
            "ready": db.query(JobORM).filter(JobORM.status == JobStatus.READY).count(),
            "claiming": db.query(JobORM).filter(JobORM.status == JobStatus.CLAIMING).count(),
        },
    }

