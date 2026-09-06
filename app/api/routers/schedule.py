"""
Agent 2 — DECIDE
FastAPI router for schedule endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.decide.service import schedule_and_store
from app.ingest.jobs import get_job
from app.shared.database import get_db
from app.shared.auth import get_current_user, require_roles
from app.shared.models import JobStatus, UserORM, UserRole
from app.shared.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/schedule/{job_id}")
def trigger_schedule(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(UserRole.ADMIN, UserRole.TEAM_LEAD, UserRole.OPERATOR)),
):
    """
    Manually trigger scheduling for a specific job.
    Normally scheduling is triggered automatically by the DECIDE background loop.
    Enforces RBAC: ADMIN, TEAM_LEAD (own team only), OPERATOR.
    """
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    user_role_val = current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role)
    if user_role_val == "TEAM_LEAD" and current_user.team_id:
        if job.team_id and job.team_id != current_user.team_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Team lead for team '{current_user.team_id}' cannot schedule jobs for team '{job.team_id}'",
            )

    if job.status not in (JobStatus.SUBMITTED,):
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is in status {job.status} — only SUBMITTED jobs can be scheduled",
        )
    try:
        decision = schedule_and_store(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error calculating schedule for job {job_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while calculating the workload schedule.")

    from app.shared.timezone import format_dual_time

    return {
        "id": decision.id,
        "schedule_id": decision.id,
        "job_id": decision.job_id,
        "selected_start": decision.selected_start.isoformat(),
        "selected_end": decision.selected_end.isoformat(),
        "carbon_intensity": decision.carbon_intensity,
        "electricity_cost": decision.electricity_cost,
        "carbon_emission": decision.carbon_emission,
        "region_id": decision.region_id,
        "tariff_plan": decision.tariff_plan,
        "currency": decision.currency,
        "native_cost": decision.native_cost,
        "baseline_native_cost": decision.baseline_native_cost,
        "reason": decision.reason,
        "budget_remaining": decision.budget_remaining,
        "objective": decision.scheduler_objective or "CARBON_FIRST",
        "scheduler_objective": decision.scheduler_objective or "CARBON_FIRST",
        "candidates_evaluated": getattr(decision, "candidates_evaluated", 0) or 0,
        "feasible_candidates_count": getattr(decision, "feasible_candidates_count", 0) or 0,
        "rejection_summary": getattr(decision, "rejection_summary", {}) or {},
        "rejection_reasons": getattr(decision, "rejection_reasons", []) or [],
        "deterministic_ranking": getattr(decision, "deterministic_rank", 1) or 1,
        "deterministic_rank": getattr(decision, "deterministic_rank", 1) or 1,
        "baseline_start": decision.baseline_start.isoformat() if decision.baseline_start else None,
        "baseline_end": decision.baseline_end.isoformat() if decision.baseline_end else None,
        "carbon_avoided": decision.carbon_avoided,
        "cost_difference": decision.cost_difference,
        "carbon_reduction_pct": decision.carbon_reduction_pct,
        "cost_reduction_pct": decision.cost_reduction_pct,
        "scheduling_delay_hours": decision.scheduling_delay_hours,
        "sla_met": decision.sla_met,
        "time_details": {
            "selected_start": format_dual_time(decision.selected_start, region=decision.region_id),
            "selected_end": format_dual_time(decision.selected_end, region=decision.region_id),
        },
    }

