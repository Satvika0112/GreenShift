"""
Live Kubernetes Integration Test Suite for GreenShift.

Tests end-to-end workload dispatch, execution, monitoring, log extraction,
and cryptographic audit ledger verification on a live Kubernetes cluster.

Automatically skipped when no active Kubernetes cluster is reachable.
"""

import time
import pytest
from datetime import datetime, timedelta, timezone

from app.dispatch.kubernetes_client import (
    check_kubernetes_available,
    get_batch_v1,
    get_core_v1,
)
from app.dispatch.job_builder import build_kubernetes_job
from app.dispatch.dispatcher import dispatch_job, refresh_job_status
from app.ingest.jobs import submit_job
from app.decide.service import schedule_and_store
from app.approval.service import approve_schedule
from app.trust.ledger import verify_chain, get_job_audit
from app.shared.models import JobSubmitRequest, JobStatus


def pytest_configure(config):
    config.addinivalue_line("markers", "k8s: requires a live Kubernetes cluster")


def is_k8s_available() -> bool:
    try:
        return check_kubernetes_available()
    except Exception:
        return False


K8S_SKIP = pytest.mark.skipif(
    not is_k8s_available(),
    reason="Kubernetes cluster not available",
)


@pytest.fixture
def sample_k8s_job_request():
    return JobSubmitRequest(
        team_id="K8S-INTEG",
        deadline=datetime.now(timezone.utc) + timedelta(hours=24),
        runtime_minutes=1,
        power_kw=0.1,
        region="IN-SO",
        container_image="greenshift/sample-workload:latest",
        cpu_request="100m",
        memory_request="128Mi",
    )


@K8S_SKIP
class TestLiveKubernetesIntegration:
    """
    End-to-End Live Kubernetes Integration Tests.
    Requires an active Kubernetes cluster with 'greenshift' namespace.
    """

    def test_k8s_cluster_reachable(self):
        """Verify Kubernetes API server responds and is healthy."""
        assert check_kubernetes_available() is True

    def test_k8s_namespace_exists(self):
        """Verify the 'greenshift' namespace exists on the cluster."""
        core_v1 = get_core_v1()
        namespaces = core_v1.list_namespace()
        ns_names = [ns.metadata.name for ns in namespaces.items]
        assert "greenshift" in ns_names, "Namespace 'greenshift' not found"

    def test_k8s_job_spec_generation(self, db, sample_k8s_job_request):
        """Verify Kubernetes Job manifest builder generates valid specification."""
        job = submit_job(db, sample_k8s_job_request)
        schedule_and_store(db, job)
        db.refresh(job)
        sd_orm = job.schedule_decision
        manifest = build_kubernetes_job(job, sd_orm)

        assert manifest.api_version == "batch/v1"
        assert manifest.kind == "Job"
        assert manifest.metadata.namespace == "greenshift"
        assert manifest.metadata.name.startswith("gs-")
        assert manifest.spec.backoff_limit == 0
        # Pod spec checks
        pod_spec = manifest.spec.template.spec
        assert pod_spec.restart_policy == "Never"
        assert pod_spec.service_account_name == "default"

        # Container resource checks
        container = pod_spec.containers[0]
        assert container.image == "greenshift/sample-workload:latest"
        assert container.resources.requests["cpu"] == "100m"
        assert container.resources.requests["memory"] == "128Mi"

    def test_dispatch_creates_kubernetes_job(self, db, sample_k8s_job_request):
        """Create a real Kubernetes Job and verify it appears in the cluster."""
        job = submit_job(db, sample_k8s_job_request)
        schedule_and_store(db, job)
        db.refresh(job)

        # Fast-track start time so this dispatch mechanics test isn't blocked
        # by the execution-window gate (see ERROR-005 in docs/ERROR_LOG.md).
        sd_orm = job.schedule_decision
        now_utc = datetime.now(timezone.utc)
        sd_orm.selected_start = now_utc - timedelta(seconds=5)
        sd_orm.selected_end = sd_orm.selected_start + timedelta(minutes=1)
        db.commit()

        approve_schedule(db, job.job_id, job.schedule_decision.id, approved_by="admin-test")
        db.refresh(job)

        execution = dispatch_job(db, job)
        assert execution.kubernetes_job_name.startswith("gs-")
        assert execution.kubernetes_namespace == "greenshift"

        batch_v1 = get_batch_v1()
        k8s_job = batch_v1.read_namespaced_job(
            name=execution.kubernetes_job_name,
            namespace=execution.kubernetes_namespace,
        )
        assert k8s_job is not None
        assert k8s_job.metadata.labels.get("greenshift-job-id") == job.job_id
        assert k8s_job.metadata.labels.get("greenshift-team-id") == job.team_id

        # Clean up job
        batch_v1.delete_namespaced_job(
            name=execution.kubernetes_job_name,
            namespace=execution.kubernetes_namespace,
            propagation_policy="Background",
        )

    def test_kubernetes_job_labels(self, db, sample_k8s_job_request):
        """Dispatched Job must carry all required GreenShift labels."""
        job = submit_job(db, sample_k8s_job_request)
        schedule_and_store(db, job)
        db.refresh(job)

        sd_orm = job.schedule_decision
        now_utc = datetime.now(timezone.utc)
        sd_orm.selected_start = now_utc - timedelta(seconds=5)
        sd_orm.selected_end = sd_orm.selected_start + timedelta(minutes=1)
        db.commit()

        approve_schedule(db, job.job_id, job.schedule_decision.id, approved_by="admin-test")
        db.refresh(job)

        execution = dispatch_job(db, job)
        batch_v1 = get_batch_v1()
        k8s_job = batch_v1.read_namespaced_job(
            name=execution.kubernetes_job_name,
            namespace=execution.kubernetes_namespace,
        )
        labels = k8s_job.metadata.labels
        assert labels.get("app") == "greenshift"
        assert labels.get("greenshift-job-id") == job.job_id
        assert labels.get("greenshift-team-id") == job.team_id
        assert labels.get("greenshift-region") == job.region

        # Clean up
        batch_v1.delete_namespaced_job(
            name=execution.kubernetes_job_name,
            namespace=execution.kubernetes_namespace,
            propagation_policy="Background",
        )

    def test_k8s_pod_execution_completion_logs_and_audit(self, db):
        """
        Closed-loop execution test:
        1. Submit and approve workload
        2. Dispatch to live cluster
        3. Poll until pod completion
        4. Read pod logs and assert completion banner
        5. Verify cryptographic audit chain integrity
        6. Clean up K8s resources
        """
        req = JobSubmitRequest(
            team_id="LIVE-EXEC",
            deadline=datetime.now(timezone.utc) + timedelta(hours=24),
            runtime_minutes=1,
            power_kw=0.1,
            region="IN-SO",
            container_image="greenshift/sample-workload:latest",
            cpu_request="100m",
            memory_request="128Mi",
        )
        job = submit_job(db, req)
        schedule_and_store(db, job, record_audit=True)
        db.refresh(job)
        sd_orm = job.schedule_decision

        # Fast-track start time
        now_utc = datetime.now(timezone.utc)
        sd_orm.selected_start = now_utc - timedelta(seconds=5)
        sd_orm.selected_end = sd_orm.selected_start + timedelta(minutes=1)
        db.commit()

        approve_schedule(db, job.job_id, sd_orm.id, approved_by="pytest-runner")
        db.refresh(job)

        execution = dispatch_job(db, job)
        assert execution is not None

        batch_v1 = get_batch_v1()
        core_v1 = get_core_v1()

        # Poll pod until completion
        max_wait = 180
        start_time = time.time()
        completed = False

        while time.time() - start_time < max_wait:
            execution = refresh_job_status(db, execution)
            if execution.gs_status == JobStatus.COMPLETED:
                completed = True
                break
            elif execution.gs_status == JobStatus.FAILED:
                pytest.fail(f"Pod failed during execution: {execution.error_message}")
            time.sleep(3)

        assert completed is True, f"Job did not complete within {max_wait}s"
        assert execution.pod_name is not None

        # Verify pod logs
        logs = core_v1.read_namespaced_pod_log(
            name=execution.pod_name,
            namespace=execution.kubernetes_namespace,
        )
        assert "GreenShift Sample Workload" in logs
        assert "GreenShift Sample Workload COMPLETED" in logs

        # Verify cryptographic audit ledger
        audit_res = verify_chain(db)
        assert audit_res.valid is True
        assert audit_res.event_count > 0

        events = get_job_audit(db, job.job_id)
        event_types = [e.event_type.value for e in events]
        assert "APPROVAL_GRANTED" in event_types
        assert "K8S_JOB_CREATED" in event_types
        assert "K8S_JOB_COMPLETED" in event_types

        # Cleanup
        batch_v1.delete_namespaced_job(
            name=execution.kubernetes_job_name,
            namespace=execution.kubernetes_namespace,
            propagation_policy="Background",
        )

    def test_k8s_job_cleanup(self, db, sample_k8s_job_request):
        """Verify Kubernetes Job deletion works cleanly."""
        job = submit_job(db, sample_k8s_job_request)
        schedule_and_store(db, job)
        db.refresh(job)

        sd_orm = job.schedule_decision
        now_utc = datetime.now(timezone.utc)
        sd_orm.selected_start = now_utc - timedelta(seconds=5)
        sd_orm.selected_end = sd_orm.selected_start + timedelta(minutes=1)
        db.commit()

        approve_schedule(db, job.job_id, job.schedule_decision.id, approved_by="admin-test")
        db.refresh(job)

        execution = dispatch_job(db, job)
        batch_v1 = get_batch_v1()

        # Delete job
        status = batch_v1.delete_namespaced_job(
            name=execution.kubernetes_job_name,
            namespace=execution.kubernetes_namespace,
            propagation_policy="Background",
        )
        assert status is not None
