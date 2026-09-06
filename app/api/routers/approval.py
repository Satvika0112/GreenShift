"""
FastAPI Router — Human Approval Gate Endpoints.

Endpoints:
- POST /api/v1/approval/{job_id}/approve
- POST /api/v1/approval/{job_id}/decline
- GET  /api/v1/approval/{job_id}
- GET  /api/v1/approvals/pending
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.approval.service import (
    ApprovalNotFoundError,
    ApprovalPermissionError,
    ApprovalValidationError,
    approve_schedule,
    decline_schedule,
    get_job_approvals,
    get_pending_approvals,
)
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.models import (
    ApprovalRequest,
    ApprovalResponse,
    PendingApprovalItem,
    UserORM,
    UserRole,
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
    current_user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Explicitly approve a proposed schedule for a job.
    Enforces server-side RBAC authorization:
      - ADMIN: Full approval access across all teams.
      - TEAM_LEAD: Authorized only for jobs belonging to their own team.
      - OPERATOR / VIEWER: Forbidden (403).
    """
    try:
        approver = body.approved_by if body.approved_by and body.approved_by != "admin" else current_user.username
        return approve_schedule(
            db=db,
            job_id=job_id,
            schedule_id=body.schedule_id,
            reason=body.reason,
            approved_by=approver,
            user=current_user,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ApprovalValidationError, ApprovalPermissionError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except HTTPException:
        raise
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
    current_user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Decline a proposed schedule for a job.
    Enforces server-side RBAC authorization:
      - ADMIN: Full decline access across all teams.
      - TEAM_LEAD: Authorized only for jobs belonging to their own team.
      - OPERATOR / VIEWER: Forbidden (403).
    """
    try:
        decliner = body.approved_by if body.approved_by and body.approved_by != "admin" else current_user.username
        return decline_schedule(
            db=db,
            job_id=job_id,
            schedule_id=body.schedule_id,
            reason=body.reason,
            approved_by=decliner,
            user=current_user,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ApprovalValidationError, ApprovalPermissionError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Decline failed: {exc}")


@router.get(
    "/approvals/pending",
    response_model=List[PendingApprovalItem],
    summary="List all jobs pending approval",
)
@router.get(
    "/approval/pending",
    response_model=List[PendingApprovalItem],
    include_in_schema=False,
)
def api_get_pending_approvals(
    team_id: Optional[str] = Query(None, description="Filter pending approvals by team ID"),
    db: Session = Depends(get_db),
):
    """Retrieve all jobs waiting for human approval with proposed schedules."""
    return get_pending_approvals(db, team_id=team_id)


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
