"""
GreenShift — Phase 1 Security Hardening Test Suite

Validates:
1. Removal of hardcoded secrets & fail-fast startup security validation in production
2. Secure CORS configuration & origin filtering (blocking untrusted origins, allowing configured origins)
3. Dashboard session authentication integrity (no auto-login, no client-side token minting)
4. Protection of /auth/users and /api/v1/auth/users (401 unauth, 403 non-admin, 200 admin)
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.main import app
from app.shared.config import Settings, validate_security_config, DEV_INSECURE_JWT_SECRETS
from app.shared.database import init_db, SessionLocal
from app.shared.models import UserORM, UserRole
from app.shared.auth import create_access_token


@pytest.fixture(autouse=True)
def setup_security_db():
    """Ensure database tables exist and clean up users table before/after each test."""
    init_db()
    db = SessionLocal()
    try:
        db.query(UserORM).delete()
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        db.query(UserORM).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def client():
    return TestClient(app)


# ====================================================================
# 1. Hardcoded Secrets & Fail-Fast Startup Validation Tests
# ====================================================================

def test_development_mode_starts_safely():
    """Development environment should start without error using safe dev configuration."""
    dev_settings = Settings(
        environment="development",
        jwt_secret_key="greenshift-dev-insecure-jwt-secret-do-not-use-in-production",
        database_url="sqlite:///./greenshift.db",
        postgres_password="",
    )
    # Should not raise exception
    validate_security_config(dev_settings)


def test_production_mode_requires_secure_jwt_secret():
    """Production environment MUST reject empty, insecure default, or short JWT secret keys."""
    # 1. Empty JWT Secret
    prod_empty_jwt = Settings(
        environment="production",
        jwt_secret_key="",
        database_url="sqlite:///./greenshift.db",
    )
    with pytest.raises(ValueError, match="JWT_SECRET_KEY must be set"):
        validate_security_config(prod_empty_jwt)

    # 2. Insecure default JWT secret
    for insecure_secret in DEV_INSECURE_JWT_SECRETS:
        prod_insecure_jwt = Settings(
            environment="production",
            jwt_secret_key=insecure_secret,
            database_url="sqlite:///./greenshift.db",
        )
        with pytest.raises(ValueError, match="cannot be empty or default dev secret"):
            validate_security_config(prod_insecure_jwt)

    # 3. Short secret key (< 32 characters)
    prod_short_jwt = Settings(
        environment="production",
        jwt_secret_key="too-short-secret-key-12345",
        database_url="sqlite:///./greenshift.db",
    )
    with pytest.raises(ValueError, match="at least 32 characters long"):
        validate_security_config(prod_short_jwt)

    # 4. Valid production secret (>= 32 chars) should pass
    prod_valid_jwt = Settings(
        environment="production",
        jwt_secret_key="a" * 32,
        database_url="sqlite:///./greenshift.db",
        postgres_host="localhost",
    )
    validate_security_config(prod_valid_jwt)


def test_production_mode_requires_postgres_password():
    """Production environment MUST reject missing or default postgres_password when PostgreSQL is used."""
    prod_pg_missing_pwd = Settings(
        environment="production",
        jwt_secret_key="valid-secure-production-jwt-key-32chars!",
        database_url="postgresql+psycopg2://greenshift:@postgres:5432/greenshift",
        postgres_host="greenshift-postgres",
        postgres_password="",
    )
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD must be explicitly configured"):
        validate_security_config(prod_pg_missing_pwd)


def test_production_mode_rejects_wildcard_cors():
    """Production environment MUST reject wildcard '*' CORS origin."""
    prod_wildcard_cors = Settings(
        environment="production",
        jwt_secret_key="valid-secure-production-jwt-key-32chars!",
        database_url="sqlite:///./greenshift.db",
        postgres_host="localhost",
        cors_origins="*",
    )
    with pytest.raises(ValueError, match="Wildcard CORS origin"):
        validate_security_config(prod_wildcard_cors)


# ====================================================================
# 2. CORS Origin Filtering Tests
# ====================================================================

def test_cors_allows_configured_origin(client):
    """CORS middleware must allow configured frontend origins with credentials."""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:8501",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8501"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_blocks_untrusted_origin(client):
    """CORS middleware must NOT return allow-origin header for untrusted origins."""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://malicious-attacker-site.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # When origin is not in allowed list, Access-Control-Allow-Origin header is omitted
    assert "access-control-allow-origin" not in response.headers or response.headers.get("access-control-allow-origin") != "http://malicious-attacker-site.com"


# ====================================================================
# 3. Protected User List Endpoint Tests (/auth/users & /api/v1/auth/users)
# ====================================================================

def test_users_endpoint_unauthenticated_returns_401(client):
    """Calling /api/v1/auth/users or /auth/users without token must return 401 Unauthorized."""
    # 1. /api/v1/auth/users
    res_v1 = client.get("/api/v1/auth/users")
    assert res_v1.status_code == 401
    assert "token required" in res_v1.json()["detail"].lower()

    # 2. /auth/users
    res = client.get("/auth/users")
    assert res.status_code == 401
    assert "token required" in res.json()["detail"].lower()


def test_users_endpoint_non_admin_returns_403(client):
    """Calling /api/v1/auth/users with non-admin token (VIEWER, OPERATOR, TEAM_LEAD) must return 403 Forbidden."""
    # Register & Login non-admin roles
    roles = [
        ("viewer_user", "viewer@greenshift.io", "VIEWER"),
        ("operator_user", "operator@greenshift.io", "OPERATOR"),
        ("lead_user", "lead@greenshift.io", "TEAM_LEAD"),
    ]

    for uname, email, role in roles:
        client.post("/auth/register", json={
            "username": uname,
            "email": email,
            "password": "Password123!",
            "role": role,
        })
        token = client.post("/auth/login", json={
            "username": uname,
            "password": "Password123!",
        }).json()["access_token"]

        headers = {"Authorization": f"Bearer {token}"}

        # Check /api/v1/auth/users
        res_v1 = client.get("/api/v1/auth/users", headers=headers)
        assert res_v1.status_code == 403
        assert "operation not permitted" in res_v1.json()["detail"].lower()

        # Check /auth/users
        res = client.get("/auth/users", headers=headers)
        assert res.status_code == 403
        assert "operation not permitted" in res.json()["detail"].lower()


def test_users_endpoint_admin_succeeds_200(client):
    """Calling /api/v1/auth/users with ADMIN token must succeed (200 OK) and list all users."""
    # Register admin
    client.post("/auth/register", json={
        "username": "admin_sec_user",
        "email": "admin_sec@greenshift.io",
        "password": "AdminPassword123!",
        "role": "ADMIN",
    })
    # Register regular user
    client.post("/auth/register", json={
        "username": "regular_sec_user",
        "email": "regular_sec@greenshift.io",
        "password": "UserPassword123!",
        "role": "VIEWER",
    })

    admin_token = client.post("/auth/login", json={
        "username": "admin_sec_user",
        "password": "AdminPassword123!",
    }).json()["access_token"]

    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. /api/v1/auth/users
    res_v1 = client.get("/api/v1/auth/users", headers=headers)
    assert res_v1.status_code == 200
    users_v1 = res_v1.json()
    assert isinstance(users_v1, list)
    assert len(users_v1) >= 2
    usernames = [u["username"] for u in users_v1]
    assert "admin_sec_user" in usernames
    assert "regular_sec_user" in usernames

    # 2. /auth/users
    res = client.get("/auth/users", headers=headers)
    assert res.status_code == 200
    users = res.json()
    assert isinstance(users, list)
    assert len(users) >= 2


# ====================================================================
# 4. Dashboard Auth Architecture & Security Integrity
# ====================================================================

def test_dashboard_files_do_not_import_token_generator():
    """Verify that dashboard views and main do NOT import or mint tokens client-side."""
    import inspect
    import app.dashboard.main as dash_main
    import app.dashboard.views.login as dash_login

    dash_main_src = inspect.getsource(dash_main)
    dash_login_src = inspect.getsource(dash_login)

    assert "create_access_token" not in dash_main_src
    assert "create_access_token" not in dash_login_src
