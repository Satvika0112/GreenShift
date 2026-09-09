"""
Tests for Observability (Prometheus Metrics, Health Probes, and Structured Logging).
"""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.decide.service import schedule_and_store
from app.ingest.service import submit_job
from app.observability.metrics import scheduler_jobs_total
from app.shared.config import settings
from app.shared.models import JobSubmitRequest
from app.shared.utils import JSONFormatter, get_logger


@pytest.fixture
def client():
    return TestClient(app)


def test_metrics_endpoint_returns_prometheus_format(client):
    """GET /metrics returns text with greenshift_ prefixed metrics."""
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    assert "greenshift_" in res.text


def test_health_returns_checks(client):
    """GET /health returns api, database, kubernetes checks."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert "checks" in data
    assert data["checks"]["api"] == "ok"
    assert "database" in data["checks"]
    assert "kubernetes" in data["checks"]


def test_health_degraded_on_db_failure(client):
    """Mock DB failure → status=degraded."""
    with patch("app.shared.health.check_database_health", return_value={"status": "unhealthy", "reason": "connection_refused"}):
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"] == "degraded"


def test_scheduler_counter_increments(db, client):
    """After scheduling a job, greenshift_scheduler_jobs_total increases."""
    req = JobSubmitRequest(
        team_id="OBS-TEAM",
        deadline=datetime.now(timezone.utc) + timedelta(hours=24),
        runtime_minutes=30,
        power_kw=0.5,
        region="IN-WE",
        container_image="greenshift/sample-workload:latest",
        cpu_request="100m",
        memory_request="64Mi",
    )
    job = submit_job(db, req)
    region = job.region

    before = scheduler_jobs_total.labels(region=region, status="success")._value.get()
    schedule_and_store(db, job)
    after = scheduler_jobs_total.labels(region=region, status="success")._value.get()

    assert after == before + 1

    res = client.get("/metrics")
    assert "greenshift_scheduler_jobs_total" in res.text


def test_production_json_logger():
    """Production logs emit valid JSON with timestamp, level, logger, message."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="greenshift.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Operational metric check %s",
        args=("ok",),
        exc_info=None,
    )
    formatted = formatter.format(record)
    import json
    parsed = json.loads(formatted)
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "greenshift.test"
    assert parsed["message"] == "Operational metric check ok"
    assert "timestamp" in parsed
