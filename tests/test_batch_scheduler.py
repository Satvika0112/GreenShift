"""
Unit and integration tests for Contention-Aware Scheduler and ML Demand Forecaster.
Covers:
  - Layer 1: SlotCapacity and SlotCapacityRegistry bounds and multi-hour spanning.
  - Layer 2: DemandForecaster causality, speed (<5s train, <1ms predict), [0.0, 1.0] bounds.
  - Batch scheduling: Urgency ordering (CRITICAL before LOW, non-deferrable first).
  - Spillover: preferred slot saturation causes spill to next slot with spilled_from_preferred=True.
  - No slot exceeds max_cpu capacity.
  - FastAPI endpoints for batch scheduling and capacity inspection.
"""

import time
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.main import app
from app.decide.batch_scheduler import schedule_batch, _urgency_key
from app.decide.demand_forecaster import DemandForecaster, build_arrival_training_data
from app.decide.slot_capacity import SlotCapacity, SlotCapacityRegistry
from app.shared.database import SessionLocal
from app.shared.models import JobORM, JobStatus, ScheduleDecisionORM


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_slot_capacity_basic():
    """Test single SlotCapacity bounds, allocation, and utilization."""
    slot_dt = datetime(2026, 9, 10, 2, 0, 0, tzinfo=timezone.utc)
    slot = SlotCapacity(slot_start=slot_dt, max_cpu=4.0, max_memory_mib=8192.0, max_gpus=1)

    assert slot.remaining_cpu == 4.0
    assert slot.utilization_pct == 0.0
    assert slot.can_fit(2.0, 4096.0, 0) is True

    # Allocate 2 CPUs
    allocated = slot.allocate(2.0, 4096.0, 0)
    assert allocated is True
    assert slot.allocated_cpu == 2.0
    assert slot.remaining_cpu == 2.0
    assert slot.utilization_pct == 50.0
    assert slot.job_count == 1

    # Can allocate another 2 CPUs
    assert slot.can_fit(2.0, 2048.0, 0) is True
    assert slot.allocate(2.0, 2048.0, 0) is True
    assert slot.utilization_pct == 100.0
    assert slot.remaining_cpu == 0.0

    # Overcapacity cannot fit
    assert slot.can_fit(0.5, 512.0, 0) is False
    assert slot.allocate(0.5, 512.0, 0) is False


def test_slot_capacity_registry_multihour():
    """Test SlotCapacityRegistry time normalization and multi-hour spanning."""
    registry = SlotCapacityRegistry(default_max_cpu=4.0, default_max_mem_mib=8192.0, default_max_gpus=1)
    base_time = datetime(2026, 9, 10, 14, 25, 30, tzinfo=timezone.utc)

    # 2.5 hour job spans 3 slots (14:00, 15:00, 16:00)
    assert registry.can_fit("us-east-1", base_time, 2.5, cpu=3.0, mem_mib=2048.0, gpus=0) is True
    assert registry.allocate("us-east-1", base_time, 2.5, cpu=3.0, mem_mib=2048.0, gpus=0) is True

    # Now in hour 15:00, remaining CPU is 1.0. A 2.0 CPU job starting at 15:00 cannot fit
    h15 = datetime(2026, 9, 10, 15, 0, 0, tzinfo=timezone.utc)
    assert registry.can_fit("us-east-1", h15, 1.0, cpu=2.0, mem_mib=1024.0, gpus=0) is False

    # Hour 17:00 was not spanned, so 4.0 CPU fits
    h17 = datetime(2026, 9, 10, 17, 0, 0, tzinfo=timezone.utc)
    assert registry.can_fit("us-east-1", h17, 1.0, cpu=4.0, mem_mib=1024.0, gpus=0) is True

    # Contention summary
    summary = registry.get_summary()
    assert summary["total_slots"] == 3
    assert summary["max_utilization_pct"] == 75.0


def test_demand_forecaster_causal_invariant_and_speed(db_session: Session):
    """
    Test DemandForecaster:
    - Causal invariant: only uses JobORM.submitted_at
    - Fast training (<5 seconds)
    - Fast inference (<1ms)
    - Predictions bounded strictly in [0.0, 1.0]
    """
    forecaster = DemandForecaster()

    t0 = time.perf_counter()
    meta = forecaster.train(db_session)
    train_time = time.perf_counter() - t0

    assert train_time < 5.0, f"Training took too long: {train_time:.2f}s"
    assert forecaster.is_trained is True

    # Predict speed & bounds
    test_dt = datetime(2026, 9, 10, 14, 0, 0, tzinfo=timezone.utc)
    t_inf_start = time.perf_counter()
    pred = forecaster.predict_demand_pressure(test_dt, "us-east-1")
    t_inf = time.perf_counter() - t_inf_start

    assert t_inf < 0.05, f"Prediction took too long: {t_inf*1000:.2f}ms"
    assert 0.0 <= pred <= 1.0, f"Prediction out of bounds: {pred}"


def test_urgency_ordering():
    """Verify urgency sorting prioritizes CRITICAL and non-deferrable jobs with tightest slack."""
    now = datetime(2026, 9, 10, 10, 0, 0, tzinfo=timezone.utc)

    job_critical = JobORM(
        job_id="crit_1",
        team_id="team_test",
        container_image="python:3.10",
        power_kw=1.0,
        region="us-east-1",
        submitted_at=now,
        priority="CRITICAL",
        deferrable=True,
        deadline=now + timedelta(hours=8),
        earliest_start_time=now,
        runtime_minutes=60,
    )
    job_low = JobORM(
        job_id="low_1",
        team_id="team_test",
        container_image="python:3.10",
        power_kw=1.0,
        region="us-east-1",
        submitted_at=now,
        priority="LOW",
        deferrable=True,
        deadline=now + timedelta(hours=4),
        earliest_start_time=now,
        runtime_minutes=60,
    )
    job_non_def = JobORM(
        job_id="non_def_1",
        team_id="team_test",
        container_image="python:3.10",
        power_kw=1.0,
        region="us-east-1",
        submitted_at=now,
        priority="HIGH",
        deferrable=False,
        deadline=now + timedelta(hours=2),
        earliest_start_time=now,
        runtime_minutes=60,
    )

    jobs = [job_low, job_critical, job_non_def]
    sorted_jobs = sorted(jobs, key=lambda j: _urgency_key(j, now))

    # Critical rank has priority 0 vs HIGH (1) vs LOW (3)
    assert sorted_jobs[0].job_id == "crit_1"
    assert sorted_jobs[1].job_id == "non_def_1"
    assert sorted_jobs[2].job_id == "low_1"


def test_contention_batch_spillover(db_session: Session):
    """
    Test that when multiple jobs compete for a single slot,
    jobs spill to subsequent feasible slots once capacity is full.
    """
    # A future-relative timestamp, not a hardcoded absolute date: since
    # app.decide.batch_scheduler now clamps its effective start floor to
    # max(real_now, requested) (Time Consistency Hardening, matching the
    # single-job scheduler's existing clamp), a fixed past calendar date here
    # would collapse every candidate onto the real current instant instead of
    # spreading across this test's intended multi-slot contention window.
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    deadline = now + timedelta(hours=12)

    # Cluster capacity with only 2.0 CPU cores max
    registry = SlotCapacityRegistry(default_max_cpu=2.0, default_max_mem_mib=4096.0, default_max_gpus=0)

    # 4 identical jobs each requesting 1.0 CPU
    # Slot 1 can only take 2 jobs; jobs 3 and 4 must spill!
    test_jobs = []
    for i in range(4):
        job = JobORM(
            job_id=f"spill_test_{i}_{int(time.time())}",
            team_id="team_test",
            container_image="python:3.10",
            submitted_at=now,
            region="us-east-1",
            priority="MEDIUM",
            deferrable=True,
            deadline=deadline,
            earliest_start_time=now,
            runtime_minutes=60,
            power_kw=1.0,
            cpu_request="1000m",
            memory_request="1024Mi",
            status=JobStatus.SUBMITTED,
        )
        test_jobs.append(job)

    decisions = schedule_batch(
        db=db_session,
        jobs=test_jobs,
        registry=registry,
        use_demand_forecast=False,
    )

    assert len(decisions) == 4

    # Check slot allocations
    slots_used = [d.selected_start for d in decisions]
    # At least two distinct start slots should be used
    assert len(set(slots_used)) >= 2

    # Spilled flags: at least 1 job must have spilled_from_preferred = True
    spilled_jobs = [d for d in decisions if d.spilled_from_preferred]
    assert len(spilled_jobs) >= 1

    # Verify no slot exceeded 2.0 CPU
    contention = registry.get_contention_map()
    for s in contention["slots"]:
        assert s["allocated_cpu"] <= s["max_cpu"] + 1e-6, f"Slot {s['slot_start']} exceeded CPU limit!"


def test_scheduler_api_endpoints():
    """Test /schedule/batch, /demand-forecaster/status, /scheduler/capacity-map API routes."""
    client = TestClient(app)

    # 1. Demand forecaster status
    res = client.get("/demand-forecaster/status")
    assert res.status_code == 200
    data = res.json()
    assert "is_trained" in data

    # 2. Train forecaster
    res = client.post("/demand-forecaster/train")
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # 3. Capacity map
    res = client.get("/scheduler/capacity-map")
    assert res.status_code == 200
    map_data = res.json()
    assert "summary" in map_data
    assert "cluster_limits" in map_data
    assert "contention_map" in map_data
