"""
Agent 2 — DECIDE
Decision service — orchestrates scheduling for pending jobs.
Stores ScheduleDecision in DB and triggers dispatch.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.decide.scheduler import schedule_job
from app.ingest.data_sources import get_carbon_data, get_tariff_data
from app.ingest.jobs import update_job_status, get_job
from app.observability.metrics import (
    scheduler_jobs_total,
    scheduler_duration_seconds,
    scheduler_carbon_avoided_kg,
)
from app.shared.database import SessionLocal
from app.shared.models import (
    JobORM,
    JobStatus,
    ScheduleDecisionORM,
    ScheduleDecision,
)
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)


def schedule_and_store(db: Session, job: JobORM, record_audit: bool = False) -> ScheduleDecision:
    """
    Run the scheduler for a job and persist the ScheduleDecision.

    Args:
        db:           SQLAlchemy session
        job:          JobORM record to schedule
        record_audit: Whether to automatically record a JOB_SCHEDULED audit event

    Returns:
        ScheduleDecision pydantic model
    """
    now = utcnow()
    deadline = job.deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    # Fetch carbon + tariff data (API/CSV -> Mock priority)
    carbon_curve = get_carbon_data(job.region, now, deadline, db=db)
    tariff_curve = get_tariff_data(job.region, now, deadline, job_type=job.job_type)

    # Run scheduler with full dataset parameters
    start_time = time.monotonic()
    try:
        decision = schedule_job(
            job_id              = job.job_id,
            team_id             = job.team_id,
            deadline            = deadline,
            runtime_minutes     = job.runtime_minutes,
            power_kw            = job.power_kw,
            region              = job.region,
            carbon_curve        = carbon_curve,
            tariff_curve        = tariff_curve,
            carbon_budget_kg    = job.carbon_budget_kg,
            energy_kwh          = job.energy_kwh,
            earliest_start_time = job.earliest_start_time,
            deferrable          = job.deferrable,
            job_type            = job.job_type,
            tariff_plan         = getattr(job, "tariff_plan", None),
            cpu_request         = getattr(job, "cpu_request", "500m"),
            memory_request      = getattr(job, "memory_request", "512Mi"),
        )
        elapsed = time.monotonic() - start_time
        scheduler_jobs_total.labels(region=job.region, status="success").inc()
        scheduler_duration_seconds.observe(elapsed)
        if decision.carbon_avoided and decision.carbon_avoided > 0:
            scheduler_carbon_avoided_kg.labels(region=job.region).inc(decision.carbon_avoided)
    except Exception as exc:
        scheduler_jobs_total.labels(region=job.region, status="failed").inc()
        raise

    # Persist decision with regional & impact details (update if already exists)
    existing_sd = db.query(ScheduleDecisionORM).filter(ScheduleDecisionORM.job_id == decision.job_id).first()
    if existing_sd:
        existing_sd.selected_start           = decision.selected_start
        existing_sd.selected_end             = decision.selected_end
        existing_sd.carbon_intensity         = decision.carbon_intensity
        existing_sd.electricity_cost         = decision.electricity_cost
        existing_sd.carbon_emission          = decision.carbon_emission
        existing_sd.region_id                = decision.region_id
        existing_sd.tariff_plan              = decision.tariff_plan
        existing_sd.currency                 = decision.currency
        existing_sd.native_cost              = decision.native_cost
        existing_sd.baseline_native_cost     = decision.baseline_native_cost
        existing_sd.tariff_inr_per_kwh       = decision.tariff_inr_per_kwh
        existing_sd.tariff_category          = decision.tariff_category
        existing_sd.reason                   = decision.reason
        existing_sd.budget_remaining         = decision.budget_remaining
        existing_sd.created_at               = now
        existing_sd.baseline_start           = decision.baseline_start
        existing_sd.baseline_end             = decision.baseline_end
        existing_sd.baseline_carbon_emission = decision.baseline_carbon_emission
        existing_sd.baseline_cost            = decision.baseline_cost
        existing_sd.carbon_avoided           = decision.carbon_avoided
        existing_sd.cost_difference          = decision.cost_difference
        existing_sd.carbon_reduction_pct     = decision.carbon_reduction_pct
        existing_sd.cost_reduction_pct       = decision.cost_reduction_pct
        existing_sd.scheduling_delay_hours   = decision.scheduling_delay_hours
        existing_sd.sla_met                  = decision.sla_met
        existing_sd.candidates_evaluated      = decision.candidates_evaluated
        existing_sd.feasible_candidates_count = decision.feasible_candidates_count
        existing_sd.rejection_summary         = decision.rejection_summary
        existing_sd.scheduler_objective       = decision.scheduler_objective
        existing_sd.deterministic_rank        = decision.deterministic_rank
        existing_sd.scheduling_method         = decision.scheduling_method or "single_greedy"
        existing_sd.slot_utilization_pct      = decision.slot_utilization_pct
        existing_sd.demand_predicted          = decision.demand_predicted
        existing_sd.candidates_json          = decision.candidates
        existing_sd.rejected_candidates_json = decision.rejected_candidates
        existing_sd.recommended_candidate_json = decision.recommended_candidate
    else:
        orm = ScheduleDecisionORM(
            job_id                   = decision.job_id,
            selected_start           = decision.selected_start,
            selected_end             = decision.selected_end,
            carbon_intensity         = decision.carbon_intensity,
            electricity_cost         = decision.electricity_cost,
            carbon_emission          = decision.carbon_emission,
            region_id                = decision.region_id,
            tariff_plan              = decision.tariff_plan,
            currency                 = decision.currency,
            native_cost              = decision.native_cost,
            baseline_native_cost     = decision.baseline_native_cost,
            tariff_inr_per_kwh       = decision.tariff_inr_per_kwh,
            tariff_category          = decision.tariff_category,
            reason                   = decision.reason,
            budget_remaining         = decision.budget_remaining,
            created_at               = now,
            baseline_start           = decision.baseline_start,
            baseline_end             = decision.baseline_end,
            baseline_carbon_emission = decision.baseline_carbon_emission,
            baseline_cost            = decision.baseline_cost,
            carbon_avoided           = decision.carbon_avoided,
            cost_difference          = decision.cost_difference,
            carbon_reduction_pct     = decision.carbon_reduction_pct,
            cost_reduction_pct       = decision.cost_reduction_pct,
            scheduling_delay_hours   = decision.scheduling_delay_hours,
            sla_met                  = decision.sla_met,
            candidates_evaluated      = decision.candidates_evaluated,
            feasible_candidates_count = decision.feasible_candidates_count,
            rejection_summary         = decision.rejection_summary,
            scheduler_objective       = decision.scheduler_objective,
            deterministic_rank        = decision.deterministic_rank,
            scheduling_method         = decision.scheduling_method or "single_greedy",
            slot_utilization_pct      = decision.slot_utilization_pct,
            demand_predicted          = decision.demand_predicted,
            spilled_from_preferred    = decision.spilled_from_preferred or False,
            ml_advisor_used           = decision.ml_advisor_used or False,
            candidates_json          = decision.candidates,
            rejected_candidates_json = decision.rejected_candidates,
            recommended_candidate_json = decision.recommended_candidate,
        )
        db.add(orm)

    # Update job status: deferrable jobs require human approval; non-deferrable proceed to APPROVED
    if getattr(job, "deferrable", True) is False:
        job.status = JobStatus.APPROVED
    else:
        job.status = JobStatus.PENDING_APPROVAL
    job.updated_at = now
    db.commit()

    saved_sd = existing_sd or orm
    db.refresh(saved_sd)
    decision.id = saved_sd.id

    if job.status == JobStatus.PENDING_APPROVAL:
        try:
            from app.notify.service import create_notification, notify_users, resolve_platform_admin_user_ids, resolve_tenant_admin_user_ids
            from app.shared.models import EventType

            if job.submitted_by_user_id:
                create_notification(
                    db,
                    recipient_user_id=job.submitted_by_user_id,
                    event_type=EventType.SCHEDULE_PROPOSED,
                    category="SCHEDULING",
                    severity="INFO",
                    title=f"Workload {job.job_id} ready for approval",
                    message=(
                        f"A schedule for workload '{job.job_id}' is ready for review "
                        f"(carbon: {decision.carbon_emission:.4f} kg CO2, start: {decision.selected_start.isoformat()})."
                    ),
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    email_required=False,
                )

            # Notify only the users actually authorized to approve/decline this
            # job (app.approval.service.check_user_approval_permission: tenant's
            # COMPANY_ADMINs + all PLATFORM_ADMINs) — never the submitter alone,
            # and never anyone outside that real authorization set.
            approver_ids = set(resolve_tenant_admin_user_ids(db, job.tenant_id)) | set(resolve_platform_admin_user_ids(db))
            approver_ids.discard(job.submitted_by_user_id)
            if approver_ids:
                notify_users(
                    db,
                    recipient_user_ids=list(approver_ids),
                    event_type=EventType.SCHEDULE_PROPOSED,
                    category="APPROVAL",
                    severity="INFO",
                    title=f"Approval required — {job.job_id}",
                    message=(
                        f"Workload '{job.job_id}' has a proposed schedule awaiting your approval "
                        f"(carbon: {decision.carbon_emission:.4f} kg CO2, start: {decision.selected_start.isoformat()})."
                    ),
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    dedup_suffix="approver",
                    email_required=True,
                )
        except Exception as exc:
            logger.warning("Notification failed for job %s schedule-proposed: %s", decision.job_id, exc)

    # Record audit events if requested
    if record_audit:
        try:
            from app.trust.service import record_job_scheduled, record_schedule_proposed
            record_job_scheduled(
                db=db,
                job_id=decision.job_id,
                selected_start=decision.selected_start.isoformat(),
                carbon_emission=decision.carbon_emission,
                carbon_avoided=decision.carbon_avoided,
                budget_remaining=decision.budget_remaining,
            )
            # Add schedule proposed event with decision id
            sd_record = db.query(ScheduleDecisionORM).filter(ScheduleDecisionORM.job_id == decision.job_id).first()
            if sd_record:
                record_schedule_proposed(
                    db=db,
                    job_id=decision.job_id,
                    schedule_decision_id=sd_record.id,
                    selected_start=decision.selected_start.isoformat(),
                    carbon_emission=decision.carbon_emission,
                    electricity_cost=decision.electricity_cost,
                    region_id=decision.region_id,
                    tariff_plan=decision.tariff_plan,
                    deadline=job.deadline.isoformat() if job.deadline else None,
                )
        except Exception as exc:
            logger.warning("Audit record failed for job %s scheduling: %s", decision.job_id, exc)

    logger.info(
        "Scheduled job %s → %s | start=%s | carbon=%.4fkg | cost=$%.4f | avoided=%.4fkg",
        decision.job_id,
        job.status.value,
        decision.selected_start.isoformat(),
        decision.carbon_emission,
        decision.electricity_cost,
        decision.carbon_avoided or 0.0,
    )

    return decision


def schedule_batch_and_store(
    db: Session,
    jobs: List[JobORM],
    use_demand_forecast: bool = True,
    record_audit: bool = False,
) -> List[ScheduleDecision]:
    """
    Batch-schedule multiple jobs with capacity enforcement and optional ML demand forecast.
    Falls back to sequential schedule_and_store() if batch scheduling fails.

    This is the ADDITIONAL entry point for fleet experiments and bulk scheduling.
    The existing schedule_and_store() remains the entry point for single jobs.
    """
    if not jobs:
        return []

    try:
        from app.decide.batch_scheduler import schedule_batch
        from app.decide.demand_forecaster import DemandForecaster
        from app.decide.slot_capacity import SlotCapacityRegistry
        from app.dispatch.k8s_state_collector import collect_cluster_state

        cluster_state = collect_cluster_state()
        registry = SlotCapacityRegistry(cluster_state)

        forecaster = None
        if use_demand_forecast:
            try:
                forecaster = DemandForecaster()
                if not forecaster.load():
                    forecaster.train(db)
                if not forecaster.is_trained:
                    forecaster = None
            except Exception as exc:
                logger.warning("DemandForecaster initialization failed (%s) — proceeding with capacity scheduling", exc)
                forecaster = None

        decisions = schedule_batch(
            db=db,
            jobs=jobs,
            registry=registry,
            demand_forecaster=forecaster,
            use_demand_forecast=use_demand_forecast,
        )

        job_map = {j.job_id: j for j in jobs}
        now = utcnow()

        for decision in decisions:
            job = job_map.get(decision.job_id)
            if not job:
                continue

            existing_sd = db.query(ScheduleDecisionORM).filter(ScheduleDecisionORM.job_id == decision.job_id).first()
            if existing_sd:
                existing_sd.selected_start           = decision.selected_start
                existing_sd.selected_end             = decision.selected_end
                existing_sd.carbon_intensity         = decision.carbon_intensity
                existing_sd.electricity_cost         = decision.electricity_cost
                existing_sd.carbon_emission          = decision.carbon_emission
                existing_sd.region_id                = decision.region_id
                existing_sd.tariff_plan              = decision.tariff_plan
                existing_sd.currency                 = decision.currency
                existing_sd.native_cost              = decision.native_cost
                existing_sd.baseline_native_cost     = decision.baseline_native_cost
                existing_sd.tariff_inr_per_kwh       = decision.tariff_inr_per_kwh
                existing_sd.tariff_category          = decision.tariff_category
                existing_sd.reason                   = decision.reason
                existing_sd.budget_remaining         = decision.budget_remaining
                existing_sd.created_at               = now
                existing_sd.baseline_start           = decision.baseline_start
                existing_sd.baseline_end             = decision.baseline_end
                existing_sd.baseline_carbon_emission = decision.baseline_carbon_emission
                existing_sd.baseline_cost            = decision.baseline_cost
                existing_sd.carbon_avoided           = decision.carbon_avoided
                existing_sd.cost_difference          = decision.cost_difference
                existing_sd.carbon_reduction_pct     = decision.carbon_reduction_pct
                existing_sd.cost_reduction_pct       = decision.cost_reduction_pct
                existing_sd.scheduling_delay_hours   = decision.scheduling_delay_hours
                existing_sd.sla_met                  = decision.sla_met
                existing_sd.candidates_evaluated      = decision.candidates_evaluated
                existing_sd.feasible_candidates_count = decision.feasible_candidates_count
                existing_sd.rejection_summary         = decision.rejection_summary
                existing_sd.scheduler_objective       = decision.scheduler_objective
                existing_sd.deterministic_rank        = decision.deterministic_rank
                existing_sd.scheduling_method         = decision.scheduling_method or "batch_capacity_only"
                existing_sd.slot_utilization_pct      = decision.slot_utilization_pct
                existing_sd.demand_predicted          = decision.demand_predicted
                existing_sd.spilled_from_preferred    = decision.spilled_from_preferred or False
                existing_sd.ml_advisor_used           = decision.ml_advisor_used or False
            else:
                orm = ScheduleDecisionORM(
                    job_id                   = decision.job_id,
                    selected_start           = decision.selected_start,
                    selected_end             = decision.selected_end,
                    carbon_intensity         = decision.carbon_intensity,
                    electricity_cost         = decision.electricity_cost,
                    carbon_emission          = decision.carbon_emission,
                    region_id                = decision.region_id,
                    tariff_plan              = decision.tariff_plan,
                    currency                 = decision.currency,
                    native_cost              = decision.native_cost,
                    baseline_native_cost     = decision.baseline_native_cost,
                    tariff_inr_per_kwh       = decision.tariff_inr_per_kwh,
                    tariff_category          = decision.tariff_category,
                    reason                   = decision.reason,
                    budget_remaining         = decision.budget_remaining,
                    created_at               = now,
                    baseline_start           = decision.baseline_start,
                    baseline_end             = decision.baseline_end,
                    baseline_carbon_emission = decision.baseline_carbon_emission,
                    baseline_cost            = decision.baseline_cost,
                    carbon_avoided           = decision.carbon_avoided,
                    cost_difference          = decision.cost_difference,
                    carbon_reduction_pct     = decision.carbon_reduction_pct,
                    cost_reduction_pct       = decision.cost_reduction_pct,
                    scheduling_delay_hours   = decision.scheduling_delay_hours,
                    sla_met                  = decision.sla_met,
                    candidates_evaluated      = decision.candidates_evaluated,
                    feasible_candidates_count = decision.feasible_candidates_count,
                    rejection_summary         = decision.rejection_summary,
                    scheduler_objective       = decision.scheduler_objective,
                    deterministic_rank        = decision.deterministic_rank,
                    scheduling_method         = decision.scheduling_method or "batch_capacity_only",
                    slot_utilization_pct      = decision.slot_utilization_pct,
                    demand_predicted          = decision.demand_predicted,
                    spilled_from_preferred    = decision.spilled_from_preferred or False,
                    ml_advisor_used           = decision.ml_advisor_used or False,
                )
                db.add(orm)

            if getattr(job, "deferrable", True) is False:
                job.status = JobStatus.APPROVED
            else:
                job.status = JobStatus.PENDING_APPROVAL
            job.updated_at = now

        db.commit()

        # Update decision ids and optionally record audit events
        for decision in decisions:
            sd_rec = db.query(ScheduleDecisionORM).filter(ScheduleDecisionORM.job_id == decision.job_id).first()
            if sd_rec:
                decision.id = sd_rec.id

            if record_audit:
                try:
                    from app.trust.service import record_job_scheduled
                    record_job_scheduled(
                        db=db,
                        job_id=decision.job_id,
                        selected_start=decision.selected_start.isoformat(),
                        carbon_emission=decision.carbon_emission,
                        carbon_avoided=decision.carbon_avoided,
                        budget_remaining=decision.budget_remaining,
                    )
                except Exception as audit_exc:
                    logger.warning("Audit recording skipped for job %s: %s", decision.job_id, audit_exc)

        return decisions

    except Exception as exc:
        logger.error("Batch scheduling failed (%s) — falling back to sequential schedule_and_store()", exc)
        fallback_decisions = []
        for job in jobs:
            try:
                dec = schedule_and_store(db, job, record_audit=record_audit)
                fallback_decisions.append(dec)
            except Exception as single_exc:
                logger.error("Sequential fallback failed for job %s: %s", job.job_id, single_exc)
        return fallback_decisions


def process_pending_jobs(db: Session) -> int:
    """
    Find all SUBMITTED jobs and schedule them.
    Returns the number of jobs processed.
    """
    from app.ingest.jobs import get_jobs_awaiting_schedule

    pending = get_jobs_awaiting_schedule(db)
    count = 0
    for job in pending:
        try:
            schedule_and_store(db, job, record_audit=True)
            count += 1
        except Exception as exc:
            logger.error("Failed to schedule job %s: %s", job.job_id, exc)
            job.status = JobStatus.FAILED
            db.commit()
            if job.submitted_by_user_id:
                try:
                    from app.notify.service import create_notification
                    from app.shared.models import EventType
                    create_notification(
                        db,
                        recipient_user_id=job.submitted_by_user_id,
                        event_type=EventType.SCHEDULING_FAILED,
                        category="SCHEDULING",
                        severity="CRITICAL",
                        title=f"No feasible schedule for {job.job_id}",
                        message=(
                            f"GreenShift could not find an execution window for workload "
                            f"'{job.job_id}' that satisfies its deadline and constraints "
                            f"(e.g. carbon budget). The workload was marked FAILED."
                        ),
                        tenant_id=job.tenant_id,
                        job_id=job.job_id,
                        email_required=True,
                    )
                except Exception as notif_exc:
                    logger.warning("Notification failed for job %s scheduling failure: %s", job.job_id, notif_exc)

    return count


def run_decide_loop() -> None:
    """
    Long-running background process.
    Polls for newly submitted jobs and schedules them.
    """
    import time
    from app.shared.database import init_db

    # Retry DB initialisation — PostgreSQL may still be starting up
    for attempt in range(1, 16):
        try:
            init_db()
            logger.info("Database initialised successfully")
            break
        except Exception as exc:
            logger.warning(
                "DB not ready on attempt %d/15: %s — retrying in 4s", attempt, exc
            )
            time.sleep(4)
    else:
        logger.error("Database never became ready after 15 attempts — exiting")
        return

    poll_interval = 60
    logger.info("DECIDE service started — polling every %ds", poll_interval)
    while True:
        db = SessionLocal()
        try:
            count = process_pending_jobs(db)
            if count > 0:
                logger.info("Scheduled %d jobs", count)
        except Exception as exc:
            logger.error("DECIDE loop error: %s", exc)
        finally:
            db.close()
        time.sleep(poll_interval)


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    run_decide_loop()
