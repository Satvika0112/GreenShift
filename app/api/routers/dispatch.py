"""
Agent 3 — DISPATCH
FastAPI router for dispatch endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dispatch.dispatcher import dispatch_job, refresh_job_status, DispatchError
from app.dispatch.kubernetes_client import check_kubernetes_available
from app.ingest.jobs import get_job
from app.shared.database import get_db
from app.shared.models import JobStatus

router = APIRouter()


@router.post("/dispatch/{job_id}")
def trigger_dispatch(job_id: str, db: Session = Depends(get_db)):
    """
    Manually trigger Kubernetes dispatch for a scheduled job.
    Normally triggered automatically by the DISPATCH background service.
    """
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status != JobStatus.SCHEDULED:
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is in status {job.status} — only SCHEDULED jobs can be dispatched",
        )
    try:
        execution = dispatch_job(db, job)
    except DispatchError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "job_id": job_id,
        "kubernetes_job_name": execution.kubernetes_job_name,
        "namespace": execution.kubernetes_namespace,
        "status": execution.gs_status,
    }


@router.get("/dispatch/{job_id}/status")
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
        "kubernetes_job_name": execution.kubernetes_job_name,
        "namespace": execution.kubernetes_namespace,
        "pod_name": execution.pod_name,
        "planned_start": execution.planned_start.isoformat(),
        "actual_start": execution.actual_start.isoformat() if execution.actual_start else None,
        "actual_end": execution.actual_end.isoformat() if execution.actual_end else None,
        "k8s_status": execution.k8s_status,
        "gs_status": execution.gs_status,
        "error_message": execution.error_message,
    }


@router.get("/kubernetes/health")
def kubernetes_health():
    """Check if the Kubernetes API is reachable."""
    available = check_kubernetes_available()
    return {
        "kubernetes_available": available,
        "namespace": "greenshift",
    }
