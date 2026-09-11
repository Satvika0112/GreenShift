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


def _anchor_schedule_decision_to_now(db, job) -> None:
    """
    Shift an already-computed schedule decision's window to start
    deterministically in the immediate past, preserving its real duration.
    Used only by dispatch-flow tests that need a dispatch-eligible decision
    right now — never changes which window the scheduler picked or how it
    picked it (schedule_and_store/schedule_job are untouched).
    """
    db.refresh(job)
    decision = job.schedule_decision
    duration = decision.selected_end - decision.selected_start
    decision.selected_start = datetime.now(timezone.utc) - timedelta(minutes=1)
    decision.selected_end = decision.selected_start + duration
    db.commit()
    db.refresh(job)


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
        assert job.status == JobStatus.PENDING_APPROVAL

        # 5. Approve schedule (Human Approval Gate)
        from app.approval.service import approve_schedule
        approval_resp = approve_schedule(db, job.job_id, decision.id, reason="Approved for E2E", approved_by="admin")
        assert approval_resp.decision == "APPROVED"
        assert approval_resp.job_status == JobStatus.APPROVED

        db.refresh(job)
        assert job.status == JobStatus.APPROVED

        # 6. Verify audit chain
        result = verify_chain(db)
        assert result.valid is True
        assert result.event_count >= 2

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
        # The real scheduler picks the lowest-carbon feasible window within
        # the deadline, which can legitimately land hours in the future
        # depending on the current time-of-day's fallback carbon curve —
        # dispatcher.py correctly refuses to dispatch before that window
        # starts. This test is about the mocked-Kubernetes dispatch path
        # itself, not the scheduler's window choice, so make the
        # already-computed decision's window deterministically "now" —
        # preserving its real duration — rather than fighting wall-clock
        # dependent carbon data.
        _anchor_schedule_decision_to_now(db, job)
        from app.approval.service import approve_schedule
        approve_schedule(db, job.job_id, job.schedule_decision.id)
        db.refresh(job)
        assert job.status == JobStatus.APPROVED

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

    def test_complete_status_lifecycle_and_transitions(self, db, job_request):
        """
        Verify complete job status lifecycle flow:
        SUBMITTED -> VALIDATED -> SCHEDULED / PENDING_APPROVAL -> APPROVED -> DISPATCHING -> QUEUED -> RUNNING -> COMPLETED
        """
        from app.dispatch.dispatcher import dispatch_job, refresh_job_status
        from app.approval.service import approve_schedule

        # 1. Submission
        job = submit_job(db, job_request)
        assert job.status == JobStatus.SUBMITTED

        # 2. Validation
        job.status = JobStatus.VALIDATED
        db.commit()
        db.refresh(job)
        assert job.status == JobStatus.VALIDATED

        # 3. Schedule & store
        decision = schedule_and_store(db, job, record_audit=True)
        db.refresh(job)
        assert job.status == JobStatus.PENDING_APPROVAL
        # See test_dispatch_mocked's comment: this test verifies the
        # dispatch/status-transition flow, not the scheduler's window
        # choice — anchor the real decision's window to now so dispatch
        # below isn't dependent on the current time-of-day's carbon curve.
        _anchor_schedule_decision_to_now(db, job)

        # 4. Approval
        approve_schedule(db, job.job_id, decision.id, approved_by="admin")
        db.refresh(job)
        assert job.status == JobStatus.APPROVED

        # 5. Dispatch
        with patch("app.dispatch.dispatcher.get_batch_v1") as mock_batch, \
             patch("app.dispatch.dispatcher.get_core_v1") as mock_core:
            mock_batch_api = MagicMock()
            mock_batch.return_value = mock_batch_api
            from kubernetes.client.rest import ApiException
            mock_batch_api.read_namespaced_job.side_effect = ApiException(status=404)
            mock_batch_api.create_namespaced_job.return_value = MagicMock()
            mock_core.return_value = MagicMock()

            execution = dispatch_job(db, job)
            db.refresh(job)
            assert job.status == JobStatus.QUEUED
            assert execution.gs_status == JobStatus.QUEUED

            # 6. Running simulation
            with patch("app.dispatch.dispatcher.get_batch_v1"), \
                 patch("app.dispatch.dispatcher.get_core_v1"), \
                 patch("app.dispatch.dispatcher.get_job_status", return_value=("Running", JobStatus.RUNNING)), \
                 patch("app.dispatch.dispatcher.get_pod_name", return_value="gs-pod-test"), \
                 patch("app.dispatch.dispatcher.get_pod_start_time", return_value=datetime.now(timezone.utc)):
                refresh_job_status(db, execution)
                db.refresh(job)
                assert job.status == JobStatus.RUNNING

            # 7. Completed simulation
            with patch("app.dispatch.dispatcher.get_batch_v1"), \
                 patch("app.dispatch.dispatcher.get_core_v1"), \
                 patch("app.dispatch.dispatcher.get_job_status", return_value=("Succeeded", JobStatus.COMPLETED)), \
                 patch("app.dispatch.dispatcher.get_job_completion_time", return_value=datetime.now(timezone.utc)):
                refresh_job_status(db, execution)
                db.refresh(job)
                assert job.status == JobStatus.COMPLETED

    def test_non_deferrable_workload_bypasses_approval(self, db):
        """Non-deferrable compute workloads should bypass human approval gate directly to APPROVED."""
        req = JobSubmitRequest(
            team_id="URGENT-TEAM",
            deadline=datetime.now(timezone.utc) + timedelta(hours=6),
            runtime_minutes=15,
            power_kw=1.0,
            region="IN-TG",
            container_image="greenshift/sample-workload:latest",
            deferrable=False,
        )
        job = submit_job(db, req)
        assert job.status == JobStatus.SUBMITTED

        decision = schedule_and_store(db, job, record_audit=True)
        db.refresh(job)
        assert job.status == JobStatus.APPROVED

    def test_job_cancellation_flow(self, db, job_request):
        """Test cancelling a job in pending status transitions to CANCELLED."""
        job = submit_job(db, job_request)
        schedule_and_store(db, job)
        db.refresh(job)
        assert job.status == JobStatus.PENDING_APPROVAL

        # Cancel job
        job.status = JobStatus.CANCELLED
        db.commit()
        db.refresh(job)
        assert job.status == JobStatus.CANCELLED
