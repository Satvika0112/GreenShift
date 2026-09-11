"""
Tests for the Notification system.

Validates:
1. Recipient is server-derived — GET /notifications only ever returns the
   caller's own notifications.
2. Tenant/user isolation — a user cannot read or mark-read another user's
   notification (404, not leaking existence).
3. Duplicate logical events are deduplicated (dedup_key unique constraint).
4. Email delivery failure never changes job/workload state.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.notify.email import process_pending_emails
from app.notify.service import (
    create_notification,
    get_notifications,
    get_unread_count,
    mark_all_read,
    mark_read,
)
from app.shared.auth import create_access_token, hash_password
from app.shared.database import get_db
from app.shared.models import EventType, JobORM, JobStatus, NotificationORM, UserORM, UserRole
from app.shared.utils import utcnow

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_db(db):
    def _get_test_db():
        yield db

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def two_users(db):
    alice = UserORM(
        username="notif_alice", email="alice@greenshift.io",
        hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_USER,
        tenant_id="tenant-a", is_active=True,
    )
    bob = UserORM(
        username="notif_bob", email="bob@greenshift.io",
        hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_USER,
        tenant_id="tenant-b", is_active=True,
    )
    db.add_all([alice, bob])
    db.commit()
    db.refresh(alice)
    db.refresh(bob)
    return {"alice": alice, "bob": bob}


def get_token(user: UserORM) -> str:
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    return create_access_token(user_id=user.id, username=user.username, role=role_str, tenant_id=user.tenant_id)


class TestRecipientAndTenantIsolation:
    def test_notification_visible_only_to_recipient(self, db, two_users):
        alice, bob = two_users["alice"], two_users["bob"]
        create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title="Approved", message="Your job was approved.",
            tenant_id=alice.tenant_id, job_id="JOB-1",
        )

        alice_token = get_token(alice)
        bob_token = get_token(bob)

        res_alice = client.get("/notifications", headers={"Authorization": f"Bearer {alice_token}"})
        assert res_alice.status_code == 200
        assert len(res_alice.json()) == 1
        assert res_alice.json()[0]["title"] == "Approved"

        res_bob = client.get("/notifications", headers={"Authorization": f"Bearer {bob_token}"})
        assert res_bob.status_code == 200
        assert res_bob.json() == []

    def test_user_cannot_mark_another_users_notification_read(self, db, two_users):
        alice, bob = two_users["alice"], two_users["bob"]
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title="Approved", message="msg",
            tenant_id=alice.tenant_id, job_id="JOB-2",
        )

        bob_token = get_token(bob)
        res = client.patch(f"/notifications/{notif.id}/read", headers={"Authorization": f"Bearer {bob_token}"})
        assert res.status_code == 404

        db.refresh(notif)
        assert notif.read_at is None

    def test_recipient_is_server_derived_not_client_supplied(self, db, two_users):
        """API has no way to pass recipient_user_id — GET /notifications always uses the caller's own id."""
        import inspect
        from app.api.routers.notifications import api_get_notifications
        sig = inspect.signature(api_get_notifications)
        assert "recipient_user_id" not in sig.parameters
        assert "user_id" not in sig.parameters

    def test_mark_all_read_only_affects_caller(self, db, two_users):
        alice, bob = two_users["alice"], two_users["bob"]
        for i in range(3):
            create_notification(
                db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_GRANTED,
                category="APPROVAL", severity="INFO", title=f"N{i}", message="msg",
                tenant_id=alice.tenant_id, job_id=f"JOB-A{i}",
            )
        create_notification(
            db, recipient_user_id=bob.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title="Bob's", message="msg",
            tenant_id=bob.tenant_id, job_id="JOB-B1",
        )

        alice_token = get_token(alice)
        res = client.patch("/notifications/read-all", headers={"Authorization": f"Bearer {alice_token}"})
        assert res.status_code == 200
        assert res.json()["marked_read"] == 3

        assert get_unread_count(db, alice.id) == 0
        assert get_unread_count(db, bob.id) == 1


class TestDeduplication:
    def test_duplicate_event_for_same_recipient_is_absorbed(self, db, two_users):
        alice_id = two_users["alice"].id
        alice_tenant_id = two_users["alice"].tenant_id
        kwargs = dict(
            recipient_user_id=alice_id, event_type=EventType.K8S_JOB_FAILED,
            category="EXECUTION", severity="CRITICAL", title="Failed", message="Job failed.",
            tenant_id=alice_tenant_id, job_id="JOB-DUP",
        )
        first = create_notification(db, **kwargs)
        second = create_notification(db, **kwargs)

        assert first is not None
        assert second is None  # silently absorbed, not a duplicate row

        rows = db.query(NotificationORM).filter(
            NotificationORM.recipient_user_id == alice_id,
            NotificationORM.job_id == "JOB-DUP",
        ).all()
        assert len(rows) == 1

    def test_different_suffix_creates_distinct_notification(self, db, two_users):
        alice = two_users["alice"]
        n1 = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.K8S_JOB_FAILED,
            category="EXECUTION", severity="CRITICAL", title="Failed #1", message="m",
            tenant_id=alice.tenant_id, job_id="JOB-DUP2", dedup_suffix="attempt-1",
        )
        n2 = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.K8S_JOB_FAILED,
            category="EXECUTION", severity="CRITICAL", title="Failed #2", message="m",
            tenant_id=alice.tenant_id, job_id="JOB-DUP2", dedup_suffix="attempt-2",
        )
        assert n1 is not None and n2 is not None
        assert n1.id != n2.id


class TestEmailFailureIsolation:
    def test_email_delivery_failure_does_not_touch_job_state(self, db, two_users):
        alice = two_users["alice"]
        job = JobORM(
            job_id="JOB-EMAIL-ISO",
            team_id="team-x",
            tenant_id=alice.tenant_id,
            submitted_by_user_id=alice.id,
            submitted_at=utcnow(),
            deadline=utcnow() + timedelta(hours=2),
            runtime_minutes=10,
            power_kw=1.0,
            region="IN-TG",
            container_image="greenshift/sample:v1",
            status=JobStatus.FAILED,
        )
        db.add(job)
        db.commit()

        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.K8S_JOB_FAILED,
            category="EXECUTION", severity="CRITICAL", title="Workload failed", message="It failed.",
            tenant_id=alice.tenant_id, job_id=job.job_id, email_required=True,
        )
        assert notif.email_status == "PENDING"

        from app.shared.config import settings
        original_enabled = settings.smtp_enabled
        original_host = settings.smtp_host
        settings.smtp_enabled = True
        settings.smtp_host = "smtp.invalid.example"
        try:
            with patch("app.notify.email.send_email", side_effect=RuntimeError("SMTP connection refused")):
                process_pending_emails(db, limit=10)
        finally:
            settings.smtp_enabled = original_enabled
            settings.smtp_host = original_host

        db.refresh(notif)
        db.refresh(job)

        # Email bookkeeping updated...
        assert notif.email_attempts == 1
        assert notif.email_status in ("PENDING", "FAILED")
        # ...but the job's own state is completely untouched by the email failure.
        assert job.status == JobStatus.FAILED

    def test_smtp_disabled_is_a_noop_and_never_raises(self, db, two_users):
        alice = two_users["alice"]
        create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.K8S_JOB_FAILED,
            category="EXECUTION", severity="CRITICAL", title="x", message="y",
            tenant_id=alice.tenant_id, job_id="JOB-NOSMTP", email_required=True,
        )
        from app.shared.config import settings
        assert settings.smtp_enabled is False
        count = process_pending_emails(db, limit=10)
        assert count == 0


class TestNotificationPreferences:
    """GET/PUT /notifications/preferences: lazily created, self-scoped,
    email_system is never client-editable, and preferences actually gate
    the email channel inside create_notification()."""

    def test_get_preferences_lazily_creates_all_enabled_defaults(self, db, two_users):
        alice = two_users["alice"]
        token = get_token(alice)
        res = client.get("/notifications/preferences", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        body = res.json()
        assert body == {
            "email_workload": True,
            "email_scheduling": True,
            "email_approval": True,
            "email_execution": True,
            "email_system": True,
        }

    def test_put_preferences_updates_only_supplied_fields(self, db, two_users):
        alice = two_users["alice"]
        token = get_token(alice)
        res = client.put(
            "/notifications/preferences",
            headers={"Authorization": f"Bearer {token}"},
            json={"email_scheduling": False},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["email_scheduling"] is False
        assert body["email_workload"] is True

    def test_email_system_cannot_be_disabled_via_api(self, db, two_users):
        alice = two_users["alice"]
        token = get_token(alice)
        res = client.put(
            "/notifications/preferences",
            headers={"Authorization": f"Bearer {token}"},
            json={"email_system": False},
        )
        assert res.status_code == 200
        assert res.json()["email_system"] is True

    def test_preferences_are_self_scoped_not_shared_across_users(self, db, two_users):
        alice, bob = two_users["alice"], two_users["bob"]
        client.put(
            "/notifications/preferences",
            headers={"Authorization": f"Bearer {get_token(alice)}"},
            json={"email_approval": False},
        )
        res_bob = client.get("/notifications/preferences", headers={"Authorization": f"Bearer {get_token(bob)}"})
        assert res_bob.json()["email_approval"] is True

    def test_disabled_category_preference_forces_email_not_required_but_still_creates_notification(self, db, two_users):
        from app.notify.service import update_preferences
        alice = two_users["alice"]
        update_preferences(db, user_id=alice.id, email_execution=False)

        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.K8S_JOB_COMPLETED,
            category="EXECUTION", severity="INFO", title="Completed", message="Done.",
            tenant_id=alice.tenant_id, job_id="JOB-PREF-1", email_required=True,
        )
        assert notif is not None
        assert notif.title == "Completed"
        assert notif.email_required is False
        assert notif.email_status == "NOT_REQUIRED"

    def test_security_category_email_is_never_gated_by_preference(self, db, two_users):
        alice = two_users["alice"]
        from app.notify.service import update_preferences
        update_preferences(db, user_id=alice.id, email_workload=False, email_scheduling=False, email_approval=False, email_execution=False)

        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.AUTH_ACCESS_DENIED,
            category="SECURITY", severity="CRITICAL", title="Access denied", message="msg",
            tenant_id=alice.tenant_id, email_required=True,
        )
        assert notif.email_required is True
        assert notif.email_status == "PENDING"

    def test_unauthenticated_preferences_request_rejected(self, db):
        res = client.get("/notifications/preferences")
        assert res.status_code == 401


class TestApprovalRequiredRecipientResolution:
    """The 'approval required' fan-out (app.decide.service.schedule_and_store)
    must reach exactly the users app.approval.service.check_user_approval_permission
    would actually authorize: tenant COMPANY_ADMINs + all PLATFORM_ADMINs, never
    a COMPANY_USER, never another tenant's admin."""

    @pytest.fixture
    def rbac_users(self, db):
        platform_admin = UserORM(
            username="notif_platform_admin", email="pa@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.PLATFORM_ADMIN,
            tenant_id=None, is_active=True,
        )
        tenant_a_admin = UserORM(
            username="notif_tenant_a_admin", email="taa@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_ADMIN,
            tenant_id="tenant-approval-a", is_active=True,
        )
        tenant_b_admin = UserORM(
            username="notif_tenant_b_admin", email="tba@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_ADMIN,
            tenant_id="tenant-approval-b", is_active=True,
        )
        tenant_a_user = UserORM(
            username="notif_tenant_a_user", email="tau@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_USER,
            tenant_id="tenant-approval-a", is_active=True,
        )
        db.add_all([platform_admin, tenant_a_admin, tenant_b_admin, tenant_a_user])
        db.commit()
        for u in (platform_admin, tenant_a_admin, tenant_b_admin, tenant_a_user):
            db.refresh(u)
        return {
            "platform_admin": platform_admin,
            "tenant_a_admin": tenant_a_admin,
            "tenant_b_admin": tenant_b_admin,
            "tenant_a_user": tenant_a_user,
        }

    def test_approval_required_notifies_tenant_admin_and_platform_admin_only(self, db, rbac_users):
        from app.decide.service import schedule_and_store
        from app.shared.models import JobSubmitRequest
        from app.ingest.jobs import submit_job

        req = JobSubmitRequest(
            job_id="JOB-APPROVAL-FANOUT-1",
            team_id="team-approval-a",
            deadline=utcnow() + timedelta(hours=24),
            runtime_minutes=30,
            power_kw=0.5,
            region="IN-WE",
            container_image="greenshift/sample-workload:latest",
            deferrable=True,
        )
        job = submit_job(db, req, tenant_id="tenant-approval-a", submitted_by_user_id=rbac_users["tenant_a_user"].id)
        schedule_and_store(db, job, record_audit=False)
        db.refresh(job)
        assert job.status == JobStatus.PENDING_APPROVAL

        approval_notifs = (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == job.job_id, NotificationORM.category == "APPROVAL")
            .all()
        )
        recipient_ids = {n.recipient_user_id for n in approval_notifs}

        assert rbac_users["tenant_a_admin"].id in recipient_ids
        assert rbac_users["platform_admin"].id in recipient_ids
        assert rbac_users["tenant_b_admin"].id not in recipient_ids
        assert rbac_users["tenant_a_user"].id not in recipient_ids
        admin_notif = next(n for n in approval_notifs if n.recipient_user_id == rbac_users["tenant_a_admin"].id)
        assert admin_notif.email_required is True


class TestLifecycleTriggers:
    """Real lifecycle events (submit / scheduling-failure) create the expected
    notification for the submitter, mapped to real EventType/JobStatus."""

    def test_job_submission_creates_workload_notification(self, db, two_users):
        from app.shared.models import JobSubmitRequest
        from app.ingest.jobs import submit_job

        alice = two_users["alice"]
        req = JobSubmitRequest(
            job_id="JOB-SUBMIT-NOTIF-1",
            team_id="team-x",
            deadline=utcnow() + timedelta(hours=6),
            runtime_minutes=15,
            power_kw=1.0,
            region="IN-TG",
            container_image="greenshift/sample-workload:latest",
        )
        submit_job(db, req, tenant_id=alice.tenant_id, submitted_by_user_id=alice.id)

        notif = (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == "JOB-SUBMIT-NOTIF-1", NotificationORM.event_type == EventType.JOB_SUBMITTED)
            .first()
        )
        assert notif is not None
        assert notif.recipient_user_id == alice.id
        assert notif.category == "WORKLOAD"

    def test_scheduling_failure_notifies_submitter_with_email_required(self, db, two_users):
        from app.decide.service import process_pending_jobs
        from app.shared.models import JobSubmitRequest
        from app.ingest.jobs import submit_job

        alice = two_users["alice"]
        req = JobSubmitRequest(
            job_id="JOB-SCHED-FAIL-NOTIF-1",
            team_id="team-x",
            deadline=utcnow() + timedelta(hours=12),
            runtime_minutes=60,
            power_kw=0.5,
            region="IN-WE",
            container_image="greenshift/sample-workload:latest",
            carbon_budget_kg=0.000001,
        )
        submit_job(db, req, tenant_id=alice.tenant_id, submitted_by_user_id=alice.id)
        process_pending_jobs(db)

        job = db.get(JobORM, "JOB-SCHED-FAIL-NOTIF-1")
        assert job.status == JobStatus.FAILED

        notif = (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == "JOB-SCHED-FAIL-NOTIF-1", NotificationORM.event_type == EventType.SCHEDULING_FAILED)
            .first()
        )
        assert notif is not None
        assert notif.recipient_user_id == alice.id
        assert notif.severity == "CRITICAL"
        assert notif.email_required is True


class TestEmailTemplates:
    """app.notify.templates.render_email produces real, job-aware content
    (region, native currency, regional timezone) and safely falls back to
    the notification's own title/message when no template/job applies."""

    def test_schedule_approved_template_includes_real_job_and_currency_info(self, db, two_users):
        from app.notify.templates import render_email
        from app.shared.models import ScheduleDecisionORM

        alice = two_users["alice"]
        job = JobORM(
            job_id="JOB-TEMPLATE-1", team_id="team-x", tenant_id=alice.tenant_id,
            submitted_by_user_id=alice.id, submitted_at=utcnow(), deadline=utcnow() + timedelta(hours=6),
            runtime_minutes=30, power_kw=2.0, region="AU-SA-Small",
            container_image="greenshift/sample-workload:latest", status=JobStatus.APPROVED,
            workload_name="template-test-workload",
        )
        db.add(job)
        db.commit()
        decision = ScheduleDecisionORM(
            job_id=job.job_id, selected_start=utcnow() + timedelta(hours=1), selected_end=utcnow() + timedelta(hours=2),
            carbon_intensity=200.0, carbon_emission=0.4, electricity_cost=0.5, reason="test decision",
            region_id="AU-SA-Small", currency="AUD", native_cost=0.62,
        )
        db.add(decision)
        db.commit()

        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title="fallback title", message="fallback message",
            tenant_id=alice.tenant_id, job_id=job.job_id, email_required=True,
        )
        subject, body = render_email(db, notif)
        assert "template-test-workload" in subject
        assert "AU-SA-Small" in body
        assert "AUD" in body
        assert "0.62" in body

    def test_render_email_falls_back_to_title_message_for_unmapped_event(self, db, two_users):
        from app.notify.templates import render_email
        alice = two_users["alice"]
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.JOB_SUBMITTED,
            category="WORKLOAD", severity="INFO", title="Fallback Title", message="Fallback message body.",
            tenant_id=alice.tenant_id, job_id="JOB-NO-TEMPLATE",
        )
        subject, body = render_email(db, notif)
        assert subject == "Fallback Title"
        assert body == "Fallback message body."

    def test_render_email_falls_back_when_job_no_longer_exists(self, db, two_users):
        from app.notify.templates import render_email
        alice = two_users["alice"]
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title="Fallback Title 2", message="Fallback message 2.",
            tenant_id=alice.tenant_id, job_id="JOB-DOES-NOT-EXIST",
        )
        subject, body = render_email(db, notif)
        assert subject == "Fallback Title 2"
        assert body == "Fallback message 2."


class TestEmailFailureAudit:
    def test_permanent_email_failure_records_audit_event(self, db, two_users):
        alice = two_users["alice"]
        from app.shared.config import settings
        from app.trust.ledger import get_events

        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.K8S_JOB_FAILED,
            category="EXECUTION", severity="CRITICAL", title="x", message="y",
            tenant_id=alice.tenant_id, job_id="JOB-EMAIL-AUDIT-1", email_required=True,
        )
        original_enabled = settings.smtp_enabled
        original_host = settings.smtp_host
        original_max = settings.notification_email_max_attempts
        settings.smtp_enabled = True
        settings.smtp_host = "smtp.invalid.example"
        settings.notification_email_max_attempts = 1
        try:
            with patch("app.notify.email.send_email", side_effect=RuntimeError("refused")):
                process_pending_emails(db, limit=10)
        finally:
            settings.smtp_enabled = original_enabled
            settings.smtp_host = original_host
            settings.notification_email_max_attempts = original_max

        db.refresh(notif)
        assert notif.email_status == "FAILED"

        events = get_events(db, job_id="JOB-EMAIL-AUDIT-1")
        assert any(e.event_type == EventType.EMAIL_DELIVERY_FAILED for e in events)


class TestNotificationsRBACDirectAPI:
    """Direct API-level RBAC probes for all three roles per the security
    requirements: never a client-supplied recipient, never cross-tenant
    leakage, regardless of role."""

    @pytest.fixture
    def three_roles(self, db):
        platform_admin = UserORM(
            username="notif_rbac_pa", email="rbac_pa@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.PLATFORM_ADMIN,
            tenant_id=None, is_active=True,
        )
        company_admin = UserORM(
            username="notif_rbac_ca", email="rbac_ca@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_ADMIN,
            tenant_id="tenant-rbac", is_active=True,
        )
        company_user = UserORM(
            username="notif_rbac_cu", email="rbac_cu@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_USER,
            tenant_id="tenant-rbac", is_active=True,
        )
        db.add_all([platform_admin, company_admin, company_user])
        db.commit()
        for u in (platform_admin, company_admin, company_user):
            db.refresh(u)
        return {"platform_admin": platform_admin, "company_admin": company_admin, "company_user": company_user}

    @pytest.mark.parametrize("role_key", ["platform_admin", "company_admin", "company_user"])
    def test_every_role_can_read_its_own_notifications_only(self, db, three_roles, role_key):
        user = three_roles[role_key]
        other_key = "company_user" if role_key != "company_user" else "platform_admin"
        other = three_roles[other_key]

        create_notification(
            db, recipient_user_id=user.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title=f"For {role_key}", message="m",
            tenant_id=user.tenant_id, job_id=f"JOB-RBAC-{role_key}",
        )
        create_notification(
            db, recipient_user_id=other.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title=f"For {other_key}", message="m",
            tenant_id=other.tenant_id, job_id=f"JOB-RBAC-{other_key}",
        )

        token = get_token(user)
        res = client.get("/notifications", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        titles = {n["title"] for n in res.json()}
        assert f"For {role_key}" in titles
        assert f"For {other_key}" not in titles

    def test_no_endpoint_accepts_a_recipient_query_param_override(self, db, three_roles):
        victim = three_roles["company_user"]
        attacker = three_roles["company_admin"]
        create_notification(
            db, recipient_user_id=victim.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title="Victim's notification", message="m",
            tenant_id=victim.tenant_id, job_id="JOB-RBAC-SMUGGLE",
        )
        token = get_token(attacker)
        res = client.get(
            "/notifications",
            headers={"Authorization": f"Bearer {token}"},
            params={"recipient_user_id": victim.id, "user_id": victim.id},
        )
        assert res.status_code == 200
        titles = {n["title"] for n in res.json()}
        assert "Victim's notification" not in titles

    def test_unauthenticated_request_rejected_for_every_endpoint(self, db):
        assert client.get("/notifications").status_code == 401
        assert client.get("/notifications/unread-count").status_code == 401
        assert client.patch("/notifications/1/read").status_code == 401
        assert client.patch("/notifications/read-all").status_code == 401
        assert client.get("/notifications/preferences").status_code == 401
        assert client.put("/notifications/preferences", json={}).status_code == 401
