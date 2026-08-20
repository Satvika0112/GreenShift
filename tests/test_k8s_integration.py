"""
Live Kubernetes Integration Test.

REQUIRES: A running Kubernetes cluster with the 'greenshift' namespace.
Run only when Kubernetes is available:

  pytest tests/test_k8s_integration.py -v --k8s

Skipped automatically when Kubernetes is not reachable.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.dispatch.kubernetes_client import check_kubernetes_available
from app.dispatch.dispatcher import dispatch_job
from app.ingest.jobs import submit_job
from app.decide.service import schedule_and_store
from app.shared.models import JobSubmitRequest, JobStatus


def pytest_configure(config):
    config.addinivalue_line("markers", "k8s: requires a live Kubernetes cluster")


def is_k8s_available():
    try:
        return check_kubernetes_available()
    except Exception:
        return False


K8S_SKIP = pytest.mark.skipif(
    not is_k8s_available(),
    reason="Kubernetes cluster not available",
)


@K8S_SKIP
class TestLiveKubernetes:
    """
    These tests create REAL Kubernetes Jobs.
    They require the 'greenshift' namespace and the dispatcher ServiceAccount.
    """

    def test_dispatch_creates_kubernetes_job(self, db):
        """Create a real Kubernetes Job and verify it appears in the cluster."""
        req = JobSubmitRequest(
            team_id="K8S-TEST",
            deadline=datetime.now(timezone.utc) + timedelta(hours=2),
            runtime_minutes=1,
            power_kw=0.1,
            region="IN-WE",
            container_image="greenshift/sample-workload:latest",
            cpu_request="100m",
            memory_request="64Mi",
        )
        job = submit_job(db, req)
        schedule_and_store(db, job)
        db.refresh(job)

        execution = dispatch_job(db, job)
        assert execution.kubernetes_job_name.startswith("gs-")

        # Verify the job exists in Kubernetes
        from app.dispatch.kubernetes_client import get_batch_v1
        batch = get_batch_v1()
        k8s_job = batch.read_namespaced_job(
            name=execution.kubernetes_job_name,
            namespace=execution.kubernetes_namespace,
        )
        assert k8s_job is not None
        assert k8s_job.metadata.labels.get("greenshift-job-id") == job.job_id

    def test_kubernetes_job_labels(self, db):
        """Dispatched Job must have correct GreenShift labels."""
        req = JobSubmitRequest(
            team_id="LABEL-TEST",
            deadline=datetime.now(timezone.utc) + timedelta(hours=2),
            runtime_minutes=1,
            power_kw=0.1,
            region="IN-WE",
            container_image="greenshift/sample-workload:latest",
        )
        job = submit_job(db, req)
        schedule_and_store(db, job)
        db.refresh(job)

        execution = dispatch_job(db, job)
        from app.dispatch.kubernetes_client import get_batch_v1
        batch = get_batch_v1()
        k8s_job = batch.read_namespaced_job(
            name=execution.kubernetes_job_name,
            namespace=execution.kubernetes_namespace,
        )
        labels = k8s_job.metadata.labels
        assert labels.get("app") == "greenshift"
        assert labels.get("greenshift-job-id") == job.job_id
        assert labels.get("greenshift-team-id") == job.team_id
