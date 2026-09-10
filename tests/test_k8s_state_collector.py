"""
Tests for Kubernetes State Collector and Resource Telemetry.
"""

from unittest.mock import patch
from app.dispatch.k8s_state_collector import (
    collect_cluster_state,
    _parse_cpu_string,
    _parse_memory_string,
    ClusterResourceSnapshot,
    NodeState,
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


class TestNodeLevelFeasibility:
    """Test suite verifying node-level resource feasibility checks and scheduling hints."""

    def _create_3node_snapshot(self) -> ClusterResourceSnapshot:
        """Create a cluster with 3 nodes having 6 free cores each (18 aggregate free cores)."""
        nodes = [
            NodeState(
                name="node-1",
                status="Ready",
                cpu_capacity_cores=8.0,
                cpu_allocatable_cores=8.0,
                memory_capacity_mib=16384.0,
                memory_allocatable_mib=16384.0,
                gpu_capacity=0,
                gpu_allocatable=0,
                cpu_used_cores=2.0,  # 6.0 free
                memory_used_mib=4096.0,  # 12288.0 free
                gpu_used=0,
            ),
            NodeState(
                name="node-2",
                status="Ready",
                cpu_capacity_cores=8.0,
                cpu_allocatable_cores=8.0,
                memory_capacity_mib=16384.0,
                memory_allocatable_mib=16384.0,
                gpu_capacity=1,
                gpu_allocatable=1,
                cpu_used_cores=2.0,  # 6.0 free
                memory_used_mib=4096.0,  # 12288.0 free
                gpu_used=0,  # 1 free
            ),
            NodeState(
                name="node-3",
                status="Ready",
                cpu_capacity_cores=8.0,
                cpu_allocatable_cores=8.0,
                memory_capacity_mib=16384.0,
                memory_allocatable_mib=16384.0,
                gpu_capacity=0,
                gpu_allocatable=0,
                cpu_used_cores=2.0,  # 6.0 free
                memory_used_mib=4096.0,  # 12288.0 free
                gpu_used=0,
            ),
        ]
        return ClusterResourceSnapshot(
            connected=True,
            cluster_health="HEALTHY",
            total_nodes=3,
            ready_nodes=3,
            total_cpu_cores=24.0,
            allocatable_cpu_cores=24.0,
            used_cpu_cores=6.0,
            free_cpu_cores=18.0,
            total_memory_mib=49152.0,
            allocatable_memory_mib=49152.0,
            used_memory_mib=12288.0,
            free_memory_mib=36864.0,
            total_gpus=1,
            allocatable_gpus=1,
            used_gpus=0,
            free_gpus=1,
            nodes=nodes,
        )

    def test_job_rejected_when_exceeding_any_single_node_even_if_aggregate_fits(self):
        """Aggregate has 18 free cores, but each node only has 6 free cores -> 8-core job must fail."""
        snapshot = self._create_3node_snapshot()
        feasible, msg = snapshot.is_resource_feasible(
            cpu_request_cores=8.0,
            memory_request_mib=1024.0,
            gpu_request=0,
        )
        assert feasible is False
        assert "No single node can fit" in msg
        assert "largest Ready node has: 6.00 CPU" in msg

    def test_job_feasible_when_single_node_has_capacity(self):
        """4-core job fits on any of the 6-core free nodes -> must be feasible."""
        snapshot = self._create_3node_snapshot()
        feasible, msg = snapshot.is_resource_feasible(
            cpu_request_cores=4.0,
            memory_request_mib=2048.0,
            gpu_request=0,
        )
        assert feasible is True
        assert "Feasible on 3 node(s)" in msg

    def test_gpu_feasibility_requires_gpu_on_node(self):
        """GPU job is feasible on node-2 (which has 1 GPU), but infeasible if 2 GPUs requested."""
        snapshot = self._create_3node_snapshot()

        feasible_1gpu, msg1 = snapshot.is_resource_feasible(
            cpu_request_cores=2.0,
            memory_request_mib=1024.0,
            gpu_request=1,
        )
        assert feasible_1gpu is True
        assert "Feasible on 1 node(s)" in msg1
        assert "node-2" in msg1

        infeasible_2gpu, msg2 = snapshot.is_resource_feasible(
            cpu_request_cores=2.0,
            memory_request_mib=1024.0,
            gpu_request=2,
        )
        assert infeasible_2gpu is False
        assert "GPU" in msg2

    def test_not_ready_nodes_excluded(self):
        """A node that is NotReady must NOT be considered for feasibility even if it has free resources."""
        snapshot = self._create_3node_snapshot()
        # Mark all ready nodes used up, but have a NotReady node with 16 cores
        for n in snapshot.nodes:
            n.cpu_used_cores = 8.0  # 0 free cores

        not_ready_node = NodeState(
            name="node-offline",
            status="NotReady",
            cpu_capacity_cores=16.0,
            cpu_allocatable_cores=16.0,
            memory_capacity_mib=32768.0,
            memory_allocatable_mib=32768.0,
            cpu_used_cores=0.0,
            memory_used_mib=0.0,
        )
        snapshot.nodes.append(not_ready_node)
        snapshot.free_cpu_cores = 16.0  # aggregate has free cores from the NotReady node

        feasible, msg = snapshot.is_resource_feasible(cpu_request_cores=4.0)
        assert feasible is False
        assert "No single node can fit" in msg

    def test_find_best_node_spread_strategy(self):
        """Spread strategy selects the candidate node with the most free CPU cores."""
        nodes = [
            NodeState(
                name="node-busy",
                status="Ready",
                cpu_capacity_cores=8.0,
                cpu_allocatable_cores=8.0,
                memory_capacity_mib=16384.0,
                memory_allocatable_mib=16384.0,
                cpu_used_cores=5.0,  # 3.0 free
                memory_used_mib=1024.0,
            ),
            NodeState(
                name="node-empty",
                status="Ready",
                cpu_capacity_cores=8.0,
                cpu_allocatable_cores=8.0,
                memory_capacity_mib=16384.0,
                memory_allocatable_mib=16384.0,
                cpu_used_cores=1.0,  # 7.0 free
                memory_used_mib=1024.0,
            ),
            NodeState(
                name="node-medium",
                status="Ready",
                cpu_capacity_cores=8.0,
                cpu_allocatable_cores=8.0,
                memory_capacity_mib=16384.0,
                memory_allocatable_mib=16384.0,
                cpu_used_cores=3.0,  # 5.0 free
                memory_used_mib=1024.0,
            ),
        ]
        snapshot = ClusterResourceSnapshot(
            connected=True,
            cluster_health="HEALTHY",
            total_nodes=3,
            ready_nodes=3,
            total_cpu_cores=24.0,
            allocatable_cpu_cores=24.0,
            used_cpu_cores=9.0,
            free_cpu_cores=15.0,
            total_memory_mib=49152.0,
            allocatable_memory_mib=49152.0,
            used_memory_mib=3072.0,
            free_memory_mib=46080.0,
            total_gpus=0,
            allocatable_gpus=0,
            used_gpus=0,
            free_gpus=0,
            nodes=nodes,
        )

        best = snapshot.find_best_node(cpu_request_cores=2.0, memory_request_mib=512.0)
        assert best is not None
        assert best.name == "node-empty"
        assert best.cpu_free_cores == 7.0

    def test_simulated_snapshot_has_node_inventory_and_consistent_metrics(self):
        """Simulated cluster state returns 3 nodes whose used metrics sum to the cluster totals."""
        with patch("app.dispatch.k8s_state_collector.check_kubernetes_available", return_value=False):
            snapshot = collect_cluster_state()
        assert len(snapshot.nodes) == 3

        sum_cpu_used = sum(n.cpu_used_cores for n in snapshot.nodes)
        sum_mem_used = sum(n.memory_used_mib for n in snapshot.nodes)
        sum_gpu_used = sum(n.gpu_used for n in snapshot.nodes)

        assert round(sum_cpu_used, 2) == round(snapshot.used_cpu_cores, 2)
        assert round(sum_mem_used, 1) == round(snapshot.used_memory_mib, 1)
        assert sum_gpu_used == snapshot.used_gpus

        for n in snapshot.nodes:
            assert n.cpu_free_cores >= 0.0
            assert n.memory_free_mib >= 0.0
            assert n.gpu_free >= 0

    def test_backward_compatibility_empty_nodes(self):
        """When nodes list is empty, snapshot falls back to aggregate checks."""
        snapshot = ClusterResourceSnapshot(
            connected=True,
            cluster_health="HEALTHY",
            total_nodes=3,
            ready_nodes=3,
            total_cpu_cores=24.0,
            allocatable_cpu_cores=24.0,
            used_cpu_cores=6.0,
            free_cpu_cores=18.0,
            total_memory_mib=49152.0,
            allocatable_memory_mib=49152.0,
            used_memory_mib=12288.0,
            free_memory_mib=36864.0,
            total_gpus=2,
            allocatable_gpus=2,
            used_gpus=0,
            free_gpus=2,
            nodes=[],  # Empty node inventory
        )
        feasible, msg = snapshot.is_resource_feasible(cpu_request_cores=8.0)
        assert feasible is True  # In fallback mode, 18.0 free cores >= 8.0 passes
        assert msg == "Cluster resources available"
