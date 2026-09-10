"""
Unit and Integration Tests for Kubernetes Dispatcher and Client.

Covers:
  1. Local Kubernetes configuration selection (k8s_in_cluster=False)
  2. In-cluster configuration selection (k8s_in_cluster=True)
  3. Invalid Kubernetes configuration handling
  4. Kubernetes connectivity health check (healthy vs unreachable)
  5. Dynamic Job generation (V1Job structure, restartPolicy, backoffLimit, TTL)
  6. Correct namespace routing
  7. Correct metadata and labels (job ID, team ID, region, annotations)
  8. Correct CPU/memory configuration and scaling
  9. Idempotent dispatch behavior (skips duplicate creation if Job exists)

All unit tests mock external Kubernetes API calls so they run deterministically in any CI/CD environment.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException

from app.dispatch.job_builder import build_kubernetes_job, _scale_cpu, _scale_memory
from app.dispatch.kubernetes_client import (
    _load_kube_config,
    get_api_client,
    get_batch_v1,
    get_core_v1,
    check_kubernetes_available,
    reset_kubernetes_client,
    is_running_in_container,
)
from app.dispatch.dispatcher import dispatch_job, refresh_job_status, DispatchError
from app.shared.config import settings
from app.shared.models import (
    JobORM,
    JobStatus,
    ScheduleDecisionORM,
    KubernetesExecutionORM,
)
from app.shared.utils import utcnow


@pytest.fixture(autouse=True)
def reset_client_fixture():
    """Ensure clean Kubernetes client state before each test."""
    reset_kubernetes_client()
    yield
    reset_kubernetes_client()


class TestKubernetesClientConfiguration:
    """Test suite for Kubernetes configuration modes."""

    def test_local_kubeconfig_mode_selected_when_not_in_cluster(self):
        """When k8s_in_cluster=False, local kubeconfig loader must be invoked."""
        with patch.object(settings, "k8s_in_cluster", False), \
             patch("kubernetes.config.load_kube_config") as mock_load_kube, \
             patch("kubernetes.config.load_incluster_config") as mock_load_incluster:

            client = _load_kube_config()
            assert client is not None
            mock_load_kube.assert_called_once()
            mock_load_incluster.assert_not_called()

    def test_in_cluster_mode_selected_when_in_cluster_true(self):
        """When k8s_in_cluster=True, in-cluster loader must be invoked."""
        with patch.object(settings, "k8s_in_cluster", True), \
             patch("kubernetes.config.load_kube_config") as mock_load_kube, \
             patch("kubernetes.config.load_incluster_config") as mock_load_incluster:

            client = _load_kube_config()
            assert client is not None
            mock_load_incluster.assert_called_once()
            mock_load_kube.assert_not_called()

    def test_invalid_kubeconfig_raises_clean_runtime_error(self):
        """ConfigException during local kubeconfig load must raise descriptive RuntimeError."""
        with patch.object(settings, "k8s_in_cluster", False), \
             patch("kubernetes.config.load_kube_config", side_effect=ConfigException("Invalid kubeconfig syntax")):

            with pytest.raises(RuntimeError) as exc_info:
                _load_kube_config()
            assert "Failed to load local kubeconfig" in str(exc_info.value)

    def test_invalid_incluster_config_raises_clean_runtime_error(self):
        """ConfigException during in-cluster load must raise descriptive RuntimeError."""
        with patch.object(settings, "k8s_in_cluster", True), \
             patch("kubernetes.config.load_incluster_config", side_effect=ConfigException("ServiceAccount token missing")):

            with pytest.raises(RuntimeError) as exc_info:
                _load_kube_config()
            assert "Failed to load in-cluster Kubernetes config" in str(exc_info.value)

    def test_explicit_host_override_applied(self):
        """When k8s_host_override is set, it overrides the client host endpoint."""
        with patch.object(settings, "k8s_in_cluster", False), \
             patch.object(settings, "k8s_host_override", "https://custom-k8s.example.com:6443"), \
             patch("kubernetes.config.load_kube_config"):

            client = _load_kube_config()
            assert client.configuration.host == "https://custom-k8s.example.com:6443"


class TestKubernetesHealthCheck:
    """Test suite for check_kubernetes_available()."""

    def test_health_check_returns_true_when_api_responds(self):
        """Successful namespace query indicates Kubernetes API is healthy."""
        mock_core = MagicMock()
        mock_core.list_namespace.return_value = MagicMock(items=[MagicMock()])

        with patch("app.dispatch.kubernetes_client.socket.create_connection"), \
             patch("app.dispatch.kubernetes_client.get_core_v1", return_value=mock_core):
            assert check_kubernetes_available() is True
            mock_core.list_namespace.assert_called_once_with(limit=1, _request_timeout=3)

    def test_health_check_returns_false_on_connection_failure(self):
        """Connection / API exception must return False without crashing."""
        mock_core = MagicMock()
        mock_core.list_namespace.side_effect = Exception("Connection refused to 127.0.0.1:6443")
        mock_core.list_namespaced_pod.side_effect = Exception("Connection refused to 127.0.0.1:6443")

        with patch("app.dispatch.kubernetes_client.get_core_v1", return_value=mock_core):
            assert check_kubernetes_available(force=True) is False


class TestDynamicJobBuilder:
    """Test suite for build_kubernetes_job()."""

    @pytest.fixture
    def sample_job_and_decision(self):
        start_time = datetime(2026, 9, 10, 14, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2026, 9, 10, 15, 0, 0, tzinfo=timezone.utc)

        job = JobORM(
            job_id="JOB-TEST-101",
            team_id="ENERGY-TEAM",
            submitted_at=utcnow(),
            deadline=start_time + timedelta(hours=5),
            runtime_minutes=60,
            power_kw=1.5,
            region="IN-SO",
            container_image="greenshift/sample-workload:latest",
            cpu_request="500m",
            memory_request="512Mi",
            status=JobStatus.SCHEDULED,
        )
        decision = ScheduleDecisionORM(
            job_id="JOB-TEST-101",
            selected_start=start_time,
            selected_end=end_time,
            carbon_intensity=350.0,
            electricity_cost=0.08,
            carbon_emission=0.0525,
            reason="Lowest carbon intensity slot",
            region_id="IN-SO",
            tariff_plan="HT-I(A)",
        )
        return job, decision

    def test_job_metadata_and_labels(self, sample_job_and_decision):
        job, decision = sample_job_and_decision
        k8s_job = build_kubernetes_job(job, decision, namespace="greenshift")

        assert k8s_job.api_version == "batch/v1"
        assert k8s_job.kind == "Job"
        assert k8s_job.metadata.name == "gs-job-test-101"
        assert k8s_job.metadata.namespace == "greenshift"

        labels = k8s_job.metadata.labels
        assert labels["app"] == "greenshift"
        assert labels["greenshift-job-id"] == "JOB-TEST-101"
        assert labels["greenshift-team-id"] == "ENERGY-TEAM"
        assert labels["greenshift-region"] == "IN-SO"

        annotations = k8s_job.metadata.annotations
        assert annotations["greenshift/selected-carbon"] == "350.0"
        assert annotations["greenshift/selected-cost"] == "0.08"
        assert annotations["greenshift/carbon-emission-kg"] == "0.0525"

    def test_job_spec_restart_policy_and_ttl(self, sample_job_and_decision):
        job, decision = sample_job_and_decision
        k8s_job = build_kubernetes_job(job, decision)

        spec = k8s_job.spec
        assert spec.backoff_limit == 0
        assert spec.ttl_seconds_after_finished == 3600
        assert spec.template.spec.restart_policy == "Never"

    def test_container_environment_and_resources(self, sample_job_and_decision):
        job, decision = sample_job_and_decision
        k8s_job = build_kubernetes_job(job, decision)

        container = k8s_job.spec.template.spec.containers[0]
        assert container.name == "workload"
        assert container.image == "greenshift/sample-workload:latest"

        env_map = {e.name: e.value for e in container.env}
        assert env_map["JOB_ID"] == "JOB-TEST-101"
        assert env_map["TEAM_ID"] == "ENERGY-TEAM"
        assert env_map["DURATION_SECONDS"] == "3600"
        assert env_map["REGION"] == "IN-SO"
        assert env_map["CARBON_INTENSITY"] == "350.0"

        reqs = container.resources.requests
        limits = container.resources.limits
        assert reqs["cpu"] == "500m"
        assert reqs["memory"] == "512Mi"
        assert limits["cpu"] == "1000m"
        assert limits["memory"] == "1024Mi"

    def test_resource_scaling_helpers(self):
        assert _scale_cpu("500m") == "1000m"
        assert _scale_cpu("2") == "4.0"
        assert _scale_memory("512Mi") == "1024Mi"
        assert _scale_memory("2Gi") == "4Gi"

    def test_node_affinity_when_preferred_node_provided(self, sample_job_and_decision):
        job, decision = sample_job_and_decision
        k8s_job = build_kubernetes_job(job, decision, preferred_node="node-2-worker-gpu")

        pod_spec = k8s_job.spec.template.spec
        assert pod_spec.affinity is not None
        node_aff = pod_spec.affinity.node_affinity
        assert node_aff is not None
        assert node_aff.preferred_during_scheduling_ignored_during_execution is not None
        term = node_aff.preferred_during_scheduling_ignored_during_execution[0]
        assert term.weight == 100
        req = term.preference.match_expressions[0]
        assert req.key == "kubernetes.io/hostname"
        assert "node-2-worker-gpu" in req.values

    def test_gpu_node_selector_when_gpu_requested(self, sample_job_and_decision):
        job, decision = sample_job_and_decision
        job.gpu_request = 2
        k8s_job = build_kubernetes_job(job, decision)

        pod_spec = k8s_job.spec.template.spec
        assert pod_spec.affinity is not None
        node_aff = pod_spec.affinity.node_affinity
        assert node_aff is not None
        req_terms = node_aff.required_during_scheduling_ignored_during_execution
        assert req_terms is not None
        match_expr = req_terms.node_selector_terms[0].match_expressions[0]
        assert match_expr.key == "nvidia.com/gpu.present"
        assert match_expr.values == ["true"]

        container = pod_spec.containers[0]
        assert container.resources.requests["nvidia.com/gpu"] == "2"
        assert container.resources.limits["nvidia.com/gpu"] == "2"


class TestDispatcherIdempotencyAndFlow:
    """Test suite for dispatch_job() idempotency and error handling."""

    def test_idempotent_dispatch_skips_creation_if_job_already_exists(self, db):
        """If Kubernetes Job exists, dispatcher must not fail and must not re-create."""
        start_time = datetime.now(timezone.utc)
        now = utcnow()
        job = JobORM(
            job_id="JOB-IDEM-001",
            team_id="IDEM-TEAM",
            submitted_at=now,
            deadline=now + timedelta(hours=2),
            runtime_minutes=10,
            power_kw=1.0,
            region="IN-SO",
            container_image="greenshift/sample-workload:latest",
            cpu_request="200m",
            memory_request="128Mi",
            status=JobStatus.APPROVED,
        )
        decision = ScheduleDecisionORM(
            job_id="JOB-IDEM-001",
            selected_start=start_time,
            selected_end=start_time + timedelta(minutes=10),
            carbon_intensity=300.0,
            electricity_cost=0.05,
            carbon_emission=0.01,
            reason="Lowest carbon window",
            region_id="IN-SO",
            tariff_plan="HT-I(A)",
        )
        job.schedule_decision = decision
        db.add(job)
        db.commit()

        mock_batch = MagicMock()
        mock_batch.read_namespaced_job.return_value = MagicMock()  # Job exists

        with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch):
            execution = dispatch_job(db, job)
            assert execution is not None
            assert execution.gs_status == JobStatus.QUEUED
            mock_batch.create_namespaced_job.assert_not_called()

    def test_dispatch_raises_if_no_schedule_decision(self, db):
        """A job without a schedule decision must raise DispatchError."""
        now = utcnow()
        job = JobORM(
            job_id="JOB-NO-DEC",
            team_id="TEST",
            submitted_at=now,
            deadline=now + timedelta(hours=2),
            runtime_minutes=5,
            power_kw=1.0,
            region="IN-SO",
            container_image="greenshift/sample-workload:latest",
            status=JobStatus.APPROVED,
        )
        db.add(job)
        db.commit()

        with pytest.raises(DispatchError) as exc_info:
            dispatch_job(db, job)
        assert "has no schedule decision" in str(exc_info.value)


class TestUtcDispatcherScheduling:
    """Test suite for UTC scheduling filter and timezone handling."""

    def test_utc_ready_filtering_only_dispatches_due_jobs(self):
        """Jobs in the future must not be dispatched; jobs in the past/now must be."""
        from app.dispatch.service import _filter_ready

        now = utcnow()
        past_job = MagicMock()
        past_job.job_id = "JOB-PAST"
        past_job.schedule_decision.selected_start = now - timedelta(minutes=5)

        future_job = MagicMock()
        future_job.job_id = "JOB-FUTURE"
        future_job.schedule_decision.selected_start = now + timedelta(hours=1)

        ready = _filter_ready([past_job, future_job])
        assert len(ready) == 1
        assert ready[0].job_id == "JOB-PAST"


class TestDispatcherStatusSync:
    """Test suite for status synchronization to database."""

    def test_refresh_status_synchronizes_to_job_orm(self, db):
        """When Kubernetes Job completes, JobORM and KubernetesExecutionORM must both transition to COMPLETED."""
        now = utcnow()
        job = JobORM(
            job_id="JOB-SYNC-001",
            team_id="SYNC-TEAM",
            submitted_at=now,
            deadline=now + timedelta(hours=2),
            runtime_minutes=5,
            power_kw=1.0,
            region="IN-TG",
            container_image="greenshift/sample-workload:latest",
            status=JobStatus.RUNNING,
        )
        execution = KubernetesExecutionORM(
            job_id="JOB-SYNC-001",
            kubernetes_job_name="gs-job-sync-001",
            kubernetes_namespace="greenshift",
            planned_start=now,
            planned_end=now + timedelta(minutes=5),
            gs_status=JobStatus.RUNNING,
            pod_name="gs-job-sync-001-pod",
            created_at=now,
        )
        job.kubernetes_execution = execution
        db.add(job)
        db.commit()

        mock_batch = MagicMock()
        mock_core = MagicMock()

        with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch), \
             patch("app.dispatch.dispatcher.get_core_v1", return_value=mock_core), \
             patch("app.dispatch.dispatcher.get_job_status", return_value=("Complete", JobStatus.COMPLETED)), \
             patch("app.dispatch.dispatcher.get_pod_start_time", return_value=now + timedelta(minutes=1)), \
             patch("app.dispatch.dispatcher.get_job_completion_time", return_value=now + timedelta(minutes=4)):

            updated = refresh_job_status(db, execution)
            assert updated.gs_status == JobStatus.COMPLETED
            assert updated.actual_end is not None
            assert job.status == JobStatus.COMPLETED

