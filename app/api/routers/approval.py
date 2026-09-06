"""
FastAPI Router — Human Approval Gate Endpoints.

Endpoints:
- POST /api/v1/approval/{job_id}/approve
- POST /api/v1/approval/{job_id}/decline
- GET  /api/v1/approval/{job_id}
- GET  /api/v1/approvals/pending
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.approval.service import (
    ApprovalNotFoundError,
    ApprovalValidationError,
    approve_schedule,
    decline_schedule,
    get_job_approvals,
    get_pending_approvals,
)
from app.shared.database import get_db
from app.shared.models import (
    ApprovalRequest,
    ApprovalResponse,
    PendingApprovalItem,
)

router = APIRouter()


@router.post(
    "/approval/{job_id}/approve",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve proposed schedule",
)
@router.post(
    "/approvals/{job_id}/approve",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def api_approve_schedule(
    job_id: str,
    body: ApprovalRequest,
    db: Session = Depends(get_db),
):
    """
    Explicitly approve a proposed schedule for a job.
    Transitions job status from PENDING_APPROVAL to APPROVED.
    """
    try:
        return approve_schedule(
            db=db,
            job_id=job_id,
            schedule_id=body.schedule_id,
            reason=body.reason,
            approved_by=body.approved_by,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ApprovalValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Approval failed: {exc}")


@router.post(
    "/approval/{job_id}/decline",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Decline proposed schedule",
)
@router.post(
    "/approvals/{job_id}/decline",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def api_decline_schedule(
    job_id: str,
    body: ApprovalRequest,
    db: Session = Depends(get_db),
):
    """
    Decline a proposed schedule for a job.
    Transitions job status from PENDING_APPROVAL to DECLINED.
    Declined jobs will not be dispatched to Kubernetes.
    """
    try:
        return decline_schedule(
            db=db,
            job_id=job_id,
            schedule_id=body.schedule_id,
            reason=body.reason,
            approved_by=body.approved_by,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ApprovalValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Decline failed: {exc}")


@router.get(
    "/approval/{job_id}",
    response_model=List[ApprovalResponse],
    summary="Get approval history for a job",
)
@router.get(
    "/approvals/{job_id}",
    response_model=List[ApprovalResponse],
    include_in_schema=False,
)
def api_get_job_approvals(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Retrieve all approvals or declines recorded for a given job."""
    approvals = get_job_approvals(db, job_id)
    if not approvals:
        from app.ingest.jobs import get_job
        job = get_job(db, job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
    return [
        ApprovalResponse(
            id=a.id,
            job_id=a.job_id,
            schedule_decision_id=a.schedule_decision_id,
            decision=a.decision,
            job_status=a.job.status if a.job else "UNKNOWN",
            reason=a.reason,
            approved_by=a.approved_by,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in approvals
    ]


@router.get(
    "/approvals/pending",
    response_model=List[PendingApprovalItem],
    summary="List all jobs pending approval",
)
def api_get_pending_approvals(
    db: Session = Depends(get_db),
):
    """Retrieve all jobs waiting for human approval with proposed schedules."""
    return get_pending_approvals(db)
