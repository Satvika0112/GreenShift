"""
Agent 3 — DISPATCH
Kubernetes Job Builder.

Converts a ScheduleDecision + JobORM into a Kubernetes Job manifest
using the official Kubernetes Python client object model.
"""

import logging
from typing import Dict, Optional

from kubernetes.client import (
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1Container,
    V1ResourceRequirements,
    V1EnvVar,
    V1Affinity,
    V1NodeAffinity,
    V1PreferredSchedulingTerm,
    V1NodeSelectorTerm,
    V1NodeSelectorRequirement,
    V1NodeSelector,
)

from app.shared.config import settings
from app.shared.models import JobORM, ScheduleDecisionORM
from app.shared.utils import k8s_safe_name

logger = logging.getLogger(__name__)


def build_kubernetes_job(
    job: JobORM,
    decision: ScheduleDecisionORM,
    namespace: str = None,
    preferred_node: Optional[str] = None,
) -> V1Job:
    """
    Build a V1Job object for a GreenShift job.

    Args:
        job:            JobORM record (provides container_image, cpu_request, etc.)
        decision:       ScheduleDecisionORM (provides timing and metadata)
        namespace:      Target namespace (defaults to settings.k8s_namespace)
        preferred_node: Optional node name to prefer scheduling on via node affinity

    Returns:
        kubernetes.client.V1Job ready to be submitted to the API.
    """
    if namespace is None:
        namespace = settings.k8s_namespace

    k8s_name = f"gs-{k8s_safe_name(job.job_id)}"
    duration_seconds = str(job.runtime_minutes * 60)

    # Build container resources
    gpu_req = getattr(job, "gpu_request", 0) or 0
    requests_dict = {
        "cpu":    job.cpu_request    or "500m",
        "memory": job.memory_request or "512Mi",
    }
    limits_dict = {
        "cpu":    _scale_cpu(job.cpu_request    or "500m"),
        "memory": _scale_memory(job.memory_request or "512Mi"),
    }
    if gpu_req > 0:
        requests_dict["nvidia.com/gpu"] = str(gpu_req)
        limits_dict["nvidia.com/gpu"] = str(gpu_req)

    # Build container
    container = V1Container(
        name="workload",
        image=job.container_image,
        image_pull_policy="IfNotPresent",
        env=[
            V1EnvVar(name="JOB_ID",            value=job.job_id),
            V1EnvVar(name="TEAM_ID",            value=job.team_id),
            V1EnvVar(name="DURATION_SECONDS",   value=duration_seconds),
            V1EnvVar(name="REGION",             value=job.region),
            V1EnvVar(name="CARBON_INTENSITY",   value=str(decision.carbon_intensity)),
            V1EnvVar(name="SELECTED_START",     value=decision.selected_start.isoformat()),
        ],
        resources=V1ResourceRequirements(
            requests=requests_dict,
            limits=limits_dict,
        ),
    )

    # Node affinity configuration
    preferred_terms = []
    if preferred_node:
        preferred_terms.append(
            V1PreferredSchedulingTerm(
                weight=100,
                preference=V1NodeSelectorTerm(
                    match_expressions=[
                        V1NodeSelectorRequirement(
                            key="kubernetes.io/hostname",
                            operator="In",
                            values=[preferred_node],
                        )
                    ]
                ),
            )
        )

    required_node_selector = None
    if gpu_req > 0:
        required_node_selector = V1NodeSelector(
            node_selector_terms=[
                V1NodeSelectorTerm(
                    match_expressions=[
                        V1NodeSelectorRequirement(
                            key="nvidia.com/gpu.present",
                            operator="In",
                            values=["true"],
                        )
                    ]
                )
            ]
        )

    affinity = None
    if preferred_terms or required_node_selector:
        affinity = V1Affinity(
            node_affinity=V1NodeAffinity(
                preferred_during_scheduling_ignored_during_execution=preferred_terms or None,
                required_during_scheduling_ignored_during_execution=required_node_selector,
            )
        )

    # Build Job
    k8s_job = V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=V1ObjectMeta(
            name=k8s_name,
            namespace=namespace,
            labels={
                "app":                  "greenshift",
                "greenshift-job-id":    job.job_id,
                "greenshift-team-id":   job.team_id,
                "greenshift-region":    job.region,
            },
            annotations={
                "greenshift/scheduled-start":   decision.selected_start.isoformat(),
                "greenshift/selected-carbon":   str(decision.carbon_intensity),
                "greenshift/selected-cost":     str(decision.electricity_cost),
                "greenshift/carbon-emission-kg": str(decision.carbon_emission),
            },
        ),
        spec=V1JobSpec(
            backoff_limit=0,              # No automatic retries — GreenShift manages retry policy
            ttl_seconds_after_finished=3600,  # Clean up after 1 hour
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(
                    labels={
                        "app":               "greenshift",
                        "greenshift-job-id": job.job_id,
                    }
                ),
                spec=V1PodSpec(
                    restart_policy="Never",
                    service_account_name="default",
                    security_context=None,  # set by pod security policy / admission
                    containers=[container],
                    affinity=affinity,
                ),
            ),
        ),
    )

    logger.debug("Built Kubernetes Job: %s (image=%s, preferred_node=%s)", k8s_name, job.container_image, preferred_node)
    return k8s_job


def _scale_cpu(cpu_request: str) -> str:
    """Double the CPU request for the limit."""
    if cpu_request.endswith("m"):
        val = int(cpu_request[:-1]) * 2
        return f"{val}m"
    try:
        val = float(cpu_request) * 2
        return str(val)
    except ValueError:
        return "1000m"


def _scale_memory(mem_request: str) -> str:
    """Double the memory request for the limit."""
    if mem_request.endswith("Mi"):
        val = int(mem_request[:-2]) * 2
        return f"{val}Mi"
    if mem_request.endswith("Gi"):
        val = int(mem_request[:-2]) * 2
        return f"{val}Gi"
    return "1Gi"
