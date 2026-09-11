"""
Agent 3 — DISPATCH
Core dispatcher — creates Kubernetes Jobs at the scheduled time.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from kubernetes.client.rest import ApiException
from sqlalchemy.orm import Session

from app.dispatch.job_builder import build_kubernetes_job
from app.dispatch.k8s_state_collector import (
    collect_cluster_state,
    _parse_cpu_string,
    _parse_memory_string,
)
from app.dispatch.kubernetes_client import get_batch_v1, get_core_v1, check_kubernetes_available
from app.dispatch.status_tracker import (
    get_job_status,
    get_pod_name,
    get_pod_start_time,
    get_job_completion_time,
)
from app.shared.config import settings
from app.shared.metrics import (
    record_dispatch_attempt as metrics_record_dispatch_attempt,
    record_dispatch_success as metrics_record_dispatch_success,
    record_dispatch_blocked as metrics_record_dispatch_blocked,
    record_dispatch_failure as metrics_record_dispatch_failure,
)
from app.shared.models import (
    JobORM,
    JobStatus,
    KubernetesExecutionORM,
    ScheduleDecisionORM,
)
from app.shared.utils import utcnow, k8s_safe_name

logger = logging.getLogger(__name__)


class DispatchError(Exception):
    """Raised when the dispatcher cannot create a Kubernetes Job."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


class DispatchBlockedError(DispatchError):
    """Raised when job status or approval constraints block dispatch."""
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message, status_code=status_code)


class DispatchPermissionError(DispatchError):
    """Raised when user role is not authorized to dispatch a job."""
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message, status_code=status_code)


def validate_job_for_dispatch(job: JobORM, user: Optional[object] = None) -> None:
    """
    Validate all preconditions and authorization gates before Kubernetes dispatch.

    Rules:
    1. User authorization (if user is provided):
       - PLATFORM_ADMIN: full access to dispatch any job across all companies.
       - COMPANY_ADMIN / COMPANY_USER: allowed to dispatch jobs within their own company
         (cross-company access is blocked below regardless of role).
    2. Status enforcement:
       - PENDING_APPROVAL -> raises DispatchBlockedError(403, "Job {job.job_id} is pending approval and cannot be dispatched")
       - DECLINED -> raises DispatchBlockedError(403, "Job {job.job_id} has been declined and cannot be dispatched")
       - Not in (APPROVED, QUEUED) -> raises DispatchBlockedError(400, "Job {job.job_id} is in status {job.status} — only APPROVED jobs can be dispatched")
    3. Schedule decision integrity:
       - job.schedule_decision is None -> raises DispatchBlockedError(400, "Job {job.job_id} has no schedule decision")
       - job.schedule_decision.job_id != job.job_id -> raises DispatchBlockedError(400, "Schedule decision does not belong to job {job.job_id}")
    """
    if user is not None:
        user_role = getattr(user, "role", None)
        role_str = str(user_role.value if hasattr(user_role, "value") else user_role).upper()
        user_tenant = getattr(user, "tenant_id", None)

        # Cross-tenant check for all non-global admins
        if user_tenant and job.tenant_id and user_tenant != job.tenant_id:
            raise DispatchPermissionError(
                f"User from company '{getattr(user, 'company_name', None) or user_tenant}' cannot dispatch job for company '{job.company_name or job.tenant_id}'",
                status_code=403,
            )

        if role_str in ("PLATFORM_ADMIN", "COMPANY_ADMIN", "COMPANY_USER"):
            pass  # Platform Admin has global access; Company Admin/User have within-company access
        else:
            raise DispatchPermissionError(
                f"Role '{role_str}' is not authorized to trigger dispatch",
                status_code=403,
            )

    # Status validations
    if job.status == JobStatus.PENDING_APPROVAL:
        raise DispatchBlockedError(
            f"Job {job.job_id} is pending approval and cannot be dispatched",
            status_code=403,
        )
    elif job.status == JobStatus.DECLINED:
        raise DispatchBlockedError(
            f"Job {job.job_id} has been declined and cannot be dispatched",
            status_code=403,
        )
    elif job.status not in (JobStatus.APPROVED, JobStatus.SCHEDULED, JobStatus.READY, JobStatus.CLAIMING, JobStatus.QUEUED, JobStatus.DISPATCHING):
        raise DispatchBlockedError(
            f"Job {job.job_id} is in status {job.status} — only APPROVED jobs can be dispatched",
            status_code=400,
        )

    # Schedule ownership validation
    decision = job.schedule_decision
    if decision is None:
        raise DispatchBlockedError(
            f"Job {job.job_id} has no schedule decision",
            status_code=400,
        )
    if decision.job_id != job.job_id:
        raise DispatchBlockedError(
            f"Schedule decision {decision.id} does not belong to job {job.job_id}",
            status_code=400,
        )

    # Execution window: never dispatch before the approved selected_start,
    # even via the manual endpoint. Jobs that reached READY/CLAIMING/QUEUED/
    # DISPATCHING through the automated promote_scheduled_to_ready() gate
    # already satisfy this trivially; this only blocks a direct manual
    # dispatch of a job whose window hasn't arrived yet.
    selected_start = decision.selected_start
    if selected_start is not None:
        if selected_start.tzinfo is None:
            selected_start = selected_start.replace(tzinfo=timezone.utc)
        if selected_start > utcnow():
            raise DispatchBlockedError(
                f"Job {job.job_id} cannot be dispatched before its selected execution "
                f"window ({selected_start.isoformat()})",
                status_code=400,
            )


def dispatch_job(db: Session, job: JobORM, user: Optional[object] = None) -> KubernetesExecutionORM:
    """
    Create a Kubernetes Job for an approved GreenShift job.

    Preconditions:
        - job.status == APPROVED (or QUEUED for idempotency)
        - job.schedule_decision is not None and matches job.job_id
        - user (if supplied) has permission to dispatch (PLATFORM_ADMIN, or COMPANY_ADMIN/COMPANY_USER within their own company)

    Args:
        db:   SQLAlchemy session
        job:  JobORM with associated schedule_decision
        user: Optional UserORM triggering the dispatch

    Returns:
        KubernetesExecutionORM record

    Raises:
        DispatchPermissionError: If user is unauthorized to dispatch this job.
        DispatchBlockedError: If job status or schedule constraints block dispatch.
        DispatchError: If the Kubernetes Job cannot be created.
    """
    caller_name = getattr(user, "username", None) if user else "system"
    metrics_record_dispatch_attempt()

    # 1. Record dispatch requested
    try:
        from app.trust.service import (
            record_dispatch_requested,
            record_dispatch_blocked,
            record_dispatch_started,
            record_dispatch_authorized,
            record_k8s_job_created,
        )
        record_dispatch_requested(db, job.job_id, requested_by=caller_name, team_id=job.team_id)
    except Exception as exc:
        logger.warning("Audit record failed for dispatch requested on %s: %s", job.job_id, exc)

    # 2. Strict authorization & state validation
    try:
        validate_job_for_dispatch(job, user=user)
    except (DispatchBlockedError, DispatchPermissionError, DispatchError) as exc:
        metrics_record_dispatch_blocked(str(exc))
        try:
            from app.trust.service import record_dispatch_blocked as audit_record_dispatch_blocked
            audit_record_dispatch_blocked(
                db,
                job.job_id,
                reason=str(exc),
                current_status=job.status,
                requested_by=caller_name,
            )
        except Exception as audit_exc:
            logger.warning("Audit record failed for dispatch blocked on %s: %s", job.job_id, audit_exc)
        raise

    decision: ScheduleDecisionORM = job.schedule_decision
    namespace = settings.k8s_namespace
    k8s_name = f"gs-{k8s_safe_name(job.job_id)}"

    # Transition to DISPATCHING state during manifest preparation and submission
    now_dispatching = utcnow()
    job.status = JobStatus.DISPATCHING
    job.updated_at = now_dispatching
    db.commit()

    logger.info("Dispatching job %s (DISPATCHING) → Kubernetes Job %s in namespace %s", job.job_id, k8s_name, namespace)

    try:
        batch = get_batch_v1()

        # Determine best candidate node for scheduling preference
        preferred_node = None
        try:
            cluster = collect_cluster_state()
            cpu_req = _parse_cpu_string(job.cpu_request or "500m")
            mem_req = _parse_memory_string(job.memory_request or "512Mi")
            gpu_req = getattr(job, "gpu_request", 0) or 0
            best = cluster.find_best_node(
                cpu_request_cores=cpu_req,
                memory_request_mib=mem_req,
                gpu_request=gpu_req,
            )
            if best:
                preferred_node = best.name
                logger.debug("Selected preferred node %s for job %s", preferred_node, job.job_id)
        except Exception as exc:
            logger.warning("Node selection hint failed for job %s, proceeding without hint: %s", job.job_id, exc)

        # Check if job already exists (idempotency)
        try:
            existing = batch.read_namespaced_job(name=k8s_name, namespace=namespace)
            logger.warning("Kubernetes Job %s already exists — skipping creation", k8s_name)
        except ApiException as exc:
            if exc.status != 404:
                raise DispatchError(f"Kubernetes API error: {exc}", status_code=500) from exc
            # Job does not exist — create it
            k8s_job = build_kubernetes_job(job, decision, namespace=namespace, preferred_node=preferred_node)
            batch.create_namespaced_job(namespace=namespace, body=k8s_job)
            logger.info("Created Kubernetes Job: %s (preferred_node=%s)", k8s_name, preferred_node)

        metrics_record_dispatch_success()
    except ApiException as exc:
        error_msg = f"Kubernetes API error creating job {k8s_name}: {exc}"
        logger.error(error_msg)
        _mark_job_failed(db, job, error_msg)
        metrics_record_dispatch_failure(error_msg)
        raise DispatchError(error_msg, status_code=500) from exc
    except Exception as exc:
        exc_str = str(exc)
        is_conn_error = (
            "Max retries exceeded" in exc_str
            or "Failed to establish a new connection" in exc_str
            or "Connection refused" in exc_str
            or "actively refused" in exc_str
            or "WinError 10061" in exc_str
            or not check_kubernetes_available()
        )
        if is_conn_error:
            logger.warning(
                "Kubernetes API cluster unreachable (%s). Dispatched in simulated local execution mode for %s.",
                exc, k8s_name,
            )
            metrics_record_dispatch_success()
        else:
            error_msg = f"Unexpected error dispatching job {k8s_name}: {exc}"
            logger.error(error_msg)
            _mark_job_failed(db, job, error_msg)
            metrics_record_dispatch_failure(error_msg)
            raise DispatchError(error_msg, status_code=500) from exc

    # Create execution tracking record
    now = utcnow()
    execution = KubernetesExecutionORM(
        job_id=job.job_id,
        kubernetes_job_name=k8s_name,
        kubernetes_namespace=namespace,
        planned_start=decision.selected_start,
        planned_end=decision.selected_end,
        gs_status=JobStatus.QUEUED,
        created_at=now,
        updated_at=now,
    )
    execution = db.merge(execution)

    # Update job status and clear claiming metadata
    job.status = JobStatus.QUEUED
    job.claimed_by = None
    job.claimed_at = None
    job.lease_expires_at = None
    job.updated_at = now
    db.commit()
    db.refresh(execution)

    # Record audit events
    try:
        from app.trust.service import (
            record_dispatch_started,
            record_dispatch_authorized,
            record_k8s_job_created,
        )
        record_dispatch_started(db, job.job_id, k8s_name, namespace, dispatched_by=caller_name)
        record_dispatch_authorized(db, job.job_id, decision.id, now.isoformat())
        record_k8s_job_created(db, job.job_id, k8s_name, namespace)
    except Exception as exc:
        logger.warning("Audit record failed for job %s creation: %s", job.job_id, exc)

    if job.submitted_by_user_id:
        try:
            from app.notify.service import create_notification
            from app.shared.models import EventType
            create_notification(
                db,
                recipient_user_id=job.submitted_by_user_id,
                event_type=EventType.K8S_JOB_CREATED,
                category="EXECUTION",
                severity="INFO",
                title=f"Workload {job.job_id} execution started",
                message=f"Workload '{job.job_id}' was dispatched to Kubernetes and is now queued for execution.",
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                email_required=False,
            )
        except Exception as exc:
            logger.warning("Notification failed for job %s dispatch: %s", job.job_id, exc)

    from app.shared.timezone import format_regional_time
    local_display = format_regional_time(decision.selected_start, region=job.region)
    logger.info(
        "Kubernetes Job %s created — GreenShift status: QUEUED | UTC: %s | Local (%s): %s",
        k8s_name, decision.selected_start.strftime("%Y-%m-%d %H:%M UTC"), job.region, local_display,
    )
    return execution


def _mark_job_failed(db: Session, job: JobORM, error_msg: str) -> None:
    """Mark a job as FAILED with an error message."""
    job.status = JobStatus.FAILED
    job.claimed_by = None
    job.claimed_at = None
    job.lease_expires_at = None
    if job.kubernetes_execution:
        job.kubernetes_execution.gs_status = JobStatus.FAILED
        job.kubernetes_execution.error_message = error_msg
        job.kubernetes_execution.updated_at = utcnow()
    db.commit()
    try:
        from app.trust.service import record_k8s_job_failed
        k8s_name = job.kubernetes_execution.kubernetes_job_name if job.kubernetes_execution else f"gs-{k8s_safe_name(job.job_id)}"
        record_k8s_job_failed(db, job.job_id, k8s_name, error_msg)
    except Exception as exc:
        logger.warning("Audit record failed for job %s failure: %s", job.job_id, exc)

    if job.submitted_by_user_id:
        try:
            from app.notify.service import create_notification
            from app.shared.models import EventType
            create_notification(
                db,
                recipient_user_id=job.submitted_by_user_id,
                event_type=EventType.K8S_JOB_FAILED,
                category="EXECUTION",
                severity="CRITICAL",
                title=f"Workload {job.job_id} failed",
                message=f"Workload '{job.job_id}' failed during dispatch: {error_msg}",
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                email_required=True,
            )
        except Exception as exc:
            logger.warning("Notification failed for job %s failure: %s", job.job_id, exc)


def refresh_job_status(db: Session, execution: KubernetesExecutionORM) -> KubernetesExecutionORM:
    """
    Query Kubernetes and update the execution record with the current status.

    Args:
        db:        SQLAlchemy session
        execution: KubernetesExecutionORM to update

    Returns:
        Updated KubernetesExecutionORM
    """
    now = utcnow()
    prev_status = execution.gs_status

    try:
        batch = get_batch_v1()
        core = get_core_v1()
        k8s_status_str, gs_status = get_job_status(
            batch, execution.kubernetes_job_name, execution.kubernetes_namespace
        )
        execution.k8s_status = k8s_status_str
        execution.gs_status = gs_status

        # Try to get pod name
        if execution.pod_name is None:
            pod_name = get_pod_name(core, execution.kubernetes_job_name, execution.kubernetes_namespace)
            if pod_name:
                execution.pod_name = pod_name

        # Try to get actual start time
        if execution.actual_start is None and execution.pod_name:
            start_time = get_pod_start_time(core, execution.pod_name, execution.kubernetes_namespace)
            if start_time:
                execution.actual_start = start_time

        # Try to get completion time
        if gs_status in (JobStatus.COMPLETED, JobStatus.FAILED):
            end_time = get_job_completion_time(batch, execution.kubernetes_job_name, execution.kubernetes_namespace)
            if end_time:
                execution.actual_end = end_time

        execution.updated_at = now

        # Sync job status
        job = execution.job or db.get(JobORM, execution.job_id)
        if job:
            job.status = gs_status

        db.commit()

        # Record audit events for state transitions
        if prev_status != gs_status:
            try:
                from app.trust.service import (
                    record_k8s_job_started,
                    record_k8s_job_completed,
                    record_k8s_job_failed,
                )
                if gs_status == JobStatus.RUNNING:
                    record_k8s_job_started(
                        db,
                        execution.job_id,
                        execution.kubernetes_job_name,
                        execution.pod_name,
                        (execution.actual_start or now).isoformat(),
                    )
                elif gs_status == JobStatus.COMPLETED:
                    record_k8s_job_completed(
                        db,
                        execution.job_id,
                        execution.kubernetes_job_name,
                        execution.pod_name,
                        (execution.actual_end or now).isoformat(),
                    )
                elif gs_status == JobStatus.FAILED:
                    record_k8s_job_failed(
                        db,
                        execution.job_id,
                        execution.kubernetes_job_name,
                        execution.error_message,
                    )
            except Exception as exc:
                logger.warning("Audit record failed for job %s transition to %s: %s", execution.job_id, gs_status, exc)

            if job and job.submitted_by_user_id and gs_status in (JobStatus.COMPLETED, JobStatus.FAILED):
                try:
                    from app.notify.service import create_notification
                    from app.shared.models import EventType
                    if gs_status == JobStatus.COMPLETED:
                        create_notification(
                            db,
                            recipient_user_id=job.submitted_by_user_id,
                            event_type=EventType.K8S_JOB_COMPLETED,
                            category="EXECUTION",
                            severity="INFO",
                            title=f"Workload {job.job_id} completed",
                            message=f"Workload '{job.job_id}' completed successfully. Impact/report data is now available.",
                            tenant_id=job.tenant_id,
                            job_id=job.job_id,
                            email_required=True,
                        )
                    else:
                        create_notification(
                            db,
                            recipient_user_id=job.submitted_by_user_id,
                            event_type=EventType.K8S_JOB_FAILED,
                            category="EXECUTION",
                            severity="CRITICAL",
                            title=f"Workload {job.job_id} failed",
                            message=f"Workload '{job.job_id}' failed during execution: {execution.error_message or 'unknown error'}",
                            tenant_id=job.tenant_id,
                            job_id=job.job_id,
                            email_required=True,
                        )
                except Exception as exc:
                    logger.warning("Notification failed for job %s transition to %s: %s", execution.job_id, gs_status, exc)

        logger.info(
            "Job %s | K8s: %s | GS: %s",
            execution.job_id,
            k8s_status_str,
            gs_status,
        )

    except Exception as exc:
        exc_str = str(exc)
        is_conn_error = (
            "Max retries exceeded" in exc_str
            or "Failed to establish a new connection" in exc_str
            or "Connection refused" in exc_str
            or "actively refused" in exc_str
            or "WinError 10061" in exc_str
            or not check_kubernetes_available()
        )
        if is_conn_error and execution.planned_start:
            planned_start = execution.planned_start
            if planned_start.tzinfo is None:
                planned_start = planned_start.replace(tzinfo=timezone.utc)
            planned_end = execution.planned_end or (planned_start + timedelta(minutes=15))
            if planned_end.tzinfo is None:
                planned_end = planned_end.replace(tzinfo=timezone.utc)

            sim_status = execution.gs_status
            if now >= planned_end:
                sim_status = JobStatus.COMPLETED
                if execution.actual_end is None:
                    execution.actual_end = planned_end
            elif now >= planned_start:
                sim_status = JobStatus.RUNNING
                if execution.actual_start is None:
                    execution.actual_start = planned_start
            else:
                sim_status = JobStatus.QUEUED

            if sim_status != execution.gs_status:
                execution.gs_status = sim_status
                execution.k8s_status = f"Simulated / {sim_status.value}"
                execution.updated_at = now
                if execution.job:
                    execution.job.status = sim_status
                db.commit()
        else:
            logger.error("Error refreshing status for %s: %s", execution.kubernetes_job_name, exc)

    return execution
