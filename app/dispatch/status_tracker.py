"""
Agent 3 — DISPATCH
Kubernetes Status Tracker.

Queries Kubernetes API for Job and Pod status.
Maps Kubernetes states to GreenShift states.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from kubernetes.client import BatchV1Api, CoreV1Api
from kubernetes.client.rest import ApiException

from app.shared.models import JobStatus

logger = logging.getLogger(__name__)

# Kubernetes → GreenShift status mapping
K8S_TO_GS_STATUS = {
    "Pending":   JobStatus.QUEUED,
    "Running":   JobStatus.RUNNING,
    "Succeeded": JobStatus.COMPLETED,
    "Failed":    JobStatus.FAILED,
    "Unknown":   JobStatus.FAILED,
}


def get_job_status(
    batch_api: BatchV1Api,
    job_name: str,
    namespace: str,
) -> Tuple[Optional[str], JobStatus]:
    """
    Query Kubernetes for Job status.

    Returns:
        (k8s_status_str, gs_status)
    """
    try:
        job = batch_api.read_namespaced_job(name=job_name, namespace=namespace)
        status = job.status

        if status.succeeded and status.succeeded > 0:
            return "Succeeded", JobStatus.COMPLETED
        elif status.failed and status.failed > 0:
            return "Failed", JobStatus.FAILED
        elif status.active and status.active > 0:
            return "Running", JobStatus.RUNNING
        else:
            return "Pending", JobStatus.QUEUED

    except ApiException as exc:
        if exc.status == 404:
            logger.warning("Kubernetes Job %s not found in namespace %s", job_name, namespace)
            return None, JobStatus.FAILED
        logger.error("Kubernetes API error querying job %s: %s", job_name, exc)
        raise


def get_pod_name(
    core_api: CoreV1Api,
    job_name: str,
    namespace: str,
) -> Optional[str]:
    """
    Find the pod created by a Kubernetes Job.
    Returns the pod name, or None if no pod exists yet.
    """
    try:
        pods = core_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"batch.kubernetes.io/job-name={job_name}",
        )
        # Filter out terminating pods (deletion_timestamp is set)
        active_pods = [p for p in pods.items if p.metadata.deletion_timestamp is None]
        if active_pods:
            # Prefer the most recently created active pod
            active_pods.sort(key=lambda p: p.metadata.creation_timestamp or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return active_pods[0].metadata.name
        elif pods.items:
            return pods.items[0].metadata.name
        return None
    except ApiException as exc:
        logger.error("Error listing pods for job %s: %s", job_name, exc)
        return None


def get_pod_start_time(
    core_api: CoreV1Api,
    pod_name: str,
    namespace: str,
) -> Optional[datetime]:
    """Return the pod start time (UTC) or None."""
    try:
        pod = core_api.read_namespaced_pod(name=pod_name, namespace=namespace)
        if pod.status and pod.status.start_time:
            return pod.status.start_time.replace(tzinfo=timezone.utc)
        return None
    except ApiException:
        return None


def get_job_completion_time(
    batch_api: BatchV1Api,
    job_name: str,
    namespace: str,
) -> Optional[datetime]:
    """Return the job completion time (UTC) or None."""
    try:
        job = batch_api.read_namespaced_job(name=job_name, namespace=namespace)
        if job.status and job.status.completion_time:
            return job.status.completion_time.replace(tzinfo=timezone.utc)
        return None
    except ApiException:
        return None
