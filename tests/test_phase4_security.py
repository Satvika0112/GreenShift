"""
Tests for Phase 4 Security Hardening:
- Security Headers Middleware (X-Content-Type-Options, X-Frame-Options, CSP, HSTS, Cache-Control, No X-XSS-Protection)
- Request ID Tracing Middleware (UUID generation, Propagation, Validation)
- Internal Service Authentication (Constant-time token validation, FastAPI dependency)
- Kubernetes Network Policies (YAML validity, Selector match against actual deployment manifests)
"""

import uuid
import yaml
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.config import settings
from app.shared.auth import verify_internal_service_token, require_internal_service_token, create_access_token


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_token():
    return create_access_token(
        user_id=1,
        username="admin",
        role="PLATFORM_ADMIN",
        team_id="engineering",
    )


# ─────────────────────────────────────────────────────────────
# 1. SECURITY HEADERS TESTS
# ─────────────────────────────────────────────────────────────

def test_security_headers_present_on_api_responses(client):
    """Verify essential security headers are injected into API responses."""
    resp = client.get("/live")
    assert resp.status_code == 200

    # 1. X-Content-Type-Options: nosniff
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    # 2. X-Frame-Options: DENY
    assert resp.headers.get("X-Frame-Options") == "DENY"

    # 3. Content-Security-Policy
    csp = resp.headers.get("Content-Security-Policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp

    # 4. Obsolete X-XSS-Protection MUST NOT be present
    assert "X-XSS-Protection" not in resp.headers


def test_cache_control_on_api_endpoints(client, admin_token):
    """Verify Cache-Control: no-store is applied to dynamic/sensitive API endpoints."""
    # Test on API endpoint
    resp = client.get(
        "/api/v1/jobs",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.headers.get("Cache-Control") is not None
    assert "no-store" in resp.headers.get("Cache-Control")

    # Test on Auth endpoint
    auth_resp = client.post("/auth/login", data={"username": "admin", "password": "wrongpassword"})
    assert auth_resp.headers.get("Cache-Control") is not None
    assert "no-store" in auth_resp.headers.get("Cache-Control")


def test_hsts_header_in_production_or_https(client, monkeypatch):
    """Verify Strict-Transport-Security is applied in production or HTTPS contexts."""
    # Default non-HTTPS in dev: no HSTS unless enabled
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "enable_hsts", False)
    resp_dev = client.get("/live")
    assert "Strict-Transport-Security" not in resp_dev.headers

    # When HTTPS forwarded header is present
    resp_https = client.get("/live", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" in resp_https.headers
    assert "max-age=" in resp_https.headers["Strict-Transport-Security"]

    # When environment is production
    monkeypatch.setattr(settings, "environment", "production")
    resp_prod = client.get("/live")
    assert "Strict-Transport-Security" in resp_prod.headers
    assert "includeSubDomains" in resp_prod.headers["Strict-Transport-Security"]


def test_csp_permits_swagger_docs(client):
    """Verify CSP allows CDN assets so /docs and /redoc Swagger UI can render correctly."""
    resp = client.get("/docs")
    assert resp.status_code == 200
    csp = resp.headers.get("Content-Security-Policy")
    assert csp is not None
    assert "cdn.jsdelivr.net" in csp
    assert "fastapi.tiangolo.com" in csp


# ─────────────────────────────────────────────────────────────
# 2. REQUEST ID TRACING TESTS
# ─────────────────────────────────────────────────────────────

def test_request_id_generated_when_missing(client):
    """Verify a UUID4 request ID is automatically generated if missing."""
    resp = client.get("/live")
    assert resp.status_code == 200
    req_id = resp.headers.get("X-Request-ID")
    assert req_id is not None
    # Verify it is a valid UUID
    parsed = uuid.UUID(req_id)
    assert str(parsed) == req_id


def test_request_id_propagated_when_supplied(client):
    """Verify a valid incoming X-Request-ID is safely preserved and echoed."""
    custom_id = "greenshift-trace-abc-123_456"
    resp = client.get("/live", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == custom_id


def test_malformed_request_id_is_sanitized_with_new_uuid(client):
    """Verify invalid / injection characters in X-Request-ID trigger a fresh UUID generation."""
    malicious_id = "bad-id<script>alert(1)</script>; DROP TABLE users;"
    resp = client.get("/live", headers={"X-Request-ID": malicious_id})
    assert resp.status_code == 200
    req_id = resp.headers.get("X-Request-ID")
    assert req_id != malicious_id
    # Should have fallen back to a valid UUID
    parsed = uuid.UUID(req_id)
    assert str(parsed) == req_id


# ─────────────────────────────────────────────────────────────
# 3. INTERNAL SERVICE AUTHENTICATION TESTS
# ─────────────────────────────────────────────────────────────

def test_verify_internal_service_token(monkeypatch):
    """Verify internal service key verification logic."""
    monkeypatch.setattr(settings, "internal_service_key", "super-secret-internal-key-2026")

    assert verify_internal_service_token("super-secret-internal-key-2026") is True
    assert verify_internal_service_token("wrong-key") is False
    assert verify_internal_service_token("") is False
    assert verify_internal_service_token(None) is False


def test_require_internal_service_token_dependency(monkeypatch):
    """Verify FastAPI dependency behavior for internal service auth."""
    from fastapi import HTTPException

    # 1. When not configured, raises 503
    monkeypatch.setattr(settings, "internal_service_key", None)
    with pytest.raises(HTTPException) as exc1:
        require_internal_service_token("some-token")
    assert exc1.value.status_code == 503

    # 2. When configured but wrong token, raises 401
    monkeypatch.setattr(settings, "internal_service_key", "valid-key-999")
    with pytest.raises(HTTPException) as exc2:
        require_internal_service_token("wrong-token")
    assert exc2.value.status_code == 401

    # 3. When valid, returns token successfully
    result = require_internal_service_token("valid-key-999")
    assert result == "valid-key-999"


# ─────────────────────────────────────────────────────────────
# 4. KUBERNETES NETWORK POLICIES TESTS
# ─────────────────────────────────────────────────────────────

def test_kubernetes_network_policy_yaml_validity():
    """Verify k8s/network-policy.yaml is valid YAML and has all required policies."""
    netpol_path = Path("k8s/network-policy.yaml")
    assert netpol_path.exists(), "k8s/network-policy.yaml must exist"

    with open(netpol_path, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))

    assert len(docs) >= 8, f"Expected at least 8 NetworkPolicy documents, got {len(docs)}"

    policy_names = {doc["metadata"]["name"] for doc in docs if doc}
    expected_policies = {
        "default-deny-all",
        "greenshift-api-netpol",
        "greenshift-postgres-netpol",
        "greenshift-ingest-netpol",
        "greenshift-scheduler-netpol",
        "greenshift-dispatcher-netpol",
        "greenshift-trust-netpol",
        "greenshift-dashboard-netpol",
    }
    assert expected_policies.issubset(policy_names)


def test_network_policy_selectors_match_deployment_labels():
    """Verify NetworkPolicy podSelectors match actual labels used in deployments.yaml."""
    deployments_path = Path("k8s/deployments.yaml")
    assert deployments_path.exists(), "k8s/deployments.yaml must exist"

    with open(deployments_path, "r", encoding="utf-8") as f:
        deploy_docs = list(yaml.safe_load_all(f))

    # Collect actual deployment labels
    deployment_components = set()
    for doc in deploy_docs:
        if not doc or doc.get("kind") != "Deployment":
            continue
        labels = doc.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
        assert labels.get("app") == "greenshift"
        deployment_components.add(labels.get("component"))

    assert deployment_components == {"api", "ingest", "scheduler", "dispatcher", "trust", "dashboard", "postgres"}

    # Validate NetworkPolicies match these exact components
    with open("k8s/network-policy.yaml", "r", encoding="utf-8") as f:
        netpol_docs = list(yaml.safe_load_all(f))

    netpol_by_name = {doc["metadata"]["name"]: doc for doc in netpol_docs if doc}

    # 1. Default deny covers all pods (empty podSelector)
    assert netpol_by_name["default-deny-all"]["spec"]["podSelector"] == {}

    # 2. Postgres accepts traffic only from backend components, NOT dashboard
    postgres_ingress = netpol_by_name["greenshift-postgres-netpol"]["spec"]["ingress"]
    allowed_postgres_sources = set()
    for rule in postgres_ingress:
        for from_rule in rule.get("from", []):
            pod_sel = from_rule.get("podSelector", {}).get("matchLabels", {})
            allowed_postgres_sources.add(pod_sel.get("component"))

    assert "api" in allowed_postgres_sources
    assert "ingest" in allowed_postgres_sources
    assert "scheduler" in allowed_postgres_sources
    assert "dispatcher" in allowed_postgres_sources
    assert "trust" in allowed_postgres_sources
    assert "dashboard" not in allowed_postgres_sources, "Postgres must not allow direct access from Dashboard"
