"""
Tests for GreenShift Human Approval Gate before Kubernetes Dispatch.

Covers:
1. Schedule moves to PENDING_APPROVAL after scheduling
2. APPROVE changes: PENDING_APPROVAL -> APPROVED
3. DECLINE changes: PENDING_APPROVAL -> DECLINED
4. Declined job cannot dispatch
5. Pending approval job cannot dispatch
6. Submitted job cannot dispatch
7. Approved job cannot dispatch before selected_start
8. Approved job can dispatch after selected_start
9. KubernetesExecutionORM is created only after approved dispatch
10. Duplicate approval is handled safely (idempotent)
11. Approval must belong to the correct schedule
12. Invalid schedule ID is rejected
13. Approval audit event is created (APPROVAL_GRANTED)
14. Decline audit event is created (APPROVAL_DECLINED)
15. End-to-end scenarios: Approve and Decline pipelines
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from app.approval.service import (
    ApprovalNotFoundError,
    ApprovalValidationError,
    approve_schedule,
    decline_schedule,
    get_job_approvals,
    get_pending_approvals,
)
from app.decide.service import schedule_and_store
from app.dispatch.dispatcher import dispatch_job, DispatchError, refresh_job_status
from app.dispatch.service import _get_jobs_ready_to_dispatch, _filter_ready
from app.ingest.jobs import submit_job
from app.shared.models import (
    ApprovalORM,
    AuditEventORM,
    EventType,
    JobORM,
    JobStatus,
    JobSubmitRequest,
    KubernetesExecutionORM,
    ScheduleDecisionORM,
)
from app.shared.utils import utcnow


@pytest.fixture(autouse=True)
def mock_carbon_for_approval_tests(monkeypatch):
    monkeypatch.setenv("SIMULATE_CARBON_API_DOWN", "true")


@pytest.fixture
def sample_job_req():
    now = utcnow()
    return JobSubmitRequest(
        job_id="TEST-APPROVAL-001",
        team_id="team-alpha",
        deadline=now + timedelta(hours=6),
        runtime_minutes=60,
        power_kw=10.0,
        region="IN-TG",
        container_image="busybox:latest",
    )


def test_schedule_moves_to_pending_approval(db, sample_job_req):
    """1. Test that scheduling transitions job status from SUBMITTED to PENDING_APPROVAL."""
    job = submit_job(db, sample_job_req)
    assert job.status == JobStatus.SUBMITTED

    decision = schedule_and_store(db, job, record_audit=True)
    db.refresh(job)

    assert job.status == JobStatus.PENDING_APPROVAL
    assert job.schedule_decision is not None
    assert decision.job_id == job.job_id

    # Check audit ledger has SCHEDULE_PROPOSED
    audit = (
        db.query(AuditEventORM)
        .filter(AuditEventORM.job_id == job.job_id, AuditEventORM.event_type == EventType.SCHEDULE_PROPOSED)
        .first()
    )
    assert audit is not None


def test_approve_changes_pending_to_approved(db, sample_job_req):
    """2. Test that APPROVE changes status from PENDING_APPROVAL to APPROVED."""
    job = submit_job(db, sample_job_req)
    schedule_and_store(db, job, record_audit=True)
    sd = job.schedule_decision

    resp = approve_schedule(
        db=db,
        job_id=job.job_id,
        schedule_id=sd.id,
        reason="Schedule fits window",
        approved_by="lead_engineer",
    )

    db.refresh(job)
    assert job.status == JobStatus.APPROVED
    assert resp.decision == "APPROVED"
    assert resp.job_status == JobStatus.APPROVED
    assert resp.approved_by == "lead_engineer"

    # Verify ApprovalORM record
    approvals = get_job_approvals(db, job.job_id)
    assert len(approvals) == 1
    assert approvals[0].decision == "APPROVED"
    assert approvals[0].schedule_decision_id == sd.id


def test_decline_changes_pending_to_declined(db, sample_job_req):
    """3. Test that DECLINE changes status from PENDING_APPROVAL to DECLINED."""
    job = submit_job(db, sample_job_req)
    schedule_and_store(db, job, record_audit=True)
    sd = job.schedule_decision

    resp = decline_schedule(
        db=db,
        job_id=job.job_id,
        schedule_id=sd.id,
        reason="Grid carbon too high during slot",
        approved_by="sustainability_officer",
    )

    db.refresh(job)
    assert job.status == JobStatus.DECLINED
    assert resp.decision == "DECLINED"
    assert resp.job_status == JobStatus.DECLINED
    assert resp.reason == "Grid carbon too high during slot"

    # Verify not FAILED
    assert job.status != JobStatus.FAILED


def test_declined_job_cannot_dispatch(db, sample_job_req):
    """4. Test that a declined job cannot be dispatched to Kubernetes."""
    job = submit_job(db, sample_job_req)
    schedule_and_store(db, job)
    decline_schedule(db, job.job_id, job.schedule_decision.id, reason="Declined")

    with pytest.raises(DispatchError) as excinfo:
        dispatch_job(db, job)
    err = str(excinfo.value).lower()
    assert "declined" in err or "requires approval" in err


def test_pending_approval_job_cannot_dispatch(db, sample_job_req):
    """5. Test that a job in PENDING_APPROVAL cannot be dispatched."""
    job = submit_job(db, sample_job_req)
    schedule_and_store(db, job)
    assert job.status == JobStatus.PENDING_APPROVAL

    with pytest.raises(DispatchError) as excinfo:
        dispatch_job(db, job)
    err = str(excinfo.value).lower()
    assert "pending approval" in err or "requires approval" in err


def test_submitted_job_cannot_dispatch(db, sample_job_req):
    """6. Test that a freshly submitted job cannot be dispatched."""
    job = submit_job(db, sample_job_req)
    assert job.status == JobStatus.SUBMITTED

    with pytest.raises(DispatchError) as excinfo:
        dispatch_job(db, job)
    err = str(excinfo.value).lower()
    assert "requires approval" in err or "no schedule decision" in err or "only approved jobs" in err


def test_approved_job_dispatch_timing(db, sample_job_req):
    """7 & 8. Test approved job dispatch eligibility based on selected_start."""
    job = submit_job(db, sample_job_req)
    schedule_and_store(db, job)
    approve_schedule(db, job.job_id, job.schedule_decision.id)

    # Scenario 7: Future start time -> not ready in polling filter
    future_time = utcnow() + timedelta(hours=2)
    job.schedule_decision.selected_start = future_time
    job.schedule_decision.selected_end = future_time + timedelta(minutes=job.runtime_minutes)
    db.commit()

    scheduled_jobs = _get_jobs_ready_to_dispatch(db)
    assert job in scheduled_jobs
    ready_jobs = _filter_ready(scheduled_jobs)
    assert job not in ready_jobs  # Not ready yet

    # Scenario 8: Past start time -> ready for dispatch
    past_time = utcnow() - timedelta(minutes=5)
    job.schedule_decision.selected_start = past_time
    job.schedule_decision.selected_end = past_time + timedelta(minutes=job.runtime_minutes)
    db.commit()

    ready_jobs_now = _filter_ready(_get_jobs_ready_to_dispatch(db))
    assert job in ready_jobs_now


@patch("app.dispatch.dispatcher.get_batch_v1")
def test_k8s_execution_created_only_after_approved_dispatch(mock_batch, db, sample_job_req):
    """9. Test that KubernetesExecutionORM is created only after approved dispatch."""
    mock_batch_client = MagicMock()
    from kubernetes.client.rest import ApiException
    mock_batch_client.read_namespaced_job.side_effect = ApiException(status=404)
    mock_batch.return_value = mock_batch_client

    job = submit_job(db, sample_job_req)
    schedule_and_store(db, job)
    approve_schedule(db, job.job_id, job.schedule_decision.id)

    assert job.kubernetes_execution is None

    execution = dispatch_job(db, job)
    db.refresh(job)

    assert job.status == JobStatus.QUEUED
    assert execution is not None
    assert job.kubernetes_execution is not None
    assert execution.job_id == job.job_id
    assert execution.gs_status == JobStatus.QUEUED


def test_duplicate_approval_is_handled_idempotently(db, sample_job_req):
    """10. Test duplicate approval requests return existing approval without error."""
    job = submit_job(db, sample_job_req)
    schedule_and_store(db, job)
    sd = job.schedule_decision

    resp1 = approve_schedule(db, job.job_id, sd.id, reason="First approval")
    resp2 = approve_schedule(db, job.job_id, sd.id, reason="Duplicate retry")

    assert resp1.id == resp2.id
    assert resp1.decision == resp2.decision == "APPROVED"
    assert job.status == JobStatus.APPROVED

    # Confirm only 1 ApprovalORM record was created
    approvals = get_job_approvals(db, job.job_id)
    assert len(approvals) == 1


def test_approval_must_belong_to_correct_schedule(db, sample_job_req):
    """11. Test that approval fails if schedule ID belongs to a different job."""
    job1 = submit_job(db, sample_job_req)
    schedule_and_store(db, job1)

    job2_req = JobSubmitRequest(
        job_id="TEST-APPROVAL-002",
        team_id="team-beta",
        deadline=utcnow() + timedelta(hours=8),
        runtime_minutes=30,
        power_kw=5.0,
        region="IN-GJ",
        container_image="ubuntu:latest",
    )
    job2 = submit_job(db, job2_req)
    schedule_and_store(db, job2)

    # Try to approve job1 using job2's schedule_id
    with pytest.raises(ApprovalValidationError) as excinfo:
        approve_schedule(db, job1.job_id, job2.schedule_decision.id)
    assert "belongs to job" in str(excinfo.value)


def test_invalid_schedule_id_rejected(db, sample_job_req):
    """12. Test that non-existent schedule ID is rejected."""
    job = submit_job(db, sample_job_req)
    schedule_and_store(db, job)

    with pytest.raises(ApprovalNotFoundError):
        approve_schedule(db, job.job_id, 999999)


def test_approval_and_decline_audit_events_created(db, sample_job_req):
    """13 & 14. Test APPROVAL_GRANTED and APPROVAL_DECLINED audit ledger entries."""
    # Test Approval Audit
    job1 = submit_job(db, sample_job_req)
    schedule_and_store(db, job1)
    approve_schedule(db, job1.job_id, job1.schedule_decision.id, reason="Audit test approve", approved_by="auditor1")

    ev_app = (
        db.query(AuditEventORM)
        .filter(AuditEventORM.job_id == job1.job_id, AuditEventORM.event_type == EventType.APPROVAL_GRANTED)
        .first()
    )
    assert ev_app is not None
    assert "auditor1" in ev_app.payload_json
    assert "APPROVED" in ev_app.payload_json

    # Test Decline Audit
    job2_req = JobSubmitRequest(
        job_id="TEST-APPROVAL-003",
        team_id="team-gamma",
        deadline=utcnow() + timedelta(hours=10),
        runtime_minutes=45,
        power_kw=8.0,
        region="IN-WB",
        container_image="python:3.11-slim",
    )
    job2 = submit_job(db, job2_req)
    schedule_and_store(db, job2)
    decline_schedule(db, job2.job_id, job2.schedule_decision.id, reason="Audit test decline", approved_by="auditor2")

    ev_dec = (
        db.query(AuditEventORM)
        .filter(AuditEventORM.job_id == job2.job_id, AuditEventORM.event_type == EventType.APPROVAL_DECLINED)
        .first()
    )
    assert ev_dec is not None
    assert "auditor2" in ev_dec.payload_json
    assert "DECLINED" in ev_dec.payload_json


def test_get_pending_approvals_listing(db, sample_job_req):
    """Test get_pending_approvals returns active pending approval jobs."""
    job = submit_job(db, sample_job_req)
    schedule_and_store(db, job)

    pending = get_pending_approvals(db)
    assert any(p.job_id == job.job_id for p in pending)

    # Once approved, no longer in pending list
    approve_schedule(db, job.job_id, job.schedule_decision.id)
    pending_after = get_pending_approvals(db)
    assert not any(p.job_id == job.job_id for p in pending_after)


@patch("app.dispatch.dispatcher.get_batch_v1")
def test_end_to_end_scenario_a_approve(mock_batch, db, sample_job_req):
    """End-to-End Scenario A: Submit -> Schedule (PENDING_APPROVAL) -> Approve (APPROVED) -> Dispatch (QUEUED)."""
    mock_batch_client = MagicMock()
    from kubernetes.client.rest import ApiException
    mock_batch_client.read_namespaced_job.side_effect = ApiException(status=404)
    mock_batch.return_value = mock_batch_client

    # 1. Create job
    job = submit_job(db, sample_job_req)
    assert job.status == JobStatus.SUBMITTED

    # 2. Run scheduling
    decision = schedule_and_store(db, job, record_audit=True)

    # 3 & 4. Schedule generated, job becomes PENDING_APPROVAL
    db.refresh(job)
    assert job.status == JobStatus.PENDING_APPROVAL

    # 5. Confirm no Kubernetes job exists
    assert job.kubernetes_execution is None

    # 6 & 7. Approve schedule -> becomes APPROVED
    approve_resp = approve_schedule(db, job.job_id, job.schedule_decision.id, reason="Approved for off-peak execution")
    db.refresh(job)
    assert job.status == JobStatus.APPROVED
    assert approve_resp.decision == "APPROVED"

    # 8. Advance / prepare selected start time
    job.schedule_decision.selected_start = utcnow() - timedelta(minutes=1)
    job.schedule_decision.selected_end = job.schedule_decision.selected_start + timedelta(minutes=job.runtime_minutes)
    db.commit()

    # 9, 10, 11. Dispatcher processes job -> K8s Job created -> QUEUED
    ready_jobs = _filter_ready(_get_jobs_ready_to_dispatch(db))
    assert job in ready_jobs

    exec_record = dispatch_job(db, job)
    db.refresh(job)
    assert job.status == JobStatus.QUEUED
    assert exec_record.gs_status == JobStatus.QUEUED
    assert job.kubernetes_execution is not None


def test_end_to_end_scenario_b_decline(db, sample_job_req):
    """End-to-End Scenario B: Submit -> Schedule (PENDING_APPROVAL) -> Decline (DECLINED) -> No Dispatch."""
    # 1. Create job
    job = submit_job(db, sample_job_req)
    assert job.status == JobStatus.SUBMITTED

    # 2. Run scheduling
    decision = schedule_and_store(db, job, record_audit=True)

    # 3. Job becomes PENDING_APPROVAL
    db.refresh(job)
    assert job.status == JobStatus.PENDING_APPROVAL

    # 4 & 5. Decline schedule -> becomes DECLINED
    decline_resp = decline_schedule(db, job.job_id, job.schedule_decision.id, reason="Cost threshold exceeded")
    db.refresh(job)
    assert job.status == JobStatus.DECLINED
    assert decline_resp.decision == "DECLINED"

    # 6. Verify no Kubernetes Job is created
    assert job.kubernetes_execution is None
    with pytest.raises(DispatchError):
        dispatch_job(db, job)

    # 7. Verify audit event exists
    ev_dec = (
        db.query(AuditEventORM)
        .filter(AuditEventORM.job_id == job.job_id, AuditEventORM.event_type == EventType.APPROVAL_DECLINED)
        .first()
    )
    assert ev_dec is not None
    assert "DECLINED" in ev_dec.payload_json
