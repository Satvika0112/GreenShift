"""
GreenShift — Trust & Audit security test suite.

Covers the mandatory security testing section of the Trust & Audit
implementation: RBAC visibility (Platform Admin / Company Admin / Company
User), API authorization on the verify/anchor endpoints, identity-spoofing
resistance (actor_user_id/actor_role/tenant_id/team_id are always
server-derived), tenant isolation across two real tenants, and team
isolation across two teams within one tenant.

Uses the same real file-backed test DB + TestClient pattern already
established by tests/test_p0_tenant_isolation.py and tests/test_rbac.py —
audit_events is append-only (Trust/Audit P0) and is therefore never
deleted in cleanup; every assertion below filters by this file's own
unique tenant/team/job identifiers, so accumulation across test runs
never affects correctness.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.auth import create_access_token, hash_password
from app.shared.models import (
    AuditEventORM,
    EventType,
    JobORM,
    JobStatus,
    TenantORM,
    UserApprovalStatus,
    UserORM,
    UserRole,
)
from app.trust.ledger import append_event


TENANT_A = "tenant-trust-sec-a"
TENANT_B = "tenant-trust-sec-b"
TEAM_A1 = "team-trust-sec-a1"
TEAM_A2 = "team-trust-sec-a2"
TEAM_B1 = "team-trust-sec-b1"


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(JobORM).filter(JobORM.tenant_id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(UserORM).filter(UserORM.tenant_id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.query(UserORM).filter(UserORM.username == "trust_sec_platadm").delete(synchronize_session=False)
        db.query(TenantORM).filter(TenantORM.id.in_([TENANT_A, TENANT_B])).delete(synchronize_session=False)
        db.add(TenantORM(id=TENANT_A, name="Trust Sec Co A", is_active=True))
        db.add(TenantORM(id=TENANT_B, name="Trust Sec Co B", is_active=True))
        db.commit()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _make_user(db, username, email, role, tenant_id=None, team_id=None):
    u = UserORM(
        username=username, email=email, hashed_password=hash_password("Pass123!"),
        role=role, tenant_id=tenant_id, team_id=team_id,
        approval_status=UserApprovalStatus.APPROVED.value, is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    token = create_access_token(
        user_id=u.id, username=u.username,
        role=u.role.value if hasattr(u.role, "value") else str(u.role),
        tenant_id=u.tenant_id, team_id=u.team_id,
    )
    return u, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def identities():
    with SessionLocal() as db:
        plat, plat_h = _make_user(db, "trust_sec_platadm", "platadm@trustsec.io", UserRole.PLATFORM_ADMIN)
        admin_a, admin_a_h = _make_user(db, "trust_sec_admin_a", "adm@a.trustsec.io", UserRole.COMPANY_ADMIN, TENANT_A, TEAM_A1)
        admin_b, admin_b_h = _make_user(db, "trust_sec_admin_b", "adm@b.trustsec.io", UserRole.COMPANY_ADMIN, TENANT_B, TEAM_B1)
        user_a1, user_a1_h = _make_user(db, "trust_sec_user_a1", "u1@a.trustsec.io", UserRole.COMPANY_USER, TENANT_A, TEAM_A1)
        user_a2, user_a2_h = _make_user(db, "trust_sec_user_a2", "u2@a.trustsec.io", UserRole.COMPANY_USER, TENANT_A, TEAM_A2)
        user_b1, user_b1_h = _make_user(db, "trust_sec_user_b1", "u1@b.trustsec.io", UserRole.COMPANY_USER, TENANT_B, TEAM_B1)

        now = datetime.now(timezone.utc)

        def make_job(job_id, tenant_id, team_id):
            db.add(JobORM(
                job_id=job_id, team_id=team_id, tenant_id=tenant_id, company_name=tenant_id,
                job_type="TRAINING", priority="NORMAL", status=JobStatus.SUBMITTED,
                submitted_at=now, deadline=now + timedelta(hours=24), runtime_minutes=30,
                power_kw=1.0, region="IN-TG", container_image="python:3.10-slim",
            ))

        job_a1 = f"JOB-{TEAM_A1}-001"
        job_a2 = f"JOB-{TEAM_A2}-001"
        job_b1 = f"JOB-{TEAM_B1}-001"
        make_job(job_a1, TENANT_A, TEAM_A1)
        make_job(job_a2, TENANT_A, TEAM_A2)
        make_job(job_b1, TENANT_B, TEAM_B1)
        db.commit()

        # Real audit events via the real ledger, with real actor identities —
        # exactly what app.trust.service.record_* produces in production.
        append_event(db, EventType.JOB_SUBMITTED, job_id=job_a1, payload={},
                     actor=user_a1, tenant_id=TENANT_A, team_id=TEAM_A1, source_service="ingest")
        append_event(db, EventType.JOB_SUBMITTED, job_id=job_a2, payload={},
                     actor=user_a2, tenant_id=TENANT_A, team_id=TEAM_A2, source_service="ingest")
        append_event(db, EventType.JOB_SUBMITTED, job_id=job_b1, payload={},
                     actor=user_b1, tenant_id=TENANT_B, team_id=TEAM_B1, source_service="ingest")

        return {
            "plat_headers": plat_h, "admin_a_headers": admin_a_h, "admin_b_headers": admin_b_h,
            "user_a1_headers": user_a1_h, "user_a2_headers": user_a2_h, "user_b1_headers": user_b1_h,
            "job_a1": job_a1, "job_a2": job_a2, "job_b1": job_b1,
        }


# ─────────────────────────────────────────────────────────────────────────────
# RBAC — /trust/events visibility
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustEventsRBAC:
    def test_platform_admin_sees_events_across_all_tenants(self, client, identities):
        resp = client.get("/api/v1/trust/events?limit=1000", headers=identities["plat_headers"])
        assert resp.status_code == 200
        job_ids = {e["job_id"] for e in resp.json()["events"]}
        assert identities["job_a1"] in job_ids
        assert identities["job_a2"] in job_ids
        assert identities["job_b1"] in job_ids

    def test_company_admin_sees_all_teams_in_own_company_not_other_company(self, client, identities):
        resp = client.get("/api/v1/trust/events?limit=1000", headers=identities["admin_a_headers"])
        assert resp.status_code == 200
        job_ids = {e["job_id"] for e in resp.json()["events"]}
        assert identities["job_a1"] in job_ids
        assert identities["job_a2"] in job_ids
        assert identities["job_b1"] not in job_ids

    def test_company_user_sees_only_own_team_not_other_team_not_other_company(self, client, identities):
        resp = client.get("/api/v1/trust/events?limit=1000", headers=identities["user_a1_headers"])
        assert resp.status_code == 200
        job_ids = {e["job_id"] for e in resp.json()["events"]}
        assert identities["job_a1"] in job_ids
        assert identities["job_a2"] not in job_ids
        assert identities["job_b1"] not in job_ids

    def test_company_user_in_other_team_cannot_see_teammate_of_different_team(self, client, identities):
        resp = client.get("/api/v1/trust/events?limit=1000", headers=identities["user_a2_headers"])
        assert resp.status_code == 200
        job_ids = {e["job_id"] for e in resp.json()["events"]}
        assert identities["job_a2"] in job_ids
        assert identities["job_a1"] not in job_ids

    def test_second_tenant_company_admin_isolated_from_first_tenant(self, client, identities):
        resp = client.get("/api/v1/trust/events?limit=1000", headers=identities["admin_b_headers"])
        assert resp.status_code == 200
        job_ids = {e["job_id"] for e in resp.json()["events"]}
        assert identities["job_b1"] in job_ids
        assert identities["job_a1"] not in job_ids
        assert identities["job_a2"] not in job_ids

    def test_company_user_with_no_team_sees_zero_events_not_the_whole_tenant(self, client, identities):
        """Regression: scope_audit_events_query previously only appended the
        team filter `and user.team_id`, so a Company User whose team_id is
        None (not yet assigned) skipped the team clause entirely and fell
        through to the tenant filter alone — seeing every team's events
        instead of none. Must fail closed to zero, matching
        can_view_job_audit's `bool(user.team_id) and ...` sibling check."""
        with SessionLocal() as db:
            _, no_team_headers = _make_user(
                db, "trust_sec_no_team_user", "noteam@a.trustsec.io",
                UserRole.COMPANY_USER, TENANT_A, None,
            )
        resp = client.get("/api/v1/trust/events?limit=1000", headers=no_team_headers)
        assert resp.status_code == 200
        job_ids = {e["job_id"] for e in resp.json()["events"]}
        assert identities["job_a1"] not in job_ids
        assert identities["job_a2"] not in job_ids
        assert job_ids == set()


# ─────────────────────────────────────────────────────────────────────────────
# RBAC — /trust/jobs/{job_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestJobAuditTrailRBAC:
    def test_own_team_member_can_view(self, client, identities):
        resp = client.get(f"/api/v1/trust/jobs/{identities['job_a1']}", headers=identities["user_a1_headers"])
        assert resp.status_code == 200

    def test_other_team_member_gets_404_not_403(self, client, identities):
        resp = client.get(f"/api/v1/trust/jobs/{identities['job_a1']}", headers=identities["user_a2_headers"])
        assert resp.status_code == 404

    def test_company_admin_can_view_any_team_in_own_company(self, client, identities):
        resp = client.get(f"/api/v1/trust/jobs/{identities['job_a2']}", headers=identities["admin_a_headers"])
        assert resp.status_code == 200

    def test_cross_tenant_admin_gets_404(self, client, identities):
        resp = client.get(f"/api/v1/trust/jobs/{identities['job_a1']}", headers=identities["admin_b_headers"])
        assert resp.status_code == 404

    def test_cross_tenant_user_gets_404(self, client, identities):
        resp = client.get(f"/api/v1/trust/jobs/{identities['job_a1']}", headers=identities["user_b1_headers"])
        assert resp.status_code == 404

    def test_platform_admin_can_view_any_job(self, client, identities):
        resp = client.get(f"/api/v1/trust/jobs/{identities['job_b1']}", headers=identities["plat_headers"])
        assert resp.status_code == 200

    def test_events_filter_by_job_id_also_enforces_authorization(self, client, identities):
        """job_id is a valid /trust/events filter, but it must never bypass RBAC."""
        resp = client.get(f"/api/v1/trust/events?job_id={identities['job_a1']}", headers=identities["user_a2_headers"])
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# API authorization — chain verification & anchors
# ─────────────────────────────────────────────────────────────────────────────

class TestChainAndAnchorAuthorization:
    def test_company_user_cannot_verify_global_chain(self, client, identities):
        resp = client.get("/api/v1/trust/verify", headers=identities["user_a1_headers"])
        assert resp.status_code == 403

    def test_company_admin_cannot_verify_global_chain(self, client, identities):
        resp = client.get("/api/v1/trust/verify", headers=identities["admin_a_headers"])
        assert resp.status_code == 403

    def test_platform_admin_can_verify_global_chain(self, client, identities):
        resp = client.get("/api/v1/trust/verify", headers=identities["plat_headers"])
        assert resp.status_code == 200
        assert "valid" in resp.json()

    def test_unauthenticated_verify_rejected(self, client):
        resp = client.get("/api/v1/trust/verify")
        assert resp.status_code == 401

    def test_company_user_cannot_create_anchor(self, client, identities):
        resp = client.post("/api/v1/trust/anchor/create", headers=identities["user_a1_headers"])
        assert resp.status_code == 403

    def test_company_admin_cannot_create_anchor(self, client, identities):
        resp = client.post("/api/v1/trust/anchor/create", headers=identities["admin_a_headers"])
        assert resp.status_code == 403

    def test_platform_admin_can_create_anchor(self, client, identities):
        resp = client.post("/api/v1/trust/anchor/create", headers=identities["plat_headers"])
        assert resp.status_code == 200
        assert resp.json()["status"] in ("created", "empty_chain")

    def test_company_user_cannot_list_anchors(self, client, identities):
        resp = client.get("/api/v1/trust/anchors", headers=identities["user_a1_headers"])
        assert resp.status_code == 403

    def test_company_admin_cannot_verify_anchor_by_id(self, client, identities):
        resp = client.get("/api/v1/trust/anchors/1/verify", headers=identities["admin_a_headers"])
        assert resp.status_code == 403

    def test_client_supplied_anchor_sequence_and_hash_are_never_honored(self, client, identities):
        """Anchor creation takes no body at all — there is no field a client
        could use to inject a sequence/hash even if it tried."""
        resp = client.post(
            "/api/v1/trust/anchor/create",
            headers=identities["plat_headers"],
            json={"sequence": 999999, "root_hash": "f" * 64},
        )
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] == "created":
            assert body["anchor"]["sequence"] != 999999
            assert body["anchor"]["root_hash"] != "f" * 64


# ─────────────────────────────────────────────────────────────────────────────
# Identity spoofing
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentitySpoofing:
    def test_forged_actor_and_tenant_fields_in_job_submission_are_ignored(self, client, identities):
        """JobSubmitRequest has no tenant_id/actor_* fields at all — a client
        including them is silently ignored by Pydantic, and the audit event's
        real actor/tenant columns always come from the authenticated user_a1,
        never from anything in the request body."""
        job_id = "JOB-SPOOF-IDENTITY-001"
        resp = client.post(
            "/api/v1/jobs",
            headers=identities["user_a1_headers"],
            json={
                "job_id": job_id,
                "team_id": TEAM_A1,
                "deadline": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
                "runtime_minutes": 30,
                "power_kw": 1.0,
                "region": "IN-TG",
                "container_image": "python:3.10-slim",
                # forged / unexpected identity fields — none of these exist
                # on JobSubmitRequest and must have zero effect:
                "tenant_id": TENANT_B,
                "actor_user_id": "99999",
                "actor_username": "root",
                "actor_role": "PLATFORM_ADMIN",
                "team_id_override": TEAM_A2,
            },
        )
        assert resp.status_code == 201, resp.text

        with SessionLocal() as db:
            job = db.get(JobORM, job_id)
            assert job.tenant_id == TENANT_A  # not the forged TENANT_B
            assert job.team_id == TEAM_A1

            event = (
                db.query(AuditEventORM)
                .filter(AuditEventORM.job_id == job_id, AuditEventORM.event_type == EventType.JOB_SUBMITTED)
                .order_by(AuditEventORM.sequence.desc())
                .first()
            )
            assert event is not None
            assert event.tenant_id == TENANT_A
            assert event.team_id == TEAM_A1
            assert event.actor_username == "trust_sec_user_a1"
            assert event.actor_role == "COMPANY_USER"
            assert event.actor_user_id != "99999"
            assert event.actor_role != "PLATFORM_ADMIN"

    def test_direct_append_event_call_with_forged_actor_object_still_only_trusts_real_attributes(self, db):
        """Defense in depth at the service boundary itself: append_event()
        only ever reads actor.id/.username/.role/.tenant_id/.team_id off
        whatever object is passed as `actor` — there is no separate
        client-controlled parameter it could be tricked into using instead."""
        class ForgedActor:
            id = 1
            username = "trust_sec_admin_a"  # real username, but...
            role = UserRole.COMPANY_USER    # ...this object's OWN role, not spoofable to PLATFORM_ADMIN
            tenant_id = TENANT_A
            team_id = TEAM_A1

        event = append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-FORGE-ACTOR-001", actor=ForgedActor())
        assert event.actor_role == "COMPANY_USER"
        assert event.actor_type == "USER"


# ─────────────────────────────────────────────────────────────────────────────
# Tenant & team isolation (explicit, dedicated assertions)
# ─────────────────────────────────────────────────────────────────────────────

class TestTenantAndTeamIsolation:
    def test_tenant_a_cannot_see_tenant_b_events_and_vice_versa(self, client, identities):
        resp_a = client.get("/api/v1/trust/events?limit=1000", headers=identities["admin_a_headers"])
        resp_b = client.get("/api/v1/trust/events?limit=1000", headers=identities["admin_b_headers"])
        job_ids_a = {e["job_id"] for e in resp_a.json()["events"]}
        job_ids_b = {e["job_id"] for e in resp_b.json()["events"]}
        assert identities["job_b1"] not in job_ids_a
        assert identities["job_a1"] not in job_ids_b
        assert identities["job_a2"] not in job_ids_b

    def test_team_filter_cannot_be_used_to_escape_company_user_scope(self, client, identities):
        """A Company User explicitly requesting another team's team_id filter
        gets an empty intersection, not that team's events — the RBAC scope
        is applied before the filter, never bypassed by it."""
        resp = client.get(f"/api/v1/trust/events?team_id={TEAM_A2}", headers=identities["user_a1_headers"])
        assert resp.status_code == 200
        job_ids = {e["job_id"] for e in resp.json()["events"]}
        assert identities["job_a2"] not in job_ids

    def test_actor_filter_scoped_correctly_for_company_admin(self, client, identities):
        resp = client.get(
            "/api/v1/trust/events?actor=trust_sec_user_a1", headers=identities["admin_a_headers"],
        )
        assert resp.status_code == 200
        job_ids = {e["job_id"] for e in resp.json()["events"]}
        assert identities["job_a1"] in job_ids


# ─────────────────────────────────────────────────────────────────────────────
# Audit export respects the same RBAC + filters
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditExport:
    def test_export_never_includes_other_tenants_events(self, client, identities):
        resp = client.get("/api/v1/trust/events/export?format=json&limit=1000", headers=identities["admin_a_headers"])
        assert resp.status_code == 200
        assert identities["job_b1"] not in resp.text

    def test_export_csv_format(self, client, identities):
        resp = client.get("/api/v1/trust/events/export?format=csv&limit=1000", headers=identities["admin_a_headers"])
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "sequence,event_id,event_type" in resp.text
