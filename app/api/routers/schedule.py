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
    current_user: UserORM = Depends(
        require_roles(
            UserRole.ADMIN, UserRole.TEAM_LEAD, UserRole.OPERATOR,
            UserRole.COMPANY_ADMIN, UserRole.COMPANY_USER, UserRole.PLATFORM_ADMIN,
        )
    ),
):
    """
    Manually trigger scheduling for a specific job.
    Enforces tenant isolation and RBAC authorization.
    """
    from app.api.tenant_scope import get_tenant_jobs
    job = get_tenant_jobs(db, identity=current_user, job_id=job_id)

    if job.status not in (JobStatus.SUBMITTED,):
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is in status {job.status} — only SUBMITTED jobs can be scheduled",
        )
    try:
        decision = schedule_and_store(db, job)
    except ValueError as exc:
        if job.submitted_by_user_id:
            try:
                from app.notify.service import create_notification
                from app.shared.models import EventType
                create_notification(
                    db,
                    recipient_user_id=job.submitted_by_user_id,
                    event_type=EventType.JOB_SCHEDULED,
                    category="SCHEDULING",
                    severity="WARNING",
                    title=f"Workload {job.job_id} could not be scheduled",
                    message=f"No feasible execution window was found for workload '{job.job_id}': {exc}",
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    dedup_suffix="infeasible",
                    email_required=False,
                )
            except Exception as notify_exc:
                logger.warning("Notification failed for job %s infeasibility: %s", job_id, notify_exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error calculating schedule for job {job_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while calculating the workload schedule.")

    from app.shared.timezone import format_dual_time

    rec_cand = getattr(decision, "recommended_candidate", None) or getattr(decision, "recommended_candidate_json", None)
    if not rec_cand:
        rec_cand = {
            "slot_start": decision.selected_start.isoformat(),
            "slot_end": decision.selected_end.isoformat(),
            "carbon_intensity": decision.carbon_intensity,
            "carbon_emission": decision.carbon_emission,
            "electricity_cost": decision.electricity_cost,
            "rank": 1,
            "score": round(1.0 / (1.0 + (decision.carbon_emission or 0.0)), 4),
        }

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
        "recommended_candidate": rec_cand,
        "candidates": getattr(decision, "candidates", None) or getattr(decision, "candidates_json", None) or [rec_cand],
        "rejected_candidates": getattr(decision, "rejected_candidates", None) or getattr(decision, "rejected_candidates_json", None) or [],
    }


@router.get("/schedule/{job_id}")
@router.get("/schedule/{job_id}/explain")
def get_schedule_explainability(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Retrieve schedule decision and explainability details for a job with strict tenant isolation."""
    from app.api.tenant_scope import get_tenant_jobs
    job = get_tenant_jobs(db, identity=current_user, job_id=job_id)

    decision = job.schedule_decision
    if decision is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} has not been scheduled yet")

    from app.shared.timezone import format_dual_time

    rec_cand = getattr(decision, "recommended_candidate_json", None) or getattr(decision, "recommended_candidate", None)
    if not rec_cand:
        rec_cand = {
            "slot_start": decision.selected_start.isoformat(),
            "slot_end": decision.selected_end.isoformat(),
            "carbon_intensity": decision.carbon_intensity,
            "carbon_emission": decision.carbon_emission,
            "electricity_cost": decision.electricity_cost,
            "rank": 1,
            "score": round(1.0 / (1.0 + (decision.carbon_emission or 0.0)), 4),
        }

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
        "recommended_candidate": rec_cand,
        "candidates": getattr(decision, "candidates_json", None) or getattr(decision, "candidates", None) or [rec_cand],
        "rejected_candidates": getattr(decision, "rejected_candidates_json", None) or getattr(decision, "rejected_candidates", None) or [],
    }


