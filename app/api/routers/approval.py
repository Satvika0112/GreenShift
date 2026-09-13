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
    get_approval_history,
    get_job_approvals,
    get_pending_approvals,
    resubmit_workload,
)
from app.shared.auth import get_current_user, is_company_admin, is_platform_admin
from app.shared.database import get_db
from app.shared.rate_limiter import limiter
from app.shared.models import (
    ApprovalHistoryItem,
    ApprovalORM,
    ApprovalRequest,
    ApprovalResponse,
    JobORM,
    PendingApprovalItem,
    UserORM,
    UserRole,
)
from app.shared.timezone import ensure_utc
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
    Enforces server-side RBAC and tenant authorization:
      - PLATFORM_ADMIN: Full approval access across all companies.
      - COMPANY_ADMIN: Authorized only for jobs belonging to their own company.
      - COMPANY_USER: Forbidden (403).
    """
    try:
        return approve_schedule(
            db=db,
            job_id=job_id,
            schedule_id=body.schedule_id,
            reason=body.reason,
            approved_by=current_user.username,
            user=current_user,
            request_id=getattr(request.state, "request_id", None),
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
    Requires a non-empty decline reason.
    Enforces server-side RBAC and tenant authorization:
      - PLATFORM_ADMIN: Full decline access across all companies.
      - COMPANY_ADMIN: Authorized only for jobs belonging to their own company.
      - COMPANY_USER: Forbidden (403).
    """
    try:
        return decline_schedule(
            db=db,
            job_id=job_id,
            schedule_id=body.schedule_id,
            reason=body.reason,
            approved_by=current_user.username,
            user=current_user,
            request_id=getattr(request.state, "request_id", None),
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


@router.post(
    "/approval/{job_id}/resubmit",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Resubmit a declined, cancelled, or failed workload",
)
@router.post(
    "/approvals/{job_id}/resubmit",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
@limiter.limit("30/minute")
def api_resubmit_workload(
    request: Request,
    job_id: str,
    current_user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Reset a DECLINED, CANCELLED, or FAILED workload back to SUBMITTED status so it can be re-scheduled.
    """
    try:
        job = resubmit_workload(
            db=db, job_id=job_id, user=current_user,
            request_id=getattr(request.state, "request_id", None),
        )
        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "message": f"Workload {job.job_id} successfully resubmitted for scheduling.",
        }
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ApprovalValidationError, ApprovalPermissionError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Resubmit failed for job {job_id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while resubmitting the workload.",
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
    tenant_id: Optional[str] = Query(None, description="Filter pending approvals by tenant ID (Platform Admin only)"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Retrieve all jobs waiting for human approval with proposed schedules and tenant isolation."""
    try:
        if is_platform_admin(current_user):
            effective_tenant_id = tenant_id
            effective_team_id = team_id
        else:
            effective_tenant_id = current_user.tenant_id
            # Company Admin sees every team in their company (may still
            # filter by a specific team_id); a plain Company User is locked
            # to their own team — same rule as app.api.tenant_scope.
            effective_team_id = team_id if is_company_admin(current_user) else current_user.team_id

        return get_pending_approvals(db, team_id=effective_team_id, tenant_id=effective_tenant_id)
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
    tenant_id: Optional[str] = Query(None, description="Filter declined approvals by tenant ID (Platform Admin only)"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Retrieve all declined workloads with tenant isolation."""
    try:
        query = (
            db.query(ApprovalORM)
            .join(ApprovalORM.job)
            .filter(ApprovalORM.decision == "DECLINED")
        )
        if is_platform_admin(current_user):
            if tenant_id:
                query = query.filter(JobORM.tenant_id == tenant_id)
            if team_id:
                query = query.filter(JobORM.team_id == team_id)
        else:
            if current_user.tenant_id:
                query = query.filter(JobORM.tenant_id == current_user.tenant_id)
            # Company Admin sees every team in their company; a plain
            # Company User is locked to their own team.
            if is_company_admin(current_user):
                if team_id:
                    query = query.filter(JobORM.team_id == team_id)
            elif current_user.team_id:
                query = query.filter(JobORM.team_id == current_user.team_id)

        approvals = query.order_by(ApprovalORM.created_at.desc()).all()
        return [
            {
                "job_id": a.job_id,
                "team_id": a.job.team_id if a.job else "N/A",
                "tenant_id": a.job.tenant_id if a.job else None,
                "company_name": a.job.company_name if a.job else None,
                "declined_at": ensure_utc(a.created_at).isoformat() if a.created_at else "",
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
    "/approvals/history",
    response_model=List[ApprovalHistoryItem],
    summary="List all decided (approved and declined) schedule approvals",
)
@router.get(
    "/approval/history",
    response_model=List[ApprovalHistoryItem],
    include_in_schema=False,
)
def api_get_approval_history(
    team_id: Optional[str] = Query(None, description="Filter approval history by team ID"),
    tenant_id: Optional[str] = Query(None, description="Filter approval history by tenant ID (Platform Admin only)"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Retrieve every decided (APPROVED or DECLINED) schedule, with the same tenant/team isolation as the pending queue."""
    try:
        if is_platform_admin(current_user):
            effective_tenant_id = tenant_id
            effective_team_id = team_id
        else:
            effective_tenant_id = current_user.tenant_id
            effective_team_id = team_id if is_company_admin(current_user) else current_user.team_id

        return get_approval_history(db, team_id=effective_team_id, tenant_id=effective_tenant_id)
    except Exception as exc:
        logger.error(f"Error fetching approval history: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving approval history.")


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
    """Retrieve all approvals or declines recorded for a given job with strict tenant isolation."""
    try:
        from app.api.tenant_scope import get_tenant_jobs
        job = get_tenant_jobs(db, identity=current_user, job_id=job_id)

        approvals = get_job_approvals(db, job_id)
        return [
            ApprovalResponse(
                id=a.id,
                job_id=a.job_id,
                schedule_decision_id=a.schedule_decision_id,
                decision=a.decision,
                job_status=job.status,
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

