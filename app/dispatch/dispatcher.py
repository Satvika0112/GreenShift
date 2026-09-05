"""
Agent 3 — DISPATCH
Core dispatcher — creates Kubernetes Jobs at the scheduled time.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from kubernetes.client.rest import ApiException
from sqlalchemy.orm import Session

from app.dispatch.job_builder import build_kubernetes_job
from app.dispatch.kubernetes_client import get_batch_v1, get_core_v1
from app.dispatch.status_tracker import (
    get_job_status,
    get_pod_name,
    get_pod_start_time,
    get_job_completion_time,
)
from app.shared.config import settings
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


def dispatch_job(db: Session, job: JobORM) -> KubernetesExecutionORM:
    """
    Create a Kubernetes Job for a scheduled GreenShift job.

    Preconditions:
        - job.status == SCHEDULED
        - job.schedule_decision is not None

    Args:
        db:  SQLAlchemy session
        job: JobORM with associated schedule_decision

    Returns:
        KubernetesExecutionORM record

    Raises:
        DispatchError: If the Kubernetes Job cannot be created.
    """
    decision: Optional[ScheduleDecisionORM] = job.schedule_decision
    if decision is None:
        raise DispatchError(f"Job {job.job_id} has no schedule decision")

    namespace = settings.k8s_namespace
    k8s_name = f"gs-{k8s_safe_name(job.job_id)}"

    logger.info("Dispatching job %s → Kubernetes Job %s in namespace %s", job.job_id, k8s_name, namespace)

    try:
        batch = get_batch_v1()

        # Check if job already exists (idempotency)
        try:
            existing = batch.read_namespaced_job(name=k8s_name, namespace=namespace)
            logger.warning("Kubernetes Job %s already exists — skipping creation", k8s_name)
        except ApiException as exc:
            if exc.status != 404:
                raise DispatchError(f"Kubernetes API error: {exc}") from exc
            # Job does not exist — create it
            k8s_job = build_kubernetes_job(job, decision, namespace=namespace)
            batch.create_namespaced_job(namespace=namespace, body=k8s_job)
            logger.info("Created Kubernetes Job: %s", k8s_name)

    except ApiException as exc:
        error_msg = f"Kubernetes API error creating job {k8s_name}: {exc}"
        logger.error(error_msg)
        _mark_job_failed(db, job, error_msg)
        raise DispatchError(error_msg) from exc
    except Exception as exc:
        error_msg = f"Unexpected error dispatching job {k8s_name}: {exc}"
        logger.error(error_msg)
        _mark_job_failed(db, job, error_msg)
        raise DispatchError(error_msg) from exc

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
    db.merge(execution)

    # Update job status
    job.status = JobStatus.QUEUED
    db.commit()

    # Record audit event
    try:
        from app.trust.service import record_k8s_job_created
        record_k8s_job_created(db, job.job_id, k8s_name, namespace)
    except Exception as exc:
        logger.warning("Audit record failed for job %s creation: %s", job.job_id, exc)

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


def refresh_job_status(db: Session, execution: KubernetesExecutionORM) -> KubernetesExecutionORM:
    """
    Query Kubernetes and update the execution record with the current status.

    Args:
        db:        SQLAlchemy session
        execution: KubernetesExecutionORM to update

    Returns:
        Updated KubernetesExecutionORM
    """
    batch = get_batch_v1()
    core = get_core_v1()
    now = utcnow()
    prev_status = execution.gs_status

    try:
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
        job = execution.job
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

        logger.info(
            "Job %s | K8s: %s | GS: %s",
            execution.job_id,
            k8s_status_str,
            gs_status,
        )

    except Exception as exc:
        logger.error("Error refreshing status for %s: %s", execution.kubernetes_job_name, exc)

    return execution
