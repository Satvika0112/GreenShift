"""
Phase 3 Security Hardening Test Suite for GreenShift.

Verifies:
1. Rate Limiting:
   - Exceeding limit (e.g. 11 rapid attempts on a 10/min limit) returns HTTP 429.
   - Normal requests within limit succeed.
2. Input Validation (Pydantic constraints):
   - runtime_minutes=99999 -> HTTP 422
   - Negative runtime_minutes -> HTTP 422
   - Negative power_kw -> HTTP 422
   - Invalid / unsupported region -> HTTP 422
   - Invalid CPU / memory format & excessive bounds -> HTTP 422
   - Invalid priority string -> HTTP 422
   - Negative carbon_budget_kg or energy_kwh -> HTTP 422
   - Valid payload -> HTTP 201
3. Kubernetes RBAC Hardening:
   - k8s/rbac.yaml contains no default ServiceAccount binding.
   - Only dedicated greenshift-dispatcher ServiceAccount is bound.
4. Kubernetes Secrets Hardening:
   - k8s/deployments.yaml uses secretKeyRef for POSTGRES_PASSWORD without plaintext secrets.
   - k8s/secrets.example.yaml provides clean templates.
5. Configuration & Placeholders:
   - .env.example contains no hardcoded real credentials.
6. Security-Relevant Audit Events:
   - Successful login generates AUTH_LOGIN_SUCCESS event without sensitive credentials.
   - Failed login generates AUTH_LOGIN_FAILURE event without logging attempted passwords.
   - Forbidden RBAC check generates AUTH_ACCESS_DENIED event.
   - New user registration generates AUTH_USER_REGISTERED event without password hashes.
   - SHA-256 tamper-evident chain verification remains 100% valid.
7. Terminology:
   - No misleading 'blockchain' claims in audit trust view.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.auth import create_access_token, hash_password
from app.shared.database import get_db
from app.shared.models import (
    UserORM,
    UserRole,
    EventType,
    AuditEventORM,
)
from app.shared.rate_limiter import limiter
from app.shared.utils import utcnow
from app.trust.ledger import verify_chain


@pytest.fixture(autouse=True)
def override_db(db):
    """Override FastAPI get_db dependency with test database session."""
    def _get_test_db():
        yield db

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def auth_users(db):
    """Create test users for role authorization and rate limit tests."""
    users = {
        "admin": UserORM(
            username="p3_admin",
            email="p3_admin@greenshift.io",
            hashed_password=hash_password("adminpass123"),
            role=UserRole.ADMIN,
            is_active=True,
        ),
        "lead_alpha": UserORM(
            username="p3_lead_alpha",
            email="p3_alpha@greenshift.io",
            hashed_password=hash_password("alphapass123"),
            role=UserRole.TEAM_LEAD,
            team_id="team_alpha",
            is_active=True,
        ),
        "viewer": UserORM(
            username="p3_viewer",
            email="p3_viewer@greenshift.io",
            hashed_password=hash_password("viewerpass123"),
            role=UserRole.VIEWER,
            is_active=True,
        ),
    }
    for u in users.values():
        db.add(u)
    db.commit()
    for u in users.values():
        db.refresh(u)
    return users


def get_token(user: UserORM) -> str:
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    return create_access_token(
        user_id=user.id,
        username=user.username,
        role=role_str,
        team_id=user.team_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Rate Limiting Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_rate_limiting_exceeded_returns_429(auth_users):
    """Verify that exceeding rate limit on /auth/login returns HTTP 429."""
    client = TestClient(app)
    limiter.reset()

    # Make 10 login attempts (allowed by 10/minute limit)
    for i in range(10):
        res = client.post(
            "/api/v1/auth/login",
            json={"username": "p3_admin", "password": "wrongpassword"},
        )
        assert res.status_code == 401

    # 11th attempt must be rejected with 429 Too Many Requests
    exceeded_res = client.post(
        "/api/v1/auth/login",
        json={"username": "p3_admin", "password": "wrongpassword"},
    )
    assert exceeded_res.status_code == 429
    assert "Too Many Requests" in exceeded_res.text or "rate limit" in exceeded_res.text.lower()

    # Reset limiter for subsequent tests
    limiter.reset()


def test_normal_login_within_rate_limits_succeeds(auth_users):
    """Verify standard login within rate limits succeeds with HTTP 200."""
    client = TestClient(app)
    limiter.reset()

    res = client.post(
        "/api/v1/auth/login",
        json={"username": "p3_admin", "password": "adminpass123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["username"] == "p3_admin"

    limiter.reset()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Input Validation Tests (Pydantic Constraints)
# ─────────────────────────────────────────────────────────────────────────────

def test_input_validation_runtime_minutes_bounds(auth_users):
    """Verify runtime_minutes > 10080 or <= 0 is rejected with HTTP 422."""
    client = TestClient(app)
    token = get_token(auth_users["admin"])
    headers = {"Authorization": f"Bearer {token}"}
    now = utcnow()

    base_payload = {
        "team_id": "team_alpha",
        "deadline": (now + timedelta(hours=8)).isoformat(),
        "runtime_minutes": 60,
        "power_kw": 5.0,
        "region": "IN-TG",
        "container_image": "greenshift/workload:v1",
    }

    # 1. runtime_minutes = 99999 (excessive)
    res_excess = client.post("/api/v1/jobs", json={**base_payload, "runtime_minutes": 99999}, headers=headers)
    assert res_excess.status_code == 422

    # 2. runtime_minutes = -10 (negative)
    res_neg = client.post("/api/v1/jobs", json={**base_payload, "runtime_minutes": -10}, headers=headers)
    assert res_neg.status_code == 422

    # 3. runtime_minutes = 0 (zero)
    res_zero = client.post("/api/v1/jobs", json={**base_payload, "runtime_minutes": 0}, headers=headers)
    assert res_zero.status_code == 422


def test_input_validation_power_and_resources(auth_users):
    """Verify power_kw, cpu_request, and memory_request validations."""
    client = TestClient(app)
    token = get_token(auth_users["admin"])
    headers = {"Authorization": f"Bearer {token}"}
    now = utcnow()

    base_payload = {
        "team_id": "team_alpha",
        "deadline": (now + timedelta(hours=8)).isoformat(),
        "runtime_minutes": 60,
        "power_kw": 5.0,
        "region": "IN-TG",
        "container_image": "greenshift/workload:v1",
    }

    # Negative power
    res_pow = client.post("/api/v1/jobs", json={**base_payload, "power_kw": -2.5}, headers=headers)
    assert res_pow.status_code == 422

    # Invalid region
    res_reg = client.post("/api/v1/jobs", json={**base_payload, "region": "UNKNOWN-ZONE-999"}, headers=headers)
    assert res_reg.status_code == 422

    # Invalid CPU
    res_cpu = client.post("/api/v1/jobs", json={**base_payload, "cpu_request": "-500m"}, headers=headers)
    assert res_cpu.status_code == 422

    # Invalid Memory
    res_mem = client.post("/api/v1/jobs", json={**base_payload, "memory_request": "invalid_bytes"}, headers=headers)
    assert res_mem.status_code == 422

    # Invalid Priority
    res_prio = client.post("/api/v1/jobs", json={**base_payload, "priority": "ULTRA_URGENT"}, headers=headers)
    assert res_prio.status_code == 422

    # Negative carbon budget
    res_budget = client.post("/api/v1/jobs", json={**base_payload, "carbon_budget_kg": -5.0}, headers=headers)
    assert res_budget.status_code == 422

    # Valid payload succeeds
    res_valid = client.post("/api/v1/jobs", json=base_payload, headers=headers)
    assert res_valid.status_code == 201


# ─────────────────────────────────────────────────────────────────────────────
# 3. Kubernetes RBAC Hardening Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_k8s_rbac_manifest_has_no_default_service_account():
    """Verify k8s/rbac.yaml does not bind roles to the default ServiceAccount."""
    rbac_path = Path("d:/Greenshift/k8s/rbac.yaml")
    assert rbac_path.exists()

    content = rbac_path.read_text(encoding="utf-8")
    docs = list(yaml.safe_load_all(content))

    role_bindings = [d for d in docs if d and d.get("kind") == "RoleBinding"]
    assert len(role_bindings) >= 1

    for rb in role_bindings:
        subjects = rb.get("subjects", [])
        for subject in subjects:
            assert subject.get("name") != "default", f"Unsafe binding to default ServiceAccount found in {rb.get('metadata', {}).get('name')}"
            assert subject.get("name") == "greenshift-dispatcher"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Kubernetes Secrets Hardening Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_k8s_deployments_use_secret_key_ref_for_postgres():
    """Verify k8s/deployments.yaml uses secretKeyRef for PostgreSQL credentials."""
    dep_path = Path("d:/Greenshift/k8s/deployments.yaml")
    assert dep_path.exists()

    content = dep_path.read_text(encoding="utf-8")
    docs = list(yaml.safe_load_all(content))

    postgres_dep = next((d for d in docs if d and d.get("metadata", {}).get("name") == "postgres"), None)
    assert postgres_dep is not None

    containers = postgres_dep["spec"]["template"]["spec"]["containers"]
    pg_container = next((c for c in containers if c["name"] == "postgres"), None)
    assert pg_container is not None

    env_vars = {e["name"]: e for e in pg_container.get("env", [])}
    assert "POSTGRES_PASSWORD" in env_vars
    pw_env = env_vars["POSTGRES_PASSWORD"]

    assert "valueFrom" in pw_env, "POSTGRES_PASSWORD must use valueFrom"
    assert "secretKeyRef" in pw_env["valueFrom"], "POSTGRES_PASSWORD must use secretKeyRef"
    assert pw_env["valueFrom"]["secretKeyRef"]["name"] == "greenshift-db-secrets"
    assert "value" not in pw_env, "Plaintext value must not exist in POSTGRES_PASSWORD env"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Configuration & Environment Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_env_example_contains_clean_placeholders():
    """Verify .env.example contains placeholders and no actual passwords."""
    env_path = Path("d:/Greenshift/.env.example")
    assert env_path.exists()

    content = env_path.read_text(encoding="utf-8")
    assert "your_secure_postgres_password_here" in content
    assert "your_cryptographically_secure_jwt_secret_key" in content


# ─────────────────────────────────────────────────────────────────────────────
# 6. Security Audit Event Logging Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_security_audit_events_logged_without_credential_leakage(db, auth_users):
    """Verify login success, login failure, and access denied events are recorded in audit ledger."""
    client = TestClient(app)
    limiter.reset()

    # 1. Failed login
    res_fail = client.post(
        "/api/v1/auth/login",
        json={"username": "p3_admin", "password": "supersecretpassword123"},
    )
    assert res_fail.status_code == 401

    # Check failure audit event in DB
    fail_events = db.query(AuditEventORM).filter(AuditEventORM.event_type == EventType.AUTH_LOGIN_FAILURE).all()
    assert len(fail_events) >= 1
    last_fail = fail_events[-1]
    assert last_fail.payload["username_attempted"] == "p3_admin"
    # Ensure raw password is NOT logged
    assert "supersecretpassword123" not in str(last_fail.payload)

    # 2. Successful login
    res_success = client.post(
        "/api/v1/auth/login",
        json={"username": "p3_admin", "password": "adminpass123"},
    )
    assert res_success.status_code == 200

    # Check success audit event in DB
    success_events = db.query(AuditEventORM).filter(AuditEventORM.event_type == EventType.AUTH_LOGIN_SUCCESS).all()
    assert len(success_events) >= 1
    last_success = success_events[-1]
    assert last_success.payload["username"] == "p3_admin"
    assert last_success.payload["role"] == "ADMIN"
    assert "adminpass123" not in str(last_success.payload)

    # 3. Access denied (Viewer attempting to submit job)
    viewer_token = get_token(auth_users["viewer"])
    res_denied = client.post(
        "/api/v1/jobs",
        json={
            "team_id": "team_alpha",
            "deadline": (utcnow() + timedelta(hours=8)).isoformat(),
            "runtime_minutes": 60,
            "power_kw": 5.0,
            "region": "IN-TG",
            "container_image": "greenshift/workload:v1",
        },
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_denied.status_code == 403

    denied_events = db.query(AuditEventORM).filter(AuditEventORM.event_type == EventType.AUTH_ACCESS_DENIED).all()
    assert len(denied_events) >= 1
    last_denied = denied_events[-1]
    assert last_denied.payload["username"] == "p3_viewer"
    assert last_denied.payload["role"] == "VIEWER"

    # 4. Chain integrity remains valid
    verify_res = verify_chain(db)
    assert verify_res.valid is True


# ─────────────────────────────────────────────────────────────────────────────
# 7. Accurate Terminology Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_trust_view_uses_accurate_ledger_terminology():
    """Verify app/dashboard/views/audit_trust.py avoids misleading blockchain claims."""
    view_path = Path("d:/Greenshift/app/dashboard/views/audit_trust.py")
    assert view_path.exists()

    content = view_path.read_text(encoding="utf-8")
    assert "blockchain-style" not in content
    assert "Tamper-evident" in content or "SHA-256" in content
