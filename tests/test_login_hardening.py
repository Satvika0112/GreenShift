"""
Login Flow Hardening — regression tests filling the genuine gaps found by
auditing the existing login/JWT/RBAC implementation (see
docs/greenshift_login_hardening_status.md for the full audit + report).

Everything else about login was already correct and is exercised by
tests/test_auth.py, tests/test_p0_auth_registration.py,
tests/test_multitenant_auth.py, tests/test_phase3_security.py, and
tests/test_company_registration.py — this file adds only what those did not
already cover:

  - GET /auth/me for PLATFORM_ADMIN specifically (only COMPANY_USER/
    COMPANY_ADMIN were previously covered), including the nested
    `company: {id, name}` object being None for a tenant-less admin.
  - The nested `company` object's exact shape for COMPANY_ADMIN/COMPANY_USER.
  - POST /auth/login ignoring a forged role/tenant_id/team_id/company_id in
    the request body (the equivalent check already existed for
    registration, not for login).
  - POST /auth/login-email now being rate-limited (previously unthrottled —
    a genuine gap; see the fix in app/api/routers/auth.py).
  - A JWT signed with the wrong secret is rejected (only malformed/expired
    were previously covered).
  - The login response never includes hashed_password.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.config import settings
from app.shared.database import get_db
from app.shared.auth import hash_password, create_access_token
from app.shared.models import TenantORM, UserApprovalStatus, UserORM, UserRole

# Final Consistency Audit: this file previously seeded/queried the real,
# on-disk greenshift.db directly via app.shared.database.SessionLocal (the
# same database a running dev server uses), then wiped all UserORM/TenantORM
# rows before and after every test. Once any real data existed with
# dependent foreign keys (e.g. from live E2E verification against a dev
# server sharing that file), the wipe itself started raising
# `FOREIGN KEY constraint failed` and permanently broke this entire file —
# and, worse, running these tests against a real dev database would delete
# real users/tenants. Fixed by switching to the same isolated in-memory
# `db` fixture (see tests/conftest.py) every other test file in this suite
# already uses, wired into the app via the standard `get_db` override —
# no test assertions changed.


@pytest.fixture(autouse=True)
def override_db(db):
    def _get_test_db():
        yield db

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client():
    return TestClient(app)


def _make_user(db, username, email, password, role, tenant_id=None, team_id=None):
    u = UserORM(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role=role,
        tenant_id=tenant_id,
        team_id=team_id,
        approval_status=UserApprovalStatus.APPROVED.value,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class TestAuthMeForEveryRole:
    """GET /auth/me for each of the 3 roles, including the nested company object."""

    def test_platform_admin_auth_me(self, client, db):
        _make_user(db, "login_hardening_pa", "pa@greenshift.io", "Pass123!", UserRole.PLATFORM_ADMIN)

        login = client.post("/auth/login", json={"username": "login_hardening_pa", "password": "Pass123!"})
        assert login.status_code == 200
        token = login.json()["access_token"]

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        body = me.json()
        assert body["role"] == "PLATFORM_ADMIN"
        assert body["tenant_id"] is None
        # A Platform Admin has no company — this must be None, not fabricated.
        assert body["company"] is None

    def test_company_admin_auth_me_includes_nested_company_object(self, client, db):
        db.add(TenantORM(id="tenant-login-hardening", name="Login Hardening Corp", is_active=True))
        db.commit()
        _make_user(
            db, "login_hardening_ca", "ca@greenshift.io", "Pass123!",
            UserRole.COMPANY_ADMIN, tenant_id="tenant-login-hardening", team_id="team-default",
        )

        login = client.post("/auth/login", json={"username": "login_hardening_ca", "password": "Pass123!"})
        assert login.status_code == 200

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
        assert me.status_code == 200
        body = me.json()
        assert body["role"] == "COMPANY_ADMIN"
        assert body["tenant_id"] == "tenant-login-hardening"
        assert body["team_id"] == "team-default"
        assert body["company"] == {"id": "tenant-login-hardening", "name": "Login Hardening Corp"}

    def test_company_user_auth_me_includes_nested_company_object(self, client, db):
        db.add(TenantORM(id="tenant-login-hardening-2", name="Second Login Corp", is_active=True))
        db.commit()
        _make_user(
            db, "login_hardening_cu", "cu@greenshift.io", "Pass123!",
            UserRole.COMPANY_USER, tenant_id="tenant-login-hardening-2", team_id="team-ops",
        )

        login = client.post("/auth/login", json={"username": "login_hardening_cu", "password": "Pass123!"})
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
        assert me.status_code == 200
        body = me.json()
        assert body["role"] == "COMPANY_USER"
        assert body["company"] == {"id": "tenant-login-hardening-2", "name": "Second Login Corp"}


class TestLoginNeverTrustsClientSuppliedIdentity:
    """POST /auth/login must derive role/tenant_id/team_id/company entirely
    from the server-side UserORM row — never from the request body, even if
    a client includes extra fields Pydantic doesn't declare."""

    def test_forged_fields_in_login_body_are_ignored(self, client, db):
        db.add(TenantORM(id="tenant-real-login", name="Real Login Corp", is_active=True))
        db.add(TenantORM(id="tenant-attacker-target", name="Attacker Target Corp", is_active=True))
        db.commit()
        _make_user(
            db, "login_forge_victim", "victim@greenshift.io", "Pass123!",
            UserRole.COMPANY_USER, tenant_id="tenant-real-login", team_id="team-real",
        )

        resp = client.post("/auth/login", json={
            "username": "login_forge_victim",
            "password": "Pass123!",
            # None of these exist on UserLoginRequest — must have zero effect.
            "role": "PLATFORM_ADMIN",
            "tenant_id": "tenant-attacker-target",
            "team_id": "team-attacker",
            "company_id": "tenant-attacker-target",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["role"] == "COMPANY_USER"
        assert body["user"]["tenant_id"] == "tenant-real-login"
        assert body["user"]["team_id"] == "team-real"
        assert body["user"]["company"]["id"] == "tenant-real-login"

        # The JWT itself must carry the real claims too, not the forged ones.
        decoded = jwt.decode(body["access_token"], settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert decoded["role"] == "COMPANY_USER"
        assert decoded["tenant_id"] == "tenant-real-login"
        assert decoded["team_id"] == "team-real"

    def test_login_response_never_includes_hashed_password(self, client, db):
        _make_user(db, "login_hash_check", "hashcheck@greenshift.io", "Pass123!", UserRole.COMPANY_USER)

        resp = client.post("/auth/login", json={"username": "login_hash_check", "password": "Pass123!"})
        assert resp.status_code == 200
        assert "hashed_password" not in resp.json()["user"]
        assert "hashed_password" not in resp.text


class TestJwtSignatureValidation:
    def test_token_signed_with_wrong_secret_is_rejected(self, client, db):
        user = _make_user(db, "login_wrong_sig", "wrongsig@greenshift.io", "Pass123!", UserRole.COMPANY_USER)
        user_id = user.id

        forged_payload = {
            "sub": str(user_id), "user_id": user_id, "username": "login_wrong_sig",
            "role": "PLATFORM_ADMIN", "team_id": None, "tenant_id": None,
            "company_name": None, "approval_status": "APPROVED",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }
        forged_token = jwt.encode(forged_payload, "a-completely-different-secret", algorithm=settings.jwt_algorithm)

        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
        assert resp.status_code == 401


class TestLoginEmailRateLimited:
    """POST /auth/login-email previously had no rate limit at all — a fully
    functional, unthrottled brute-force surface. Now matches /auth/login's
    10/minute limit."""

    def test_login_email_is_rate_limited(self, client, db):
        _make_user(db, "login_email_rl", "rl@greenshift.io", "Pass123!", UserRole.COMPANY_USER)

        statuses = []
        for _ in range(15):
            resp = client.post("/auth/login-email", json={"email": "rl@greenshift.io", "password": "WrongPass!"})
            statuses.append(resp.status_code)

        assert 429 in statuses, f"Expected a 429 among repeated attempts, got: {statuses}"
