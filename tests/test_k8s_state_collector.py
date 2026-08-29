"""
Tests for Kubernetes State Collector and Resource Telemetry.
"""

from app.dispatch.k8s_state_collector import (
    collect_cluster_state,
    _parse_cpu_string,
    _parse_memory_string,
    ClusterResourceSnapshot,
)


class TestK8sStateCollector:
    def test_cpu_memory_string_parsing(self):
        assert _parse_cpu_string("500m") == 0.5
        assert _parse_cpu_string("2") == 2.0
        assert _parse_cpu_string("4000m") == 4.0

        assert _parse_memory_string("512Mi") == 512.0
        assert _parse_memory_string("2Gi") == 2048.0
        assert _parse_memory_string("1024Ki") == 1.0

    def test_cluster_state_collection(self):
        snapshot = collect_cluster_state()
        assert isinstance(snapshot, ClusterResourceSnapshot)
        assert snapshot.total_cpu_cores >= 0.0
        assert snapshot.free_cpu_cores >= 0.0
        assert snapshot.total_memory_mib >= 0.0
        assert snapshot.cluster_health in ("HEALTHY", "DEGRADED", "SIMULATED", "DISCONNECTED")

    def test_resource_feasibility_check(self):
        snapshot = ClusterResourceSnapshot(
            connected=True,
            cluster_health="HEALTHY",
            total_nodes=2,
            ready_nodes=2,
            total_cpu_cores=16.0,
            allocatable_cpu_cores=16.0,
            used_cpu_cores=4.0,
            free_cpu_cores=12.0,
            total_memory_mib=32768.0,
            allocatable_memory_mib=32768.0,
            used_memory_mib=8192.0,
            free_memory_mib=24576.0,
            total_gpus=2,
            allocatable_gpus=2,
            used_gpus=0,
            free_gpus=2,
        )

        feasible, msg = snapshot.is_resource_feasible(cpu_request_cores=2.0, memory_request_mib=4096.0, gpu_request=1)
        assert feasible is True

        # Test infeasible CPU request
        infeasible, msg = snapshot.is_resource_feasible(cpu_request_cores=20.0)
        assert infeasible is False
        assert "CPU" in msg
