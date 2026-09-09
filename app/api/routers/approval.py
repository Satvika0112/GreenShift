"""
FastAPI Router — Human Approval Gate Endpoints.

Endpoints:
- POST /api/v1/approval/{job_id}/approve
- POST /api/v1/approval/{job_id}/decline
- GET  /api/v1/approval/{job_id}
- GET  /api/v1/approvals/pending
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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
from app.shared.rate_limiter import limiter
from app.shared.models import (
    ApprovalORM,
    ApprovalRequest,
    ApprovalResponse,
    JobORM,
    PendingApprovalItem,
    UserORM,
    UserRole,
)
from app.shared.utils import get_logger

logger = get_logger(__name__)

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
@limiter.limit("30/minute")
def api_approve_schedule(
    request: Request,
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
        return approve_schedule(
            db=db,
            job_id=job_id,
            schedule_id=body.schedule_id,
            reason=body.reason,
            approved_by=current_user.username,
            user=current_user,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ApprovalValidationError, ApprovalPermissionError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Approval failed for job {job_id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while approving the schedule.",
        )


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
@limiter.limit("30/minute")
def api_decline_schedule(
    request: Request,
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
        return decline_schedule(
            db=db,
            job_id=job_id,
            schedule_id=body.schedule_id,
            reason=body.reason,
            approved_by=current_user.username,
            user=current_user,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ApprovalValidationError, ApprovalPermissionError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Decline failed for job {job_id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while declining the schedule.",
        )


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
    current_user: UserORM = Depends(get_current_user),
):
    """Retrieve all jobs waiting for human approval with proposed schedules."""
    try:
        user_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        if user_role == UserRole.ADMIN.value:
            effective_team_id = team_id
        else:
            # Non-admin users must only receive pending approvals for current_user.team_id
            if not current_user.team_id:
                return []
            effective_team_id = current_user.team_id

        return get_pending_approvals(db, team_id=effective_team_id)
    except Exception as exc:
        logger.error(f"Error fetching pending approvals: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving pending approvals.")


@router.get(
    "/approvals/declined",
    summary="List all declined approvals",
)
@router.get(
    "/approval/declined",
    include_in_schema=False,
)
def api_get_declined_approvals(
    team_id: Optional[str] = Query(None, description="Filter declined approvals by team ID"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Retrieve all declined workloads."""
    try:
        query = (
            db.query(ApprovalORM)
            .join(ApprovalORM.job)
            .filter(ApprovalORM.decision == "DECLINED")
        )
        user_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        if user_role != UserRole.ADMIN.value:
            effective_team_id = current_user.team_id or ""
            query = query.filter(JobORM.team_id == effective_team_id)
        elif team_id:
            query = query.filter(JobORM.team_id == team_id)

        approvals = query.order_by(ApprovalORM.created_at.desc()).all()
        return [
            {
                "job_id": a.job_id,
                "team_id": a.job.team_id if a.job else "N/A",
                "declined_at": a.created_at.isoformat() if a.created_at else "",
                "declined_by": a.approved_by,
                "reason": a.reason,
                "status": "DECLINED",
            }
            for a in approvals
        ]
    except Exception as exc:
        logger.error(f"Error fetching declined approvals: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving declined approvals.")


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
    current_user: UserORM = Depends(get_current_user),
):
    """Retrieve all approvals or declines recorded for a given job."""
    try:
        from app.ingest.jobs import get_job
        job = get_job(db, job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")

        user_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        if user_role != UserRole.ADMIN.value:
            user_team = (current_user.team_id or "").strip().lower()
            job_team = (job.team_id or "").strip().lower()
            if not user_team or user_team != job_team:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access forbidden: User from team '{current_user.team_id}' cannot view approvals for job belonging to team '{job.team_id}'",
                )

        approvals = get_job_approvals(db, job_id)
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
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error retrieving job approvals for {job_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving job approvals.")

