"""
Tests for GreenShift Operational Metrics & Monitoring Abstraction.

Verifies:
1. Primitives: Counter, Gauge, Histogram (thread safety, calculations, Prometheus text output).
2. Operational Metrics Collection:
   - Scheduler: requests, success, infeasible, average scheduling time.
   - Carbon API: cache hits, cache misses, Redis unavailable, fallback usage.
   - Approvals: pending gauge, approvals granted, declines.
   - Dispatch: attempts, success, blocked, failure.
3. Security: No secrets, credentials, or tokens in metrics output.
4. FastAPI Endpoints:
   - GET /metrics (Prometheus text format)
   - GET /api/v1/metrics (Prometheus / JSON)
   - GET /api/v1/metrics/summary (Structured JSON snapshot)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.decide.scheduler import schedule_job
from app.approval.service import approve_schedule, decline_schedule, get_pending_approvals
from app.dispatch.dispatcher import dispatch_job, DispatchBlockedError
from app.shared.auth import create_access_token
from app.shared.database import get_db
from app.shared.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    metrics,
    record_scheduler_request,
    record_scheduler_success,
    record_scheduler_infeasible,
    record_carbon_cache_hit,
    record_carbon_cache_miss,
    record_carbon_redis_unavailable,
    record_carbon_api_fallback,
    record_approval_pending,
    record_approval_granted,
    record_approval_declined,
    record_dispatch_attempt,
    record_dispatch_success,
    record_dispatch_blocked,
    record_dispatch_failure,
)
from app.shared.models import (
    CarbonDataPoint,
    JobORM,
    JobStatus,
    ScheduleDecisionORM,
    TariffDataPoint,
    UserORM,
    UserRole,
)
from app.shared.utils import utcnow


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset global metrics before and after each test."""
    metrics.reset()
    yield
    metrics.reset()


class TestMetricsPrimitives:

    def test_counter_increment_and_reset(self):
        c = Counter("test_counter", "Test counter metric")
        assert c.get_total() == 0.0
        c.inc()
        c.inc(5.0)
        assert c.get_total() == 6.0

        c.inc(2.0, labels={"region": "IN-TG"})
        assert c.get_value({"region": "IN-TG"}) == 2.0
        assert c.get_total() == 8.0

        lines = c.to_prometheus_lines()
        assert any("test_counter" in l for l in lines)
        assert any('region="IN-TG"' in l for l in lines)

        c.reset()
        assert c.get_total() == 0.0

    def test_counter_rejects_negative_increments(self):
        c = Counter("test_neg", "Test negative check")
        with pytest.raises(ValueError):
            c.inc(-1.0)

    def test_gauge_set_inc_dec(self):
        g = Gauge("test_gauge", "Test gauge metric")
        assert g.get_total() == 0.0

        g.set(10.0)
        assert g.get_total() == 10.0

        g.inc(5.0)
        assert g.get_total() == 15.0

        g.dec(3.0)
        assert g.get_total() == 12.0

        g.set(20.0, labels={"queue": "priority"})
        assert g.get_value({"queue": "priority"}) == 20.0

        lines = g.to_prometheus_lines()
        assert any("# TYPE test_gauge gauge" in l for l in lines)

    def test_histogram_observations_and_averages(self):
        h = Histogram("test_latency", "Test latency histogram")
        assert h.count == 0
        assert h.avg == 0.0

        h.observe(0.10)
        h.observe(0.20)
        h.observe(0.30)

        assert h.count == 3
        assert pytest.approx(h.sum) == 0.60
        assert pytest.approx(h.avg) == 0.20
        assert pytest.approx(h.min) == 0.10
        assert pytest.approx(h.max) == 0.30

        lines = h.to_prometheus_lines()
        assert any("test_latency_seconds_count 3" in l for l in lines)
        assert any("test_latency_seconds_sum 0.60" in l for l in lines)


class TestOperationalMetricsTracking:

    def test_scheduler_metrics_tracking(self):
        now = utcnow()
        carbon_curve = [
            CarbonDataPoint(timestamp=now, region="IN-TG", carbon_gco2_kwh=100.0),
        ]
        tariff_curve = [
            TariffDataPoint(timestamp=now, region="IN-TG", price_per_kwh=0.08),
        ]

        # 1. Successful schedule
        decision = schedule_job(
            job_id="JOB-METRICS-01",
            team_id="team_alpha",
            deadline=now + timedelta(hours=4),
            runtime_minutes=30,
            power_kw=2.0,
            region="IN-TG",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            earliest_start_time=now,
        )
        assert decision is not None

        # 2. Infeasible schedule (impossible budget)
        with pytest.raises(ValueError):
            schedule_job(
                job_id="JOB-METRICS-02",
                team_id="team_alpha",
                deadline=now + timedelta(hours=4),
                runtime_minutes=30,
                power_kw=2.0,
                region="IN-TG",
                carbon_curve=carbon_curve,
                tariff_curve=tariff_curve,
                carbon_budget_kg=0.0000001,
                earliest_start_time=now,
            )

        summary = metrics.get_summary()
        assert summary["scheduler"]["scheduling_requests"] == 2
        assert summary["scheduler"]["successful_schedules"] == 1
        assert summary["scheduler"]["infeasible_schedules"] == 1
        assert summary["scheduler"]["average_scheduling_time_ms"] > 0.0

    def test_carbon_api_and_cache_metrics_tracking(self):
        record_carbon_cache_hit("IN-TG")
        record_carbon_cache_hit("IN-TG")
        record_carbon_cache_miss("IN-GJ")
        record_carbon_redis_unavailable()
        record_carbon_api_fallback("csv")
        record_carbon_api_fallback("stale_cache")

        summary = metrics.get_summary()
        assert summary["carbon_api"]["cache_hits"] == 2
        assert summary["carbon_api"]["cache_misses"] == 1
        assert summary["carbon_api"]["redis_unavailable_events"] == 1
        assert summary["carbon_api"]["api_fallback_usage"] == 2
        assert summary["carbon_api"]["cache_hit_ratio_pct"] == pytest.approx(66.7, 0.1)

    def test_approval_metrics_tracking(self, db):
        user_admin = UserORM(
            id=1,
            username="admin",
            email="admin@test.com",
            hashed_password="hash",
            role=UserRole.ADMIN,
        )
        now = utcnow()
        job1 = JobORM(
            job_id="JOB-APPR-M1",
            team_id="team_alpha",
            region="IN-TG",
            status=JobStatus.PENDING_APPROVAL,
            submitted_at=now,
            deadline=now + timedelta(hours=4),
            runtime_minutes=60,
            power_kw=5.0,
            container_image="sim:v1",
        )
        sd1 = ScheduleDecisionORM(
            job_id="JOB-APPR-M1",
            selected_start=now,
            selected_end=now + timedelta(hours=1),
            carbon_intensity=200.0,
            electricity_cost=0.10,
            carbon_emission=1.0,
            reason="Lowest carbon",
        )
        job1.schedule_decision = sd1
        db.add_all([user_admin, job1, sd1])
        db.commit()

        # Check pending gauge
        pending_items = get_pending_approvals(db)
        assert len(pending_items) == 1

        # Approve
        approve_schedule(db, "JOB-APPR-M1", sd1.id, approved_by="admin", user=user_admin)

        # Create second job to decline
        job2 = JobORM(
            job_id="JOB-APPR-M2",
            team_id="team_alpha",
            region="IN-TG",
            status=JobStatus.PENDING_APPROVAL,
            submitted_at=now,
            deadline=now + timedelta(hours=4),
            runtime_minutes=60,
            power_kw=5.0,
            container_image="sim:v1",
        )
        sd2 = ScheduleDecisionORM(
            job_id="JOB-APPR-M2",
            selected_start=now,
            selected_end=now + timedelta(hours=1),
            carbon_intensity=200.0,
            electricity_cost=0.10,
            carbon_emission=1.0,
            reason="Lowest carbon",
        )
        job2.schedule_decision = sd2
        db.add_all([job2, sd2])
        db.commit()

        decline_schedule(db, "JOB-APPR-M2", sd2.id, reason="No longer needed", approved_by="admin", user=user_admin)

        summary = metrics.get_summary()
        assert summary["approval"]["approvals"] == 1
        assert summary["approval"]["declines"] == 1

    def test_dispatch_metrics_tracking(self, db):
        now = utcnow()
        job = JobORM(
            job_id="JOB-DISP-M1",
            team_id="team_alpha",
            region="IN-TG",
            status=JobStatus.DECLINED,  # Blocked status
            submitted_at=now,
            deadline=now + timedelta(hours=4),
            runtime_minutes=60,
            power_kw=5.0,
            container_image="sim:v1",
        )
        db.add(job)
        db.commit()

        with pytest.raises(DispatchBlockedError):
            dispatch_job(db, job)

        summary = metrics.get_summary()
        assert summary["dispatch"]["dispatch_attempts"] == 1
        assert summary["dispatch"]["blocked_dispatches"] == 1
        assert summary["dispatch"]["successful_dispatches"] == 0

    def test_metrics_do_not_leak_secrets_or_tokens(self):
        secret_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sensitive_payload.signature"
        secret_api_key = "EM_API_SECRET_987654321"

        record_scheduler_request()
        record_carbon_cache_hit("IN-TG")
        record_carbon_api_fallback("csv")
        record_approval_granted()
        record_dispatch_success()

        prom_text = metrics.to_prometheus_format()
        summary_dict = metrics.get_summary()

        assert secret_token not in prom_text
        assert secret_api_key not in prom_text
        assert "password" not in prom_text.lower()
        assert "secret" not in prom_text.lower()


class TestMetricsEndpointsIntegration:

    @pytest.fixture(autouse=True)
    def setup_api_db(self, db):
        def _get_test_db():
            try:
                yield db
            finally:
                pass
        app.dependency_overrides[get_db] = _get_test_db
        yield
        app.dependency_overrides.pop(get_db, None)

    def test_get_metrics_prometheus_format(self):
        record_scheduler_request()
        record_scheduler_success(0.012)
        record_carbon_cache_hit("IN-TG")

        client = TestClient(app)
        res = client.get("/metrics")
        assert res.status_code == 200
        assert "text/plain" in res.headers["content-type"]
        assert "greenshift_scheduler_requests_total" in res.text
        assert "greenshift_carbon_cache_hits_total" in res.text

    def test_get_api_v1_metrics_prometheus_and_json(self):
        record_dispatch_success()
        record_approval_granted()

        client = TestClient(app)

        # 1. Prometheus format
        res_prom = client.get("/api/v1/metrics?format=prometheus")
        assert res_prom.status_code == 200
        assert "greenshift_dispatch_success_total" in res_prom.text

        # 2. JSON format
        res_json = client.get("/api/v1/metrics?format=json")
        assert res_json.status_code == 200
        data = res_json.json()
        assert "scheduler" in data
        assert "carbon_api" in data
        assert "approval" in data
        assert "dispatch" in data
        assert data["dispatch"]["successful_dispatches"] == 1
        assert data["approval"]["approvals"] == 1

    def test_get_api_v1_metrics_summary(self):
        record_scheduler_request()
        record_scheduler_success(0.005)
        record_carbon_redis_unavailable()

        client = TestClient(app)
        res = client.get("/api/v1/metrics/summary")
        assert res.status_code == 200
        data = res.json()
        assert data["scheduler"]["scheduling_requests"] == 1
        assert data["carbon_api"]["redis_unavailable_events"] == 1
