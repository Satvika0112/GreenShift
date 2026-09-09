"""
Unit and integration tests for horizontally scalable dispatcher with atomic job claiming.

Covers:
1. Atomic claiming (batch size, empty queue, skip non-ready, worker/lease assignment, disjoint claims, priority ordering)
2. Lease expiry recovery (expired claims recovered, active claims preserved, recovered claimable again)
3. Schedule promotion (promotes past start jobs, skips future start jobs)
4. Dispatch loop tick execution (promote -> claim -> dispatch cycle, empty queue safety, metadata cleanup)
5. State machine integrity (SUBMITTED -> SCHEDULED -> READY -> CLAIMING -> QUEUED -> RUNNING -> COMPLETED)
6. API workers monitoring endpoint (GET /api/v1/dispatch/workers)
7. Backward compatibility (manual dispatch with SCHEDULED/APPROVED status)
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.dispatch.dispatcher import dispatch_job
from app.dispatch.job_claimer import (
    WORKER_ID,
    CLAIM_BATCH_SIZE,
    claim_ready_jobs,
    recover_expired_claims,
    promote_scheduled_to_ready,
)
from app.dispatch.service import dispatch_loop_tick
from app.shared.database import get_db
from app.shared.auth import create_access_token, hash_password
from app.shared.models import (
    JobORM,
    JobStatus,
    ScheduleDecisionORM,
    KubernetesExecutionORM,
    UserORM,
    UserRole,
)
from app.shared.utils import utcnow


@pytest.fixture
def client(db):
    def _get_test_db():
        yield db
    app.dependency_overrides[get_db] = _get_test_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(db):
    user = UserORM(
        username="dispatch-admin",
        email="dispatch-admin@greenshift.io",
        hashed_password=hash_password("adminpass123"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user_id=user.id, username=user.username, role="ADMIN")
    return {"Authorization": f"Bearer {token}"}


def _create_job(
    db,
    job_id: str,
    status: JobStatus = JobStatus.READY,
    priority: str = "MEDIUM",
    deadline_offset_hours: int = 4,
    start_offset_minutes: int = -10,
    claimed_by: str = None,
    lease_expires_at: datetime = None,
) -> JobORM:
    now = utcnow()
    job = JobORM(
        job_id=job_id,
        team_id="SCALING-TEAM",
        submitted_at=now,
        deadline=now + timedelta(hours=deadline_offset_hours),
        runtime_minutes=30,
        power_kw=1.0,
        region="IN-SO",
        container_image="greenshift/sample-workload:latest",
        cpu_request="500m",
        memory_request="512Mi",
        status=status,
        priority=priority,
        claimed_by=claimed_by,
        claimed_at=now if claimed_by else None,
        lease_expires_at=lease_expires_at,
    )
    decision = ScheduleDecisionORM(
        job_id=job_id,
        selected_start=now + timedelta(minutes=start_offset_minutes),
        selected_end=now + timedelta(minutes=start_offset_minutes + 30),
        carbon_intensity=300.0,
        electricity_cost=0.08,
        carbon_emission=0.04,
        reason="Scalable batch slot",
        region_id="IN-SO",
        tariff_plan="HT-I(A)",
    )
    job.schedule_decision = decision
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class TestAtomicClaiming:
    """Test suite for claim_ready_jobs()."""

    def test_claim_returns_batch_of_ready_jobs(self, db):
        """Insert 100 READY jobs; claiming must return at most CLAIM_BATCH_SIZE (50), all in CLAIMING."""
        for i in range(100):
            _create_job(db, f"JOB-BATCH-{i:03d}", status=JobStatus.READY)

        claimed = claim_ready_jobs(db, batch_size=CLAIM_BATCH_SIZE)
        assert len(claimed) == CLAIM_BATCH_SIZE
        for job in claimed:
            assert job.status == JobStatus.CLAIMING
            assert job.claimed_by == WORKER_ID

    def test_claim_empty_queue_returns_empty(self, db):
        """When no jobs are READY, claim_ready_jobs returns an empty list."""
        claimed = claim_ready_jobs(db)
        assert claimed == []

    def test_claim_skips_non_ready_statuses(self, db):
        """Jobs in SUBMITTED, SCHEDULED, QUEUED, COMPLETED, FAILED must not be claimed."""
        _create_job(db, "JOB-SUBMITTED", status=JobStatus.SUBMITTED)
        _create_job(db, "JOB-SCHEDULED", status=JobStatus.SCHEDULED)
        _create_job(db, "JOB-QUEUED", status=JobStatus.QUEUED)
        _create_job(db, "JOB-COMPLETED", status=JobStatus.COMPLETED)
        _create_job(db, "JOB-FAILED", status=JobStatus.FAILED)

        claimed = claim_ready_jobs(db)
        assert claimed == []

    def test_claim_sets_worker_id_and_lease(self, db):
        """Claimed job must record worker_id, claimed_at, and lease_expires_at in the future."""
        _create_job(db, "JOB-LEASE-001", status=JobStatus.READY)

        claimed = claim_ready_jobs(db, batch_size=1)
        assert len(claimed) == 1
        job = claimed[0]
        assert job.claimed_by == WORKER_ID
        assert job.claimed_at is not None
        assert job.lease_expires_at is not None
        assert job.lease_expires_at > job.claimed_at

    def test_second_claim_gets_different_jobs(self, db):
        """Two sequential claims on a pool of READY jobs must return disjoint sets."""
        for i in range(10):
            _create_job(db, f"JOB-DISJOINT-{i:02d}", status=JobStatus.READY)

        batch1 = claim_ready_jobs(db, batch_size=5)
        batch2 = claim_ready_jobs(db, batch_size=5)

        ids1 = {j.job_id for j in batch1}
        ids2 = {j.job_id for j in batch2}

        assert len(ids1) == 5
        assert len(ids2) == 5
        assert ids1.isdisjoint(ids2)

    def test_claim_priority_ordering(self, db):
        """CRITICAL jobs must be claimed before LOW jobs."""
        _create_job(db, "JOB-PRIO-LOW", status=JobStatus.READY, priority="LOW")
        _create_job(db, "JOB-PRIO-CRIT", status=JobStatus.READY, priority="CRITICAL")
        _create_job(db, "JOB-PRIO-MED", status=JobStatus.READY, priority="MEDIUM")
        _create_job(db, "JOB-PRIO-HIGH", status=JobStatus.READY, priority="HIGH")

        claimed = claim_ready_jobs(db, batch_size=2)
        assert len(claimed) == 2
        claimed_ids = [j.job_id for j in claimed]
        assert claimed_ids[0] == "JOB-PRIO-CRIT"
        assert claimed_ids[1] == "JOB-PRIO-HIGH"


class TestLeaseRecovery:
    """Test suite for recover_expired_claims()."""

    def test_expired_claim_recovered_to_ready(self, db):
        """Job in CLAIMING whose lease has expired must return to READY with claim metadata cleared."""
        now = utcnow()
        past_lease = now - timedelta(minutes=5)
        _create_job(
            db,
            "JOB-EXPIRED-001",
            status=JobStatus.CLAIMING,
            claimed_by="crashed-worker",
            lease_expires_at=past_lease,
        )

        recovered = recover_expired_claims(db)
        assert recovered == 1

        job = db.query(JobORM).filter(JobORM.job_id == "JOB-EXPIRED-001").first()
        assert job.status == JobStatus.READY
        assert job.claimed_by is None
        assert job.claimed_at is None
        assert job.lease_expires_at is None

    def test_active_claim_not_recovered(self, db):
        """Job in CLAIMING with a valid future lease must NOT be recovered."""
        now = utcnow()
        future_lease = now + timedelta(minutes=2)
        _create_job(
            db,
            "JOB-ACTIVE-001",
            status=JobStatus.CLAIMING,
            claimed_by="active-worker",
            lease_expires_at=future_lease,
        )

        recovered = recover_expired_claims(db)
        assert recovered == 0

        job = db.query(JobORM).filter(JobORM.job_id == "JOB-ACTIVE-001").first()
        assert job.status == JobStatus.CLAIMING
        assert job.claimed_by == "active-worker"

    def test_recovered_job_claimable_again(self, db):
        """Once recovered, a job can immediately be claimed by another worker."""
        now = utcnow()
        past_lease = now - timedelta(minutes=10)
        _create_job(
            db,
            "JOB-RECLAIM-001",
            status=JobStatus.CLAIMING,
            claimed_by="dead-worker",
            lease_expires_at=past_lease,
        )

        recover_expired_claims(db)
        claimed = claim_ready_jobs(db, batch_size=1)
        assert len(claimed) == 1
        assert claimed[0].job_id == "JOB-RECLAIM-001"
        assert claimed[0].claimed_by == WORKER_ID


class TestPromotion:
    """Test suite for promote_scheduled_to_ready()."""

    def test_scheduled_promoted_when_start_time_passed(self, db):
        """SCHEDULED job whose selected_start <= now must transition to READY."""
        _create_job(db, "JOB-PROMO-001", status=JobStatus.SCHEDULED, start_offset_minutes=-5)

        promoted = promote_scheduled_to_ready(db)
        assert promoted == 1

        job = db.query(JobORM).filter(JobORM.job_id == "JOB-PROMO-001").first()
        assert job.status == JobStatus.READY

    def test_scheduled_not_promoted_when_future(self, db):
        """SCHEDULED job whose selected_start > now must stay SCHEDULED."""
        _create_job(db, "JOB-FUTURE-001", status=JobStatus.SCHEDULED, start_offset_minutes=60)

        promoted = promote_scheduled_to_ready(db)
        assert promoted == 0

        job = db.query(JobORM).filter(JobORM.job_id == "JOB-FUTURE-001").first()
        assert job.status == JobStatus.SCHEDULED


class TestDispatchLoop:
    """Test suite for dispatch_loop_tick()."""

    def test_dispatch_tick_promotes_claims_dispatches(self, db):
        """Full tick cycle: promotes scheduled job, claims it, and dispatches to K8s."""
        _create_job(db, "JOB-TICK-001", status=JobStatus.SCHEDULED, start_offset_minutes=-10)

        mock_batch = MagicMock()
        mock_core = MagicMock()

        with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch), \
             patch("app.dispatch.dispatcher.get_core_v1", return_value=mock_core):
            stats = dispatch_loop_tick(db)

        assert stats["promoted"] == 1
        assert stats["claimed"] == 1
        assert stats["dispatched"] == 1

        job = db.query(JobORM).filter(JobORM.job_id == "JOB-TICK-001").first()
        assert job.status in (JobStatus.QUEUED, JobStatus.RUNNING)

    def test_dispatch_tick_with_no_ready_jobs(self, db):
        """Empty database: tick runs cleanly without error and returns all zeros."""
        stats = dispatch_loop_tick(db)
        assert stats["recovered"] == 0
        assert stats["promoted"] == 0
        assert stats["claimed"] == 0
        assert stats["dispatched"] == 0
        assert stats["failed"] == 0

    def test_dispatch_clears_claim_metadata_after_success(self, db):
        """After successful dispatch, claimed_by, claimed_at, and lease_expires_at must be None."""
        now = utcnow()
        job = _create_job(
            db,
            "JOB-CLEAN-001",
            status=JobStatus.CLAIMING,
            claimed_by=WORKER_ID,
            lease_expires_at=now + timedelta(minutes=2),
        )

        mock_batch = MagicMock()
        mock_core = MagicMock()

        with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch), \
             patch("app.dispatch.dispatcher.get_core_v1", return_value=mock_core):
            execution = dispatch_job(db, job)

        assert execution.gs_status == JobStatus.QUEUED
        assert job.status == JobStatus.QUEUED
        assert job.claimed_by is None
        assert job.claimed_at is None
        assert job.lease_expires_at is None


class TestStateMachineAndAPI:
    """Test suite for JobStatus enum additions and monitoring API."""

    def test_ready_state_exists_in_enum(self):
        """JobStatus.READY and JobStatus.CLAIMING must exist in the enum."""
        assert JobStatus.READY == "READY"
        assert JobStatus.CLAIMING == "CLAIMING"
        assert "READY" in [s.value for s in JobStatus]
        assert "CLAIMING" in [s.value for s in JobStatus]

    def test_full_state_machine(self, db):
        """Walk a job through the complete state sequence: SUBMITTED -> SCHEDULED -> READY -> CLAIMING -> QUEUED -> RUNNING -> COMPLETED."""
        job = _create_job(db, "JOB-STATE-SEQ", status=JobStatus.SUBMITTED)
        assert job.status == JobStatus.SUBMITTED

        job.status = JobStatus.SCHEDULED
        db.commit()
        assert job.status == JobStatus.SCHEDULED

        job.status = JobStatus.READY
        db.commit()
        assert job.status == JobStatus.READY

        job.status = JobStatus.CLAIMING
        job.claimed_by = WORKER_ID
        job.lease_expires_at = utcnow() + timedelta(minutes=2)
        db.commit()
        assert job.status == JobStatus.CLAIMING

        job.status = JobStatus.QUEUED
        job.claimed_by = None
        db.commit()
        assert job.status == JobStatus.QUEUED

        job.status = JobStatus.RUNNING
        db.commit()
        assert job.status == JobStatus.RUNNING

        job.status = JobStatus.COMPLETED
        db.commit()
        assert job.status == JobStatus.COMPLETED

    def test_manual_dispatch_still_works(self, client, auth_headers, db):
        """Manual POST /api/v1/dispatch/{job_id} must work directly for SCHEDULED/APPROVED jobs."""
        job = _create_job(db, "JOB-MANUAL-001", status=JobStatus.APPROVED, start_offset_minutes=-1)

        mock_batch = MagicMock()
        mock_core = MagicMock()

        with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch), \
             patch("app.dispatch.dispatcher.get_core_v1", return_value=mock_core):
            response = client.post(f"/api/v1/dispatch/{job.job_id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "JOB-MANUAL-001"
        assert data["status"] == "QUEUED"

    def test_get_active_workers_endpoint(self, client, auth_headers, db):
        """GET /api/v1/dispatch/workers returns active workers list and queue counts."""
        now = utcnow()
        _create_job(db, "JOB-WK-1", status=JobStatus.READY)
        _create_job(db, "JOB-WK-2", status=JobStatus.READY)
        _create_job(
            db,
            "JOB-WK-3",
            status=JobStatus.CLAIMING,
            claimed_by="worker-alpha",
            lease_expires_at=now + timedelta(minutes=2),
        )

        response = client.get("/api/v1/dispatch/workers", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert "active_workers" in data
        assert "dispatch_queue" in data
        assert data["dispatch_queue"]["ready"] >= 2
        assert data["dispatch_queue"]["claiming"] >= 1

        worker_ids = [w["worker_id"] for w in data["active_workers"]]
        assert "worker-alpha" in worker_ids
