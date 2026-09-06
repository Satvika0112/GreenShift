"""
Agent 3 — DISPATCH / KUBERNETES STATE COLLECTOR
Cluster Telemetry & Resource Availability Collector.

Provides real-time cluster state to the DECIDE agent and PRESENT dashboard:
- CPU availability (total capacity, allocatable, used, free)
- RAM availability (total capacity, allocatable, used, free in MiB)
- GPU availability (total capacity, allocatable, free)
- Cluster health (ready nodes, cluster status)
- Node status inventory
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.dispatch.kubernetes_client import (
    check_kubernetes_available,
    get_batch_v1,
    get_core_v1,
)
from app.shared.config import settings

logger = logging.getLogger(__name__)


@dataclass
class NodeState:
    name: str
    status: str  # Ready / NotReady
    cpu_capacity_cores: float
    cpu_allocatable_cores: float
    memory_capacity_mib: float
    memory_allocatable_mib: float
    gpu_capacity: int = 0
    gpu_allocatable: int = 0
    roles: List[str] = field(default_factory=list)


@dataclass
class ClusterResourceSnapshot:
    connected: bool
    cluster_health: str  # HEALTHY / DEGRADED / SIMULATED / DISCONNECTED
    total_nodes: int
    ready_nodes: int
    total_cpu_cores: float
    allocatable_cpu_cores: float
    used_cpu_cores: float
    free_cpu_cores: float
    total_memory_mib: float
    allocatable_memory_mib: float
    used_memory_mib: float
    free_memory_mib: float
    total_gpus: int
    allocatable_gpus: int
    used_gpus: int
    free_gpus: int
    nodes: List[NodeState] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_resource_feasible(
        self,
        cpu_request_cores: float = 0.5,
        memory_request_mib: float = 512.0,
        gpu_request: int = 0,
    ) -> Tuple[bool, str]:
        """Check if cluster currently has sufficient resources for a workload."""
        if not self.connected and self.cluster_health != "SIMULATED":
            # In simulated mode, assume available resources
            return True, "Cluster connected (simulated capacity)"

        if self.free_cpu_cores < cpu_request_cores:
            return False, f"Insufficient CPU: requested {cpu_request_cores} cores, free {self.free_cpu_cores:.2f} cores"

        if self.free_memory_mib < memory_request_mib:
            return False, f"Insufficient RAM: requested {memory_request_mib} MiB, free {self.free_memory_mib:.1f} MiB"

        if gpu_request > 0 and self.free_gpus < gpu_request:
            return False, f"Insufficient GPU: requested {gpu_request}, free {self.free_gpus}"

        return True, "Cluster resources available"


def _parse_cpu_string(cpu_str: str) -> float:
    """Parse k8s cpu quantity string (e.g. '500m', '2', '4000m') into float cores."""
    if not cpu_str:
        return 0.0
    cpu_str = str(cpu_str).strip()
    if cpu_str.endswith("m"):
        return float(cpu_str[:-1]) / 1000.0
    return float(cpu_str)


def _parse_memory_string(mem_str: str) -> float:
    """Parse k8s memory quantity string (e.g. '512Mi', '2Gi', '1000M', '1048576Ki') into MiB."""
    if not mem_str:
        return 0.0
    mem_str = str(mem_str).strip()
    if mem_str.endswith("Ki"):
        return float(mem_str[:-2]) / 1024.0
    if mem_str.endswith("Mi"):
        return float(mem_str[:-2])
    if mem_str.endswith("Gi"):
        return float(mem_str[:-2]) * 1024.0
    if mem_str.endswith("Ti"):
        return float(mem_str[:-2]) * 1024.0 * 1024.0
    if mem_str.endswith("M"):
        return float(mem_str[:-1]) * 1000.0 / 1048.576
    if mem_str.endswith("G"):
        return float(mem_str[:-1]) * 1000.0 * 1000.0 / 1048.576
    try:
        # Assume raw bytes
        return float(mem_str) / (1024.0 * 1024.0)
    except ValueError:
        return 0.0


def collect_cluster_state() -> ClusterResourceSnapshot:
    """
    Query the Kubernetes API to collect live node and resource telemetry.
    If cluster is not reachable, returns a healthy simulated snapshot.
    """
    if not check_kubernetes_available():
        # Simulated default snapshot for dev / testing environments
        return ClusterResourceSnapshot(
            connected=False,
            cluster_health="SIMULATED",
            total_nodes=3,
            ready_nodes=3,
            total_cpu_cores=24.0,
            allocatable_cpu_cores=22.0,
            used_cpu_cores=4.5,
            free_cpu_cores=17.5,
            total_memory_mib=98304.0,  # 96 GiB
            allocatable_memory_mib=90112.0,
            used_memory_mib=18432.0,
            free_memory_mib=71680.0,
            total_gpus=4,
            allocatable_gpus=4,
            used_gpus=1,
            free_gpus=3,
            nodes=[
                NodeState(
                    name="node-1-control-plane",
                    status="Ready",
                    cpu_capacity_cores=8.0,
                    cpu_allocatable_cores=7.5,
                    memory_capacity_mib=32768.0,
                    memory_allocatable_mib=30720.0,
                    gpu_capacity=0,
                    gpu_allocatable=0,
                    roles=["control-plane", "master"],
                ),
                NodeState(
                    name="node-2-worker-gpu",
                    status="Ready",
                    cpu_capacity_cores=8.0,
                    cpu_allocatable_cores=7.5,
                    memory_capacity_mib=32768.0,
                    memory_allocatable_mib=30720.0,
                    gpu_capacity=4,
                    gpu_allocatable=4,
                    roles=["worker", "gpu"],
                ),
                NodeState(
                    name="node-3-worker",
                    status="Ready",
                    cpu_capacity_cores=8.0,
                    cpu_allocatable_cores=7.0,
                    memory_capacity_mib=32768.0,
                    memory_allocatable_mib=28672.0,
                    gpu_capacity=0,
                    gpu_allocatable=0,
                    roles=["worker"],
                ),
            ],
        )

    try:
        core = get_core_v1()
        node_list = core.list_node(_request_timeout=(0.5, 2.0))

        nodes: List[NodeState] = []
        total_cpu = 0.0
        allocatable_cpu = 0.0
        total_mem = 0.0
        allocatable_mem = 0.0
        total_gpu = 0
        allocatable_gpu = 0
        ready_count = 0

        for n in node_list.items:
            # Check ready status
            status = "NotReady"
            for cond in (n.status.conditions or []):
                if cond.type == "Ready" and cond.status == "True":
                    status = "Ready"
                    ready_count += 1
                    break

            cap = n.status.capacity or {}
            alloc = n.status.allocatable or {}

            cpu_cap = _parse_cpu_string(cap.get("cpu", "0"))
            cpu_alloc = _parse_cpu_string(alloc.get("cpu", "0"))
            mem_cap = _parse_memory_string(cap.get("memory", "0"))
            mem_alloc = _parse_memory_string(alloc.get("memory", "0"))
            gpu_cap = int(cap.get("nvidia.com/gpu", 0))
            gpu_alloc = int(alloc.get("nvidia.com/gpu", 0))

            total_cpu += cpu_cap
            allocatable_cpu += cpu_alloc
            total_mem += mem_cap
            allocatable_mem += mem_alloc
            total_gpu += gpu_cap
            allocatable_gpu += gpu_alloc

            # Determine roles
            roles = []
            labels = n.metadata.labels or {}
            for k in labels:
                if k.startswith("node-role.kubernetes.io/"):
                    roles.append(k.split("/")[-1])

            nodes.append(NodeState(
                name=n.metadata.name,
                status=status,
                cpu_capacity_cores=cpu_cap,
                cpu_allocatable_cores=cpu_alloc,
                memory_capacity_mib=mem_cap,
                memory_allocatable_mib=mem_alloc,
                gpu_capacity=gpu_cap,
                gpu_allocatable=gpu_alloc,
                roles=roles or ["worker"],
            ))

        # Query active pods to estimate used resources
        used_cpu = 0.0
        used_mem = 0.0
        used_gpu = 0
        try:
            pod_list = core.list_pod_for_all_namespaces(
                field_selector="status.phase=Running",
                _request_timeout=5,
            )
            for pod in pod_list.items:
                for c in (pod.spec.containers or []):
                    req = c.resources.requests or {} if c.resources else {}
                    used_cpu += _parse_cpu_string(req.get("cpu", "0"))
                    used_mem += _parse_memory_string(req.get("memory", "0"))
                    used_gpu += int(req.get("nvidia.com/gpu", 0))
        except Exception as exc:
            logger.debug("Pod resource listing skipped: %s", exc)

        free_cpu = max(0.0, allocatable_cpu - used_cpu)
        free_mem = max(0.0, allocatable_mem - used_mem)
        free_gpu = max(0, allocatable_gpu - used_gpu)

        health = "HEALTHY" if ready_count == len(nodes) and ready_count > 0 else "DEGRADED"

        return ClusterResourceSnapshot(
            connected=True,
            cluster_health=health,
            total_nodes=len(nodes),
            ready_nodes=ready_count,
            total_cpu_cores=round(total_cpu, 2),
            allocatable_cpu_cores=round(allocatable_cpu, 2),
            used_cpu_cores=round(used_cpu, 2),
            free_cpu_cores=round(free_cpu, 2),
            total_memory_mib=round(total_mem, 1),
            allocatable_memory_mib=round(allocatable_mem, 1),
            used_memory_mib=round(used_mem, 1),
            free_memory_mib=round(free_mem, 1),
            total_gpus=total_gpu,
            allocatable_gpus=allocatable_gpu,
            used_gpus=used_gpu,
            free_gpus=free_gpu,
            nodes=nodes,
        )

    except Exception as exc:
        logger.error("Failed to collect cluster state from Kubernetes API: %s", exc)
        return ClusterResourceSnapshot(
            connected=False,
            cluster_health="DISCONNECTED",
            total_nodes=0,
            ready_nodes=0,
            total_cpu_cores=0.0,
            allocatable_cpu_cores=0.0,
            used_cpu_cores=0.0,
            free_cpu_cores=0.0,
            total_memory_mib=0.0,
            allocatable_memory_mib=0.0,
            used_memory_mib=0.0,
            free_memory_mib=0.0,
            total_gpus=0,
            allocatable_gpus=0,
            used_gpus=0,
            free_gpus=0,
            nodes=[],
        )
