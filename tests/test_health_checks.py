"""
Tests for Phase 10: Health Checks, Readiness, and Production Reliability.

Validates:
  1. Liveness endpoint (/live and /api/v1/live) operates with zero dependency calls
  2. Overall health summary (/health and /api/v1/health) reports structured component statuses
  3. Readiness gate (/ready and /api/v1/ready) fails (HTTP 503) when database is unavailable
  4. Degraded operation (HTTP 200) when Redis or Kubernetes is degraded
  5. Carbon resilience hierarchy reporting (live, cached, stale, CSV, controlled fallback)
  6. All carbon sources unavailable handling
  7. Safe failure handling without leaking stack traces or sensitive credentials
  8. Metrics recording (greenshift_health_checks_total, greenshift_dependency_health_status)
  9. Prometheus text exposition format validation
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.health import (
    check_carbon_data_health,
    check_database_health,
    check_kubernetes_health,
    check_redis_health,
    get_system_health,
    get_system_readiness,
)
from app.shared.metrics import metrics

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_metrics():
    metrics.reset()
    yield
    metrics.reset()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Liveness Check Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_liveness_endpoint_healthy():
    """Liveness probe should return HTTP 200 and alive status."""
    for path in ("/live", "/api/v1/live"):
        response = client.get(path)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
        assert data["service"] == "greenshift"


def test_liveness_endpoint_does_not_fail_when_dependencies_down():
    """Liveness probe must succeed even when database, Redis, and K8s are down."""
    with patch("app.shared.health.check_database_health", side_effect=RuntimeError("DB exploded")), \
         patch("app.shared.health.check_redis_health", side_effect=RuntimeError("Redis exploded")), \
         patch("app.shared.health.check_kubernetes_health", side_effect=RuntimeError("K8s exploded")):
        response = client.get("/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
        assert data["service"] == "greenshift"


# ─────────────────────────────────────────────────────────────────────────────
# 2. General Health Summary Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_health_summary_all_healthy():
    """GET /health returns 200 with structured component breakdown."""
    with patch("app.shared.health.check_database_health", return_value={"status": "healthy"}), \
         patch("app.shared.health.check_redis_health", return_value={"status": "healthy"}), \
         patch("app.shared.health.check_kubernetes_health", return_value={"status": "healthy"}), \
         patch("app.shared.health.check_carbon_data_health", return_value={"status": "healthy", "mode": "healthy"}):
        for path in ("/health", "/api/v1/health"):
            response = client.get(path)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["service"] == "greenshift"
            assert "timestamp" in data
            components = data["components"]
            assert components["application"]["status"] == "healthy"
            assert components["database"]["status"] == "healthy"
            assert components["redis"]["status"] == "healthy"
            assert components["kubernetes"]["status"] == "healthy"
            assert components["carbon_data"]["status"] == "healthy"


def test_health_summary_no_secrets_exposed():
    """Health check responses must never contain secrets, passwords, or connection strings."""
    response = client.get("/health")
    assert response.status_code == 200
    text = response.text.lower()
    for sensitive_keyword in ("password", "secret", "token", "postgres://", "redis://"):
        assert sensitive_keyword not in text


# ─────────────────────────────────────────────────────────────────────────────
# 3. Readiness Gate Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_readiness_all_healthy():
    """GET /ready returns HTTP 200 ready when all dependencies healthy."""
    with patch("app.shared.health.check_database_health", return_value={"status": "healthy"}), \
         patch("app.shared.health.check_redis_health", return_value={"status": "healthy"}), \
         patch("app.shared.health.check_kubernetes_health", return_value={"status": "healthy"}), \
         patch("app.shared.health.check_carbon_data_health", return_value={"status": "healthy", "mode": "healthy"}):
        for path in ("/ready", "/api/v1/ready"):
            response = client.get(path)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["database"] == "healthy"
            assert data["redis"] == "healthy"
            assert data["kubernetes"] == "healthy"
            assert data["carbon_data"] == "healthy"


def test_readiness_database_failure_returns_503():
    """GET /ready returns HTTP 503 not_ready when database is down."""
    with patch("app.shared.health.check_database_health", return_value={"status": "unhealthy", "reason": "database_unreachable"}):
        for path in ("/ready", "/api/v1/ready"):
            response = client.get(path)
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not_ready"
            assert data["database"] == "unhealthy"
            assert data["reason"] == "database_unreachable"


def test_readiness_redis_degraded_returns_200():
    """GET /ready returns HTTP 200 ready (degraded) when Redis is down."""
    with patch("app.shared.health.check_database_health", return_value={"status": "healthy"}), \
         patch("app.shared.health.check_redis_health", return_value={"status": "degraded", "reason": "redis_unavailable"}), \
         patch("app.shared.health.check_kubernetes_health", return_value={"status": "healthy"}), \
         patch("app.shared.health.check_carbon_data_health", return_value={"status": "healthy", "mode": "healthy"}):
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["overall_state"] == "degraded"
        assert data["database"] == "healthy"
        assert data["redis"] == "degraded"
        assert data["kubernetes"] == "healthy"


def test_readiness_kubernetes_degraded_returns_200():
    """GET /ready returns HTTP 200 ready (degraded) when Kubernetes is unreachable."""
    with patch("app.shared.health.check_database_health", return_value={"status": "healthy"}), \
         patch("app.shared.health.check_redis_health", return_value={"status": "healthy"}), \
         patch("app.shared.health.check_kubernetes_health", return_value={"status": "degraded", "reason": "kubernetes_api_unreachable"}), \
         patch("app.shared.health.check_carbon_data_health", return_value={"status": "healthy", "mode": "healthy"}):
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["overall_state"] == "degraded"
        assert data["database"] == "healthy"
        assert data["kubernetes"] == "degraded"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Carbon Data Resilience Hierarchy Health Checks
# ─────────────────────────────────────────────────────────────────────────────

def test_carbon_health_live_api():
    """Carbon health returns healthy when live API is configured and available."""
    with patch("app.shared.config.settings.electricity_maps_api_key", "valid-key"), \
         patch("app.ingest.carbon_api.is_carbon_api_down_simulated", return_value=False):
        result = check_carbon_data_health()
        assert result["status"] == "healthy"
        assert result["mode"] == "healthy"


def test_carbon_health_csv_fallback():
    """Carbon health returns degraded mode csv_fallback when live API down but CSV exists."""
    with patch("app.shared.config.settings.electricity_maps_api_key", ""), \
         patch("os.environ.get", return_value=""), \
         patch("app.shared.carbon_cache.get_redis_client", return_value=None), \
         patch("app.ingest.csv_carbon_loader.csv_carbon_available", return_value=True):
        result = check_carbon_data_health()
        assert result["status"] == "degraded"
        assert result["mode"] == "csv_fallback"


def test_carbon_health_controlled_fallback():
    """Carbon health returns degraded mode controlled_fallback when only deterministic baseline exists."""
    with patch("app.shared.config.settings.electricity_maps_api_key", ""), \
         patch("os.environ.get", side_effect=lambda k, d=None: "400.0" if k == "CARBON_FALLBACK_GCO2_PER_KWH" else (d or "")), \
         patch("app.shared.carbon_cache.get_redis_client", return_value=None), \
         patch("app.ingest.csv_carbon_loader.csv_carbon_available", return_value=False):
        result = check_carbon_data_health()
        assert result["status"] == "degraded"
        assert result["mode"] == "controlled_fallback"


def test_carbon_health_all_sources_unavailable():
    """Carbon health returns unhealthy when no carbon data sources are available."""
    with patch("app.shared.config.settings.electricity_maps_api_key", ""), \
         patch("os.environ.get", side_effect=lambda k, d=None: "true" if k == "DISABLE_CONTROLLED_FALLBACK" else "0.0" if k == "CARBON_FALLBACK_GCO2_PER_KWH" else (d or "")), \
         patch("app.shared.config.settings.carbon_fallback_gco2_per_kwh", 0.0), \
         patch("app.shared.carbon_cache.get_redis_client", return_value=None), \
         patch("app.ingest.csv_carbon_loader.csv_carbon_available", return_value=False):
        result = check_carbon_data_health()
        assert result["status"] == "unhealthy"
        assert result["mode"] == "unavailable"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Dependency Safety & Failure Protection
# ─────────────────────────────────────────────────────────────────────────────

def test_database_health_handles_exception_safely():
    """Database probe returns structured failure without crashing on exception."""
    with patch("app.shared.database.engine.connect", side_effect=Exception("Connection refused")):
        res = check_database_health()
        assert res["status"] == "unhealthy"
        assert res["reason"] == "database_unreachable"


def test_redis_health_handles_exception_safely():
    """Redis probe returns degraded without crashing on exception."""
    with patch("app.shared.carbon_cache.is_redis_available", side_effect=Exception("Redis timeout")):
        res = check_redis_health()
        assert res["status"] == "degraded"
        assert res["reason"] == "redis_unavailable"


def test_kubernetes_health_handles_exception_safely():
    """Kubernetes probe returns degraded without crashing on exception."""
    with patch("app.dispatch.kubernetes_client.check_kubernetes_available", side_effect=Exception("K8s unreachable")):
        res = check_kubernetes_health()
        assert res["status"] == "degraded"
        assert res["reason"] == "kubernetes_api_unreachable"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Metrics Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_health_checks_metrics_recorded():
    """Calling health endpoints updates Prometheus metrics."""
    client.get("/live")
    client.get("/health")
    client.get("/ready")

    # Verify counters
    assert metrics.health_checks_total.get_value(labels={"endpoint": "live"}) >= 1
    assert metrics.health_checks_total.get_value(labels={"endpoint": "health"}) >= 1
    assert metrics.health_checks_total.get_value(labels={"endpoint": "ready"}) >= 1

    # Verify gauge values
    prom_text = metrics.to_prometheus_format()
    assert "greenshift_health_checks_total" in prom_text
    assert "greenshift_dependency_health_status" in prom_text
    assert 'endpoint="live"' in prom_text
    assert 'dependency="database"' in prom_text


def test_metrics_endpoint_exports_health_metrics():
    """GET /metrics includes health check metrics."""
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "greenshift_health_checks_total" in response.text
    assert "greenshift_dependency_health_status" in response.text


# ─────────────────────────────────────────────────────────────────────────────
# 10. Email Delivery Configuration Status (never exposes SMTP credentials)
# ─────────────────────────────────────────────────────────────────────────────

def test_email_health_disabled_when_smtp_disabled():
    from app.shared.config import settings
    from app.shared.health import check_email_health
    original = settings.smtp_enabled
    settings.smtp_enabled = False
    try:
        result = check_email_health()
    finally:
        settings.smtp_enabled = original
    assert result["status"] == "disabled"


def test_email_health_unconfigured_when_enabled_but_no_host():
    from app.shared.config import settings
    from app.shared.health import check_email_health
    original_enabled, original_host = settings.smtp_enabled, settings.smtp_host
    settings.smtp_enabled = True
    settings.smtp_host = ""
    try:
        result = check_email_health()
    finally:
        settings.smtp_enabled, settings.smtp_host = original_enabled, original_host
    assert result["status"] == "unconfigured"


def test_email_health_configured_when_enabled_with_host():
    from app.shared.config import settings
    from app.shared.health import check_email_health
    original_enabled, original_host = settings.smtp_enabled, settings.smtp_host
    settings.smtp_enabled = True
    settings.smtp_host = "smtp.example.com"
    try:
        result = check_email_health()
    finally:
        settings.smtp_enabled, settings.smtp_host = original_enabled, original_host
    assert result == {"status": "configured"}


def test_health_endpoint_includes_email_delivery_component_without_credentials():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "email_delivery" in data["components"]
    assert data["components"]["email_delivery"]["status"] in ("disabled", "unconfigured", "configured")
    text = response.text.lower()
    assert "smtp_password" not in text
    assert "smtp_username" not in text
