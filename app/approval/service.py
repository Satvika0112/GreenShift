"""
GreenShift — Human Approval Gate Service.

Enforces server-side validation and audit ledger recording before Kubernetes dispatch.
No workload can transition to dispatch eligibility without explicit human approval.
"""

import logging
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.shared.models import (
    ApprovalHistoryItem,
    ApprovalORM,
    ApprovalResponse,
    JobORM,
    JobStatus,
    PendingApprovalItem,
    ScheduleDecisionORM,
    UserORM,
    UserRole,
)
from app.shared.timezone import to_regional_time
from app.shared.utils import utcnow
from app.shared.metrics import (
    record_approval_pending,
    record_approval_granted as metrics_record_approval_granted,
    record_approval_declined as metrics_record_approval_declined,
)
from app.trust.service import (
    record_approval_granted,
    record_approval_declined,
)

logger = logging.getLogger(__name__)


class ApprovalValidationError(ValueError):
    """Raised when an approval request fails validation (e.g. wrong status or mismatched schedule)."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ApprovalNotFoundError(ValueError):
    """Raised when the job or schedule decision does not exist."""
    def __init__(self, message: str):
        super().__init__(message)
        self.status_code = 404


class ApprovalPermissionError(ValueError):
    """Raised when a user lacks authorization to approve or decline a schedule."""
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


def check_user_approval_permission(job: JobORM, user: Optional[UserORM] = None) -> None:
    """
    Enforces server-side RBAC and tenant authorization rules:
      - PLATFORM_ADMIN: Full access to approve/decline any job across all companies.
      - COMPANY_ADMIN: Can approve/decline only jobs matching user's tenant_id.
      - COMPANY_USER: Cannot approve schedules (raises 403).
    """
    if user is None:
        return  # Service-level backwards compatibility if no user context is passed

    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    # Platform Admin has global permissions
    if user_role == UserRole.PLATFORM_ADMIN.value and not user.tenant_id:
        return

    # Company Admin — tenant-scoped, no team restriction
    if user_role in (UserRole.PLATFORM_ADMIN.value, UserRole.COMPANY_ADMIN.value):
        if user.tenant_id and job.tenant_id and user.tenant_id != job.tenant_id:
            # Cross-tenant access -> 404 (not 403) to avoid leaking job existence,
            # consistent with app.api.tenant_scope.get_tenant_jobs.
            raise ApprovalNotFoundError(f"Job '{job.job_id}' not found")
        return

    raise ApprovalPermissionError(
        f"Role '{user_role}' is not authorized to approve or decline schedules",
        status_code=403,
    )


def validate_approval_request(
    db: Session,
    job_id: str,
    schedule_id: int,
    target_decision: str,
) -> Tuple[JobORM, ScheduleDecisionORM]:
    """
    Validate that:
      1. Job exists.
      2. Schedule decision exists.
      3. Schedule decision belongs to this job.
      4. Job status is valid for approval (PENDING_APPROVAL, or idempotent already in target status).

    Returns (job, schedule_decision).
    """
    job = db.get(JobORM, job_id)
    if job is None:
        raise ApprovalNotFoundError(f"Job '{job_id}' not found")

    sd = db.get(ScheduleDecisionORM, schedule_id)
    if sd is None:
        raise ApprovalNotFoundError(f"Schedule decision with ID {schedule_id} not found")

    if sd.job_id != job_id:
        raise ApprovalValidationError(
            f"Schedule decision {schedule_id} belongs to job '{sd.job_id}', not '{job_id}'",
            status_code=400,
        )

    return job, sd


def approve_schedule(
    db: Session,
    job_id: str,
    schedule_id: int,
    reason: Optional[str] = None,
    approved_by: Optional[str] = "admin",
    user: Optional[UserORM] = None,
    request_id: Optional[str] = None,
) -> ApprovalResponse:
    """
    Approve a proposed schedule for a job.

    Transitions job status: PENDING_APPROVAL -> APPROVED.
    Idempotent: If already APPROVED for this schedule, returns the existing approval.
    """
    job, sd = validate_approval_request(db, job_id, schedule_id, "APPROVED")
    check_user_approval_permission(job, user)

    # Idempotency check: if already approved for this schedule, return existing
    existing_approval = (
        db.query(ApprovalORM)
        .filter(
            ApprovalORM.job_id == job_id,
            ApprovalORM.schedule_decision_id == schedule_id,
            ApprovalORM.decision == "APPROVED",
        )
        .order_by(ApprovalORM.created_at.desc())
        .first()
    )
    if job.status == JobStatus.APPROVED and existing_approval:
        logger.info("Job %s is already approved for schedule %d — returning existing approval", job_id, schedule_id)
        return ApprovalResponse(
            id=existing_approval.id,
            job_id=job.job_id,
            schedule_decision_id=sd.id,
            decision="APPROVED",
            job_status=job.status,
            reason=existing_approval.reason,
            approved_by=existing_approval.approved_by,
            created_at=existing_approval.created_at,
            updated_at=existing_approval.updated_at,
        )

    # Valid status check
    if job.status != JobStatus.PENDING_APPROVAL and job.status != JobStatus.APPROVED:
        raise ApprovalValidationError(
            f"Cannot approve job '{job_id}' in status '{job.status}'. Only PENDING_APPROVAL jobs can be approved.",
            status_code=400,
        )

    now = utcnow()
    approval = ApprovalORM(
        job_id=job.job_id,
        schedule_decision_id=sd.id,
        decision="APPROVED",
        reason=reason or "Schedule acceptable",
        approved_by=approved_by or "admin",
        created_at=now,
        updated_at=now,
    )
    db.add(approval)

    # Atomic conditional transition: only succeeds if the job is still
    # PENDING_APPROVAL. Guards against a concurrent approve/decline race —
    # if another request already transitioned this job, rowcount is 0 and
    # we abort instead of silently overwriting a contradictory decision.
    rows_updated = (
        db.query(JobORM)
        .filter(JobORM.job_id == job.job_id, JobORM.status == JobStatus.PENDING_APPROVAL)
        .update({"status": JobStatus.APPROVED, "updated_at": now}, synchronize_session=False)
    )
    if rows_updated == 0:
        db.rollback()
        raise ApprovalValidationError(
            f"Job '{job_id}' was concurrently modified by another approval decision. Refresh and retry.",
            status_code=409,
        )

    db.commit()
    db.refresh(approval)
    db.refresh(job)

    # Record metrics
    metrics_record_approval_granted()

    # Record audit event in hash-chain ledger
    try:
        record_approval_granted(
            db=db,
            job_id=job.job_id,
            schedule_decision_id=sd.id,
            decision="APPROVED",
            approved_by=approved_by or "admin",
            reason=approval.reason,
            timestamp=now.isoformat(),
            tenant_id=job.tenant_id, team_id=job.team_id, actor=user, request_id=request_id,
        )
    except Exception as exc:
        logger.warning("Audit record failed for job %s approval: %s", job.job_id, exc)

    if job.submitted_by_user_id:
        try:
            from app.notify.service import create_notification
            from app.shared.models import EventType
            create_notification(
                db,
                recipient_user_id=job.submitted_by_user_id,
                event_type=EventType.APPROVAL_GRANTED,
                category="APPROVAL",
                severity="INFO",
                title=f"Workload {job.job_id} approved",
                message=f"Schedule for workload '{job.job_id}' was approved by {approved_by or 'admin'}.",
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                email_required=True,
            )
        except Exception as exc:
            logger.warning("Notification failed for job %s approval: %s", job.job_id, exc)

    logger.info(
        "Job %s schedule %d APPROVED by %s (selected_start: %s UTC)",
        job_id,
        schedule_id,
        approved_by,
        sd.selected_start.isoformat(),
    )

    return ApprovalResponse(
        id=approval.id,
        job_id=job.job_id,
        schedule_decision_id=sd.id,
        decision="APPROVED",
        job_status=job.status,
        reason=approval.reason,
        approved_by=approval.approved_by,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
    )


def decline_schedule(
    db: Session,
    job_id: str,
    schedule_id: int,
    reason: Optional[str] = None,
    approved_by: Optional[str] = "admin",
    user: Optional[UserORM] = None,
    request_id: Optional[str] = None,
) -> ApprovalResponse:
    """
    Decline a proposed schedule for a job.

    Transitions job status: PENDING_APPROVAL -> DECLINED.
    DECLINED is a business decision, not a technical failure.
    No Kubernetes job will be dispatched.
    """
    if not reason or not reason.strip():
        raise ApprovalValidationError(
            "A non-empty decline reason is required to decline a workload schedule.",
            status_code=400,
        )

    job, sd = validate_approval_request(db, job_id, schedule_id, "DECLINED")
    check_user_approval_permission(job, user)

    # Idempotency check
    existing_decline = (
        db.query(ApprovalORM)
        .filter(
            ApprovalORM.job_id == job_id,
            ApprovalORM.schedule_decision_id == schedule_id,
            ApprovalORM.decision == "DECLINED",
        )
        .order_by(ApprovalORM.created_at.desc())
        .first()
    )
    if job.status == JobStatus.DECLINED and existing_decline:
        logger.info("Job %s is already declined for schedule %d — returning existing decline", job_id, schedule_id)
        return ApprovalResponse(
            id=existing_decline.id,
            job_id=job.job_id,
            schedule_decision_id=sd.id,
            decision="DECLINED",
            job_status=job.status,
            reason=existing_decline.reason,
            approved_by=existing_decline.approved_by,
            created_at=existing_decline.created_at,
            updated_at=existing_decline.updated_at,
        )

    if job.status != JobStatus.PENDING_APPROVAL and job.status != JobStatus.DECLINED:
        raise ApprovalValidationError(
            f"Cannot decline job '{job_id}' in status '{job.status}'. Only PENDING_APPROVAL jobs can be declined.",
            status_code=400,
        )

    now = utcnow()
    approval = ApprovalORM(
        job_id=job.job_id,
        schedule_decision_id=sd.id,
        decision="DECLINED",
        reason=reason.strip(),
        approved_by=approved_by or "admin",
        created_at=now,
        updated_at=now,
    )
    db.add(approval)

    # Atomic conditional transition — see approve_schedule() for rationale.
    rows_updated = (
        db.query(JobORM)
        .filter(JobORM.job_id == job.job_id, JobORM.status == JobStatus.PENDING_APPROVAL)
        .update({"status": JobStatus.DECLINED, "updated_at": now}, synchronize_session=False)
    )
    if rows_updated == 0:
        db.rollback()
        raise ApprovalValidationError(
            f"Job '{job_id}' was concurrently modified by another approval decision. Refresh and retry.",
            status_code=409,
        )

    db.commit()
    db.refresh(approval)
    db.refresh(job)

    # Record metrics
    metrics_record_approval_declined()

    # Record audit event
    try:
        record_approval_declined(
            db=db,
            job_id=job.job_id,
            schedule_decision_id=sd.id,
            decision="DECLINED",
            approved_by=approved_by or "admin",
            reason=approval.reason,
            timestamp=now.isoformat(),
            tenant_id=job.tenant_id, team_id=job.team_id, actor=user, request_id=request_id,
        )
    except Exception as exc:
        logger.warning("Audit record failed for job %s decline: %s", job.job_id, exc)

    if job.submitted_by_user_id:
        try:
            from app.notify.service import create_notification
            from app.shared.models import EventType
            create_notification(
                db,
                recipient_user_id=job.submitted_by_user_id,
                event_type=EventType.APPROVAL_DECLINED,
                category="APPROVAL",
                severity="WARNING",
                title=f"Workload {job.job_id} declined",
                message=f"Schedule for workload '{job.job_id}' was declined by {approved_by or 'admin'}. Reason: {approval.reason}",
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                email_required=True,
            )
        except Exception as exc:
            logger.warning("Notification failed for job %s decline: %s", job.job_id, exc)

    logger.info("Job %s schedule %d DECLINED by %s (reason: %s)", job_id, schedule_id, approved_by, approval.reason)

    return ApprovalResponse(
        id=approval.id,
        job_id=job.job_id,
        schedule_decision_id=sd.id,
        decision="DECLINED",
        job_status=job.status,
        reason=approval.reason,
        approved_by=approval.approved_by,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
    )


def resubmit_workload(
    db: Session,
    job_id: str,
    user: Optional[UserORM] = None,
    request_id: Optional[str] = None,
) -> JobORM:
    """
    Resubmit a workload that was previously DECLINED, CANCELLED, or FAILED.
    Transitions status back to SUBMITTED and removes stale decision.
    """
    job = db.get(JobORM, job_id)
    if not job:
        raise ApprovalNotFoundError(f"Job '{job_id}' not found")

    check_user_approval_permission(job, user)

    if job.status not in (JobStatus.DECLINED, JobStatus.CANCELLED, JobStatus.FAILED):
        raise ApprovalValidationError(
            f"Cannot resubmit job '{job_id}' in status '{job.status}'. Only DECLINED, CANCELLED, or FAILED jobs can be resubmitted.",
            status_code=400,
        )

    now = utcnow()
    job.status = JobStatus.SUBMITTED
    job.updated_at = now
    # Detach previous schedule decision so scheduler can re-evaluate
    if job.schedule_decision:
        db.delete(job.schedule_decision)
    db.commit()
    db.refresh(job)

    try:
        from app.trust.ledger import append_event
        from app.shared.models import EventType
        append_event(
            db,
            EventType.JOB_SUBMITTED,
            job_id=job.job_id,
            payload={
                "action": "RESUBMITTED",
                "resubmitted_by": user.username if user else "admin",
                "tenant_id": job.tenant_id,
                "company_name": job.company_name,
                "team_id": job.team_id,
            },
            actor=user, tenant_id=job.tenant_id, team_id=job.team_id,
            request_id=request_id, source_service="approval",
        )
    except Exception as exc:
        logger.warning("Audit record failed for job %s resubmission: %s", job.job_id, exc)

    logger.info("Job %s RESUBMITTED by %s", job_id, user.username if user else "admin")
    return job


def get_job_approvals(db: Session, job_id: str) -> List[ApprovalORM]:
    """Retrieve all approval/decline history for a specific job."""
    return (
        db.query(ApprovalORM)
        .filter(ApprovalORM.job_id == job_id)
        .order_by(ApprovalORM.created_at.desc())
        .all()
    )


def get_approval_history(
    db: Session,
    team_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> List[ApprovalHistoryItem]:
    """
    Retrieve all decided (APPROVED or DECLINED) schedule approvals, most
    recent first, with the same tenant/team isolation as
    get_pending_approvals(). Reuses the existing ApprovalORM ledger — no new
    storage, no separate audit trail.
    """
    query = db.query(ApprovalORM).join(ApprovalORM.job)
    if tenant_id:
        query = query.filter(JobORM.tenant_id == tenant_id)
    if team_id:
        query = query.filter(JobORM.team_id == team_id)

    approvals = query.order_by(ApprovalORM.created_at.desc()).all()

    items: List[ApprovalHistoryItem] = []
    for a in approvals:
        job = a.job
        sd = a.schedule_decision
        items.append(
            ApprovalHistoryItem(
                job_id=a.job_id,
                workload_name=job.workload_name if job else None,
                decision=a.decision,
                team_id=job.team_id if job else None,
                tenant_id=job.tenant_id if job else None,
                region=job.region if job else None,
                scheduled_start_utc=sd.selected_start if sd else None,
                decided_by=a.approved_by,
                decided_at=a.created_at,
                reason=a.reason,
            )
        )
    return items


def get_pending_approvals(
    db: Session,
    team_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> List[PendingApprovalItem]:
    """
    Retrieve all jobs currently awaiting human approval (status == PENDING_APPROVAL)
    with their schedule decisions and converted local/UTC timestamps.
    Optionally filters by team_id and/or tenant_id.
    """
    query = (
        db.query(JobORM)
        .join(JobORM.schedule_decision)
        .filter(JobORM.status == JobStatus.PENDING_APPROVAL)
    )
    if tenant_id:
        query = query.filter(JobORM.tenant_id == tenant_id)
    if team_id:
        query = query.filter(JobORM.team_id == team_id)

    jobs = query.order_by(JobORM.submitted_at.desc()).all()

    items: List[PendingApprovalItem] = []
    for j in jobs:
        sd = j.schedule_decision
        if not sd:
            continue

        start_local = to_regional_time(sd.selected_start, region=j.region, timezone_name=j.timezone)
        end_local = to_regional_time(sd.selected_end, region=j.region, timezone_name=j.timezone)
        deadline_local = to_regional_time(j.deadline, region=j.region, timezone_name=j.timezone)
        baseline_start = getattr(sd, "baseline_start", None)
        baseline_start_local = (
            to_regional_time(baseline_start, region=j.region, timezone_name=j.timezone)
            if baseline_start
            else None
        )

        items.append(
            PendingApprovalItem(
                job_id=j.job_id,
                workload_name=j.workload_name,
                team_id=j.team_id,
                region=j.region,
                timezone=j.timezone or "Asia/Kolkata",
                schedule_id=sd.id,
                selected_start_utc=sd.selected_start,
                selected_start_local=start_local,
                selected_end_utc=sd.selected_end,
                selected_end_local=end_local,
                runtime_minutes=j.runtime_minutes,
                power_kw=j.power_kw,
                carbon_intensity=sd.carbon_intensity,
                carbon_emission_kg=sd.carbon_emission,
                electricity_cost_usd=sd.electricity_cost,
                deadline_utc=j.deadline,
                deadline_local=deadline_local,
                status=j.status,
                tariff_plan=sd.tariff_plan,
                scheduler_objective=getattr(sd, "scheduler_objective", "CARBON_FIRST") or "CARBON_FIRST",
                objective=getattr(sd, "scheduler_objective", "CARBON_FIRST") or "CARBON_FIRST",
                reason=sd.reason,
                job_type=j.job_type,
                priority=j.priority,
                candidates_evaluated=getattr(sd, "candidates_evaluated", 0) or 0,
                feasible_candidates_count=getattr(sd, "feasible_candidates_count", 0) or 0,
                rejection_summary=getattr(sd, "rejection_summary", {}) or {},
                rejection_reasons=list((getattr(sd, "rejection_summary", {}) or {}).keys()),
                deterministic_ranking=getattr(sd, "deterministic_rank", 1) or 1,
                deterministic_rank=getattr(sd, "deterministic_rank", 1) or 1,
                carbon_budget_kg=j.carbon_budget_kg,
                currency=getattr(sd, "currency", None) or "USD",
                native_cost=getattr(sd, "native_cost", None),
                baseline_carbon_emission_kg=getattr(sd, "baseline_carbon_emission", None),
                baseline_cost_usd=getattr(sd, "baseline_cost", None),
                baseline_native_cost=getattr(sd, "baseline_native_cost", None),
                baseline_start_utc=baseline_start,
                baseline_start_local=baseline_start_local,
                carbon_avoided_kg=getattr(sd, "carbon_avoided", None),
                cost_difference_usd=getattr(sd, "cost_difference", None),
                carbon_reduction_pct=getattr(sd, "carbon_reduction_pct", None),
                sla_met=getattr(sd, "sla_met", None),
            )
        )

    record_approval_pending(len(items))
    return items
