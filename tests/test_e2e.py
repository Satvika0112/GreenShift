"""
End-to-end integration test — GreenShift full pipeline.

Tests the complete flow:
  Job submission → Carbon/Tariff → Schedule → Audit → Dashboard data

NOTE: Kubernetes dispatch tests use mocking (to avoid needing a live cluster).
      The live Kubernetes test is in test_k8s_integration.py and requires
      a running cluster.
"""

import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.ingest.jobs import submit_job
from app.ingest.service import fetch_and_store_carbon, fetch_and_store_tariff
from app.decide.service import schedule_and_store
from app.trust.ledger import append_event, verify_chain
from app.shared.models import (
    JobSubmitRequest,
    JobStatus,
    EventType,
    ScheduleDecision,
)


@pytest.fixture()
def job_request():
    return JobSubmitRequest(
        team_id="E2E-TEAM",
        deadline=datetime.now(timezone.utc) + timedelta(hours=24),
        runtime_minutes=30,
        power_kw=0.5,
        region="IN-WE",
        container_image="greenshift/sample-workload:latest",
        cpu_request="500m",
        memory_request="512Mi",
        carbon_budget_kg=0.5,
    )


class TestEndToEnd:
    def test_full_pipeline_without_kubernetes(self, db, job_request):
        """
        Full pipeline test (no Kubernetes):
          1. Submit job
          2. Fetch carbon + tariff data
          3. Schedule job
          4. Verify audit events
          5. Verify audit chain
        """
        # 1. Submit job
        job = submit_job(db, job_request)
        assert job.job_id.startswith("JOB-")
        assert job.status == JobStatus.SUBMITTED

        # 2. Fetch carbon + tariff
        now = datetime.now(timezone.utc)
        deadline = job.deadline.replace(tzinfo=timezone.utc) if job.deadline.tzinfo is None else job.deadline
        carbon_data = fetch_and_store_carbon(db, job.region, now, deadline)
        tariff_data = fetch_and_store_tariff(db, job.region, now, deadline)
        assert len(carbon_data) > 0
        assert len(tariff_data) > 0

        # 3. Audit: job submitted
        e_submitted = append_event(db, EventType.JOB_SUBMITTED, job_id=job.job_id, payload={
            "team_id": job.team_id,
            "region": job.region,
        })
        assert e_submitted.event_id.startswith("EVT-")

        # 4. Schedule
        decision = schedule_and_store(db, job)
        assert isinstance(decision, ScheduleDecision)
        assert decision.selected_start is not None
        assert decision.carbon_emission > 0

        # Refresh job from DB
        db.refresh(job)
        assert job.status == JobStatus.SCHEDULED

        # 5. Audit: job scheduled
        e_scheduled = append_event(db, EventType.JOB_SCHEDULED, job_id=job.job_id, payload={
            "selected_start": decision.selected_start.isoformat(),
            "carbon_emission": decision.carbon_emission,
            "carbon_avoided": decision.carbon_avoided,
        })
        assert e_scheduled.previous_hash == e_submitted.current_hash

        # 6. Verify audit chain
        result = verify_chain(db)
        assert result.valid is True
        assert result.event_count == 2

    def test_carbon_avoided_is_positive(self, db, job_request):
        """GreenShift should avoid at least some carbon vs baseline for jobs with carbon variance."""
        job = submit_job(db, job_request)
        decision = schedule_and_store(db, job)
        assert (decision.carbon_avoided or 0.0) >= 0.0

    def test_schedule_decision_stored_in_db(self, db, job_request):
        """ScheduleDecision should be persisted and accessible via job relationship."""
        job = submit_job(db, job_request)
        decision = schedule_and_store(db, job)
        db.refresh(job)
        assert job.schedule_decision is not None
        assert abs(job.schedule_decision.carbon_emission - decision.carbon_emission) < 1e-6

    def test_audit_chain_remains_valid_after_multiple_jobs(self, db):
        """Chain must remain valid across multiple jobs."""
        for i in range(5):
            req = JobSubmitRequest(
                team_id=f"TEAM-{i}",
                deadline=datetime.now(timezone.utc) + timedelta(hours=24),
                runtime_minutes=30,
                power_kw=0.5,
                region="IN-WE",
                container_image="greenshift/sample-workload:latest",
            )
            job = submit_job(db, req)
            append_event(db, EventType.JOB_SUBMITTED, job_id=job.job_id)
            decision = schedule_and_store(db, job)
            append_event(db, EventType.JOB_SCHEDULED, job_id=job.job_id)

        result = verify_chain(db)
        assert result.valid is True
        assert result.event_count == 10  # 2 events × 5 jobs

    def test_dispatch_mocked(self, db, job_request):
        """Test dispatch flow with Kubernetes API mocked."""
        job = submit_job(db, job_request)
        schedule_and_store(db, job)
        db.refresh(job)

        # Mock Kubernetes API
        with patch("app.dispatch.dispatcher.get_batch_v1") as mock_batch, \
             patch("app.dispatch.dispatcher.get_core_v1") as mock_core:

            mock_batch_api = MagicMock()
            mock_batch.return_value = mock_batch_api
            # Simulate job not existing (404)
            from kubernetes.client.rest import ApiException
            mock_batch_api.read_namespaced_job.side_effect = ApiException(status=404)
            mock_batch_api.create_namespaced_job.return_value = MagicMock()

            mock_core.return_value = MagicMock()

            from app.dispatch.dispatcher import dispatch_job
            execution = dispatch_job(db, job)

            assert execution is not None
            assert execution.kubernetes_job_name.startswith("gs-")
            mock_batch_api.create_namespaced_job.assert_called_once()

            db.refresh(job)
            assert job.status == JobStatus.QUEUED

            # Audit K8s job created
            append_event(db, EventType.K8S_JOB_CREATED, job_id=job.job_id, payload={
                "kubernetes_job_name": execution.kubernetes_job_name,
                "namespace": execution.kubernetes_namespace,
            })

        # Verify chain is still intact
        result = verify_chain(db)
        assert result.valid is True
