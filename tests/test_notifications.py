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

import asyncio
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

    def test_cross_tenant_notification_recipient_injection_is_rejected(self, db, two_users):
        """Consistency & Security Hardening pass, Section 11 item 14: a user
        in tenant-b must never be able to receive, view, or act on a
        notification that legitimately belongs to a user in tenant-a, even
        with a spoofed tenant_id claim — recipient_user_id (not tenant_id)
        is the sole authorization key, and it is always server-derived from
        the authenticated caller, never accepted from the client."""
        alice, bob = two_users["alice"], two_users["bob"]
        assert alice.tenant_id != bob.tenant_id
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title="Tenant A Approved", message="msg",
            tenant_id=alice.tenant_id, job_id="JOB-CROSS-TENANT-1",
        )

        bob_token = get_token(bob)
        bob_headers = {"Authorization": f"Bearer {bob_token}"}

        # Bob (tenant-b) cannot see Alice's (tenant-a) notification in his own list.
        res_list = client.get("/notifications", headers=bob_headers)
        assert res_list.status_code == 200
        assert all(n["id"] != notif.id for n in res_list.json())

        # Bob cannot mark it read by guessing/forging its id.
        res_read = client.patch(f"/notifications/{notif.id}/read", headers=bob_headers)
        assert res_read.status_code == 404

        # Bob's unread count is unaffected by Alice's cross-tenant notification.
        res_count = client.get("/notifications/unread-count", headers=bob_headers)
        assert res_count.status_code == 200
        assert res_count.json()["unread_count"] == 0

        db.refresh(notif)
        assert notif.read_at is None

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

    def test_smtp_disabled_notification_still_works_in_app(self, db, two_users):
        """P0 Email Delivery Functionalization Pass: with SMTP disabled, the
        in-app notification (bell/toast/GET /notifications) must still be
        fully created and readable — only the email channel is gated."""
        alice = two_users["alice"]
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.K8S_JOB_FAILED,
            category="EXECUTION", severity="CRITICAL", title="Workload failed", message="It failed.",
            tenant_id=alice.tenant_id, job_id="JOB-INAPP-NOSMTP", email_required=True,
        )
        assert notif is not None
        assert notif.title == "Workload failed"
        fetched = get_notifications(db, recipient_user_id=alice.id)
        assert any(n.id == notif.id for n in fetched)

    def test_successful_delivery_marks_sent_and_records_timestamp(self, db, two_users):
        """P0 Email Delivery Functionalization Pass: with SMTP enabled/configured
        and a mocked transport that succeeds, process_pending_emails() must
        mark the notification SENT with a populated email_sent_at and exactly
        one recorded attempt — proving the PENDING -> SENT transition the
        real end-to-end flow relies on, without a real SMTP server."""
        alice = two_users["alice"]
        job = JobORM(
            job_id="JOB-EMAIL-SENT", team_id="team-x", tenant_id=alice.tenant_id,
            submitted_by_user_id=alice.id, submitted_at=utcnow(),
            deadline=utcnow() + timedelta(hours=2), runtime_minutes=10, power_kw=1.0,
            region="IN-TG", container_image="greenshift/sample:v1", status=JobStatus.SUBMITTED,
        )
        db.add(job)
        db.commit()

        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.JOB_SUBMITTED,
            category="WORKLOAD", severity="INFO", title="Workload submitted", message="fallback",
            tenant_id=alice.tenant_id, job_id=job.job_id, email_required=True,
        )
        assert notif.email_status == "PENDING"

        from app.shared.config import settings
        original_enabled, original_host = settings.smtp_enabled, settings.smtp_host
        settings.smtp_enabled = True
        settings.smtp_host = "smtp.example.com"
        try:
            with patch("app.notify.email.send_email", return_value=None) as mock_send:
                process_pending_emails(db, limit=10)
        finally:
            settings.smtp_enabled, settings.smtp_host = original_enabled, original_host

        db.refresh(notif)
        assert mock_send.called
        # The real recipient address was used — not a client-suppliable value.
        assert mock_send.call_args.args[0] == alice.email
        assert notif.email_status == "SENT"
        assert notif.email_attempts == 1
        assert notif.email_sent_at is not None
        assert notif.last_error is None
        # SMTP success must never touch the job's own business state.
        db.refresh(job)
        assert job.status == JobStatus.SUBMITTED

    def test_missing_recipient_email_is_handled_safely(self, db, two_users):
        """A recipient row with no email on file (blank string — UserORM.email
        is NOT NULL but not otherwise validated) must fail the email channel
        cleanly, without crashing the processor or touching job state."""
        alice = two_users["alice"]
        alice.email = ""
        db.commit()

        job = JobORM(
            job_id="JOB-NO-EMAIL", team_id="team-x", tenant_id=alice.tenant_id,
            submitted_by_user_id=alice.id, submitted_at=utcnow(),
            deadline=utcnow() + timedelta(hours=2), runtime_minutes=10, power_kw=1.0,
            region="IN-TG", container_image="greenshift/sample:v1", status=JobStatus.SUBMITTED,
        )
        db.add(job)
        db.commit()

        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.JOB_SUBMITTED,
            category="WORKLOAD", severity="INFO", title="Workload submitted", message="fallback",
            tenant_id=alice.tenant_id, job_id=job.job_id, email_required=True,
        )

        from app.shared.config import settings
        original_enabled, original_host = settings.smtp_enabled, settings.smtp_host
        settings.smtp_enabled = True
        settings.smtp_host = "smtp.example.com"
        try:
            with patch("app.notify.email.send_email") as mock_send:
                process_pending_emails(db, limit=10)
        finally:
            settings.smtp_enabled, settings.smtp_host = original_enabled, original_host

        db.refresh(notif)
        db.refresh(job)
        assert not mock_send.called
        assert notif.email_status == "FAILED"
        assert "no email" in (notif.last_error or "").lower()
        assert job.status == JobStatus.SUBMITTED


class TestCrossTenantRecipientDeliverySafety:
    """P0 Email Delivery Functionalization Pass: the actual SMTP send target
    is always resolved from the notification's own recipient_user_id — never
    something a client, or a different tenant's data, could influence."""

    def test_company_a_notification_is_never_delivered_to_company_b_recipient(self, db, two_users):
        alice, bob = two_users["alice"], two_users["bob"]  # tenant-a, tenant-b respectively
        job_a = JobORM(
            job_id="JOB-TENANT-A-MAIL", team_id="team-a", tenant_id=alice.tenant_id,
            submitted_by_user_id=alice.id, submitted_at=utcnow(),
            deadline=utcnow() + timedelta(hours=2), runtime_minutes=10, power_kw=1.0,
            region="IN-TG", container_image="greenshift/sample:v1", status=JobStatus.SUBMITTED,
        )
        db.add(job_a)
        db.commit()

        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.JOB_SUBMITTED,
            category="WORKLOAD", severity="INFO", title="Workload submitted", message="fallback",
            tenant_id=alice.tenant_id, job_id=job_a.job_id, email_required=True,
        )

        from app.shared.config import settings
        original_enabled, original_host = settings.smtp_enabled, settings.smtp_host
        settings.smtp_enabled = True
        settings.smtp_host = "smtp.example.com"
        try:
            with patch("app.notify.email.send_email", return_value=None) as mock_send:
                process_pending_emails(db, limit=10)
        finally:
            settings.smtp_enabled, settings.smtp_host = original_enabled, original_host

        db.refresh(notif)
        assert notif.email_status == "SENT"
        assert mock_send.call_count == 1
        sent_to = mock_send.call_args.args[0]
        assert sent_to == alice.email
        assert sent_to != bob.email


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
        job = JobORM(
            job_id="JOB-NO-TEMPLATE", team_id="team-x", tenant_id=alice.tenant_id,
            submitted_by_user_id=alice.id, submitted_at=utcnow(), deadline=utcnow() + timedelta(hours=6),
            runtime_minutes=30, power_kw=2.0, region="IN-TG",
            container_image="greenshift/sample-workload:latest", status=JobStatus.SUBMITTED,
        )
        db.add(job)
        db.commit()
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.BUDGET_UPDATED,
            category="WORKLOAD", severity="INFO", title="Fallback Title", message="Fallback message body.",
            tenant_id=alice.tenant_id, job_id="JOB-NO-TEMPLATE",
        )
        subject, body = render_email(db, notif)
        assert subject == "Fallback Title"
        assert body == "Fallback message body."

    def test_job_submitted_template_includes_real_job_content(self, db, two_users):
        from app.notify.templates import render_email
        alice = two_users["alice"]
        job = JobORM(
            job_id="JOB-SUBMIT-TEMPLATE-1", team_id="team-x", tenant_id=alice.tenant_id,
            submitted_by_user_id=alice.id, submitted_at=utcnow(), deadline=utcnow() + timedelta(hours=6),
            runtime_minutes=30, power_kw=2.0, region="IN-TG", job_type="DATA_PROCESSING",
            container_image="greenshift/sample-workload:latest", status=JobStatus.SUBMITTED,
        )
        db.add(job)
        db.commit()
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.JOB_SUBMITTED,
            category="WORKLOAD", severity="INFO", title="fallback", message="fallback",
            tenant_id=alice.tenant_id, job_id="JOB-SUBMIT-TEMPLATE-1",
        )
        subject, body = render_email(db, notif)
        assert subject == "GreenShift: Workload Submitted — JOB-SUBMIT-TEMPLATE-1"
        assert "DATA_PROCESSING" in body
        assert "IN-TG" in body

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
        assert client.get("/notifications/stream").status_code == 401

    def test_forged_recipient_and_role_fields_in_preference_update_are_ignored(self, db, two_users):
        """A crafted body carrying recipient_user_id/email/role/team_id must
        have zero effect — PUT /notifications/preferences only ever accepts
        the four editable boolean fields, and only ever writes the caller's
        own row (current_user.id), never a client-supplied identity."""
        alice, bob = two_users["alice"], two_users["bob"]
        token = get_token(alice)
        res = client.put(
            "/notifications/preferences",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email_approval": False,
                "recipient_user_id": bob.id,
                "user_id": bob.id,
                "email": "attacker@example.com",
                "role": "PLATFORM_ADMIN",
                "team_id": "another-team",
                "tenant_id": "another-tenant",
            },
        )
        assert res.status_code == 200
        assert res.json()["email_approval"] is False

        # Bob's own preferences are completely untouched by Alice's forged payload.
        bob_token = get_token(bob)
        res_bob = client.get("/notifications/preferences", headers={"Authorization": f"Bearer {bob_token}"})
        assert res_bob.json()["email_approval"] is True


class TestRealtimePublish:
    """create_notification() best-effort pushes a real-time event over
    app.notify.realtime.publish_notification_event — never blocks, never
    raises, and degrades silently when the transport is unavailable."""

    def test_create_notification_publishes_a_realtime_event(self, db, two_users):
        alice = two_users["alice"]
        with patch("app.notify.realtime.publish_notification_event") as mock_publish:
            notif = create_notification(
                db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_GRANTED,
                category="APPROVAL", severity="INFO", title="Approved", message="m",
                tenant_id=alice.tenant_id, job_id="JOB-RT-1",
            )
        assert notif is not None
        mock_publish.assert_called_once()
        called_user_id, called_payload = mock_publish.call_args[0]
        assert called_user_id == alice.id
        assert called_payload["id"] == notif.id
        assert called_payload["title"] == "Approved"

    def test_no_realtime_publish_for_a_deduplicated_notification(self, db, two_users):
        alice = two_users["alice"]
        kwargs = dict(
            recipient_user_id=alice.id, event_type=EventType.K8S_JOB_FAILED,
            category="EXECUTION", severity="CRITICAL", title="Failed", message="m",
            tenant_id=alice.tenant_id, job_id="JOB-RT-DUP",
        )
        create_notification(db, **kwargs)
        with patch("app.notify.realtime.publish_notification_event") as mock_publish:
            second = create_notification(db, **kwargs)
        assert second is None
        mock_publish.assert_not_called()

    def test_create_notification_succeeds_even_if_realtime_publish_raises(self, db, two_users):
        """The publish step must never break the notification's own
        creation/commit — a bug or outage in the realtime transport is
        strictly additive-path, never a dependency."""
        alice = two_users["alice"]
        with patch("app.notify.realtime.publish_notification_event", side_effect=RuntimeError("redis down")):
            notif = create_notification(
                db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_GRANTED,
                category="APPROVAL", severity="INFO", title="Approved", message="m",
                tenant_id=alice.tenant_id, job_id="JOB-RT-2",
            )
        assert notif is not None
        assert notif.id is not None

    def test_publish_notification_event_is_a_noop_when_redis_unavailable(self, db, two_users):
        from app.notify.realtime import publish_notification_event
        with patch("app.notify.realtime.get_redis_client", return_value=None):
            # Must not raise even though there is nothing to publish to.
            publish_notification_event(1, {"id": 1, "title": "x"})


class TestActionUrlDefaults:
    """action_url is always server-derived from real, existing frontend
    routes — never invented, never a client-supplied value."""

    def test_approval_category_gets_the_approvals_route(self, db, two_users):
        alice = two_users["alice"]
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.SCHEDULE_PROPOSED,
            category="APPROVAL", severity="INFO", title="Approval required", message="m",
            tenant_id=alice.tenant_id, job_id="JOB-URL-1",
        )
        assert notif.action_url == "/approvals"

    def test_job_scoped_category_gets_the_workload_detail_route(self, db, two_users):
        alice = two_users["alice"]
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.K8S_JOB_COMPLETED,
            category="EXECUTION", severity="INFO", title="Completed", message="m",
            tenant_id=alice.tenant_id, job_id="JOB-URL-2",
        )
        assert notif.action_url == "/workloads/JOB-URL-2"

    def test_no_job_id_and_non_approval_category_gets_no_action_url(self, db, two_users):
        alice = two_users["alice"]
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.AUTH_USER_ACTIVATED,
            category="ACCOUNT", severity="INFO", title="Account activated", message="m",
            tenant_id=alice.tenant_id,
        )
        assert notif.action_url is None

    def test_explicit_action_url_is_never_overridden(self, db, two_users):
        alice = two_users["alice"]
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.K8S_JOB_COMPLETED,
            category="EXECUTION", severity="INFO", title="Completed", message="m",
            tenant_id=alice.tenant_id, job_id="JOB-URL-3", action_url="/custom/path",
        )
        assert notif.action_url == "/custom/path"

    def test_resolved_approval_outcomes_route_to_the_workload_not_the_approvals_queue(self, db, two_users):
        """Once a schedule is APPROVED or DECLINED it's no longer in the
        approvals queue, and the submitter (often a plain COMPANY_USER) may
        not even be an approver — the workload's own detail page is the
        correct destination, not /approvals."""
        alice = two_users["alice"]
        granted = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title="Approved", message="m",
            tenant_id=alice.tenant_id, job_id="JOB-URL-4",
        )
        declined = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_DECLINED,
            category="APPROVAL", severity="WARNING", title="Declined", message="m",
            tenant_id=alice.tenant_id, job_id="JOB-URL-5",
        )
        assert granted.action_url == "/workloads/JOB-URL-4"
        assert declined.action_url == "/workloads/JOB-URL-5"


class TestAdminFanoutOnFailureAndCancellation:
    """Failures/cancellations that need operator attention must reach the
    responsible Company Admin(s), not just the submitter — while staying
    strictly scoped to the job's own tenant."""

    @pytest.fixture
    def tenant_with_admin(self, db):
        admin = UserORM(
            username="notif_fanout_admin", email="fanout_admin@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_ADMIN,
            tenant_id="tenant-fanout", is_active=True,
        )
        other_tenant_admin = UserORM(
            username="notif_fanout_other_admin", email="fanout_other@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_ADMIN,
            tenant_id="tenant-fanout-other", is_active=True,
        )
        submitter = UserORM(
            username="notif_fanout_user", email="fanout_user@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_USER,
            tenant_id="tenant-fanout", team_id="team-fanout", is_active=True,
        )
        db.add_all([admin, other_tenant_admin, submitter])
        db.commit()
        for u in (admin, other_tenant_admin, submitter):
            db.refresh(u)
        return {"admin": admin, "other_tenant_admin": other_tenant_admin, "submitter": submitter}

    def test_scheduling_failure_notifies_tenant_admin_not_other_tenant(self, db, tenant_with_admin):
        from app.decide.service import process_pending_jobs
        from app.shared.models import JobSubmitRequest
        from app.ingest.jobs import submit_job

        submitter = tenant_with_admin["submitter"]
        req = JobSubmitRequest(
            job_id="JOB-FANOUT-SCHEDFAIL-1", team_id="team-fanout",
            deadline=utcnow() + timedelta(hours=12), runtime_minutes=60, power_kw=0.5,
            region="IN-WE", container_image="greenshift/sample-workload:latest",
            carbon_budget_kg=0.000001,
        )
        submit_job(db, req, tenant_id="tenant-fanout", submitted_by_user_id=submitter.id)
        process_pending_jobs(db)

        notifs = (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == "JOB-FANOUT-SCHEDFAIL-1", NotificationORM.event_type == EventType.SCHEDULING_FAILED)
            .all()
        )
        recipient_ids = {n.recipient_user_id for n in notifs}
        assert tenant_with_admin["admin"].id in recipient_ids
        assert submitter.id in recipient_ids
        assert tenant_with_admin["other_tenant_admin"].id not in recipient_ids

    def test_execution_failure_notifies_tenant_admin(self, db, tenant_with_admin):
        """Exercises the real app.dispatch.dispatcher.refresh_job_status()
        FAILED-transition branch (mocked at the same k8s-client seam as
        tests/test_dispatch_k8s.py::test_refresh_status_synchronizes_to_job_orm)
        end-to-end, so this verifies the actual production fan-out code —
        not a re-implementation of it in the test."""
        from unittest.mock import MagicMock
        from app.dispatch.dispatcher import refresh_job_status
        from app.shared.models import KubernetesExecutionORM

        submitter = tenant_with_admin["submitter"]
        now = utcnow()
        job = JobORM(
            job_id="JOB-FANOUT-EXECFAIL-1", team_id="team-fanout", tenant_id="tenant-fanout",
            submitted_by_user_id=submitter.id, submitted_at=now, deadline=now + timedelta(hours=12),
            runtime_minutes=30, power_kw=1.0, region="IN-TG",
            container_image="greenshift/sample-workload:latest", status=JobStatus.RUNNING,
        )
        execution = KubernetesExecutionORM(
            job_id="JOB-FANOUT-EXECFAIL-1", kubernetes_job_name="gs-job-fanout-execfail-1",
            kubernetes_namespace="greenshift", planned_start=now, planned_end=now + timedelta(minutes=30),
            gs_status=JobStatus.RUNNING, pod_name="gs-job-fanout-execfail-1-pod", created_at=now,
        )
        job.kubernetes_execution = execution
        db.add(job)
        db.commit()

        mock_batch = MagicMock()
        mock_core = MagicMock()
        with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch), \
             patch("app.dispatch.dispatcher.get_core_v1", return_value=mock_core), \
             patch("app.dispatch.dispatcher.get_job_status", return_value=("Failed", JobStatus.FAILED)), \
             patch("app.dispatch.dispatcher.get_pod_start_time", return_value=now), \
             patch("app.dispatch.dispatcher.get_job_completion_time", return_value=now + timedelta(minutes=5)):
            updated = refresh_job_status(db, execution)

        assert updated.gs_status == JobStatus.FAILED

        notifs = (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == "JOB-FANOUT-EXECFAIL-1", NotificationORM.event_type == EventType.K8S_JOB_FAILED)
            .all()
        )
        recipient_ids = {n.recipient_user_id for n in notifs}
        assert submitter.id in recipient_ids
        assert tenant_with_admin["admin"].id in recipient_ids
        assert tenant_with_admin["other_tenant_admin"].id not in recipient_ids

    def test_cancellation_notifies_admin_only_when_operationally_significant(self, db, tenant_with_admin):
        from app.shared.models import JobSubmitRequest
        from app.ingest.jobs import submit_job

        submitter = tenant_with_admin["submitter"]
        token = get_token(submitter)

        # SUBMITTED (not yet significant) -> cancel -> no admin fan-out expected.
        req = JobSubmitRequest(
            job_id="JOB-FANOUT-CANCEL-1", team_id="team-fanout",
            deadline=utcnow() + timedelta(hours=12), runtime_minutes=30, power_kw=1.0,
            region="IN-TG", container_image="greenshift/sample-workload:latest",
        )
        submit_job(db, req, tenant_id="tenant-fanout", submitted_by_user_id=submitter.id)
        res = client.post("/jobs/JOB-FANOUT-CANCEL-1/cancel", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200

        admin_notifs = (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == "JOB-FANOUT-CANCEL-1", NotificationORM.recipient_user_id == tenant_with_admin["admin"].id)
            .all()
        )
        assert admin_notifs == []

        # PENDING_APPROVAL (significant) -> cancel -> admin IS notified.
        req2 = JobSubmitRequest(
            job_id="JOB-FANOUT-CANCEL-2", team_id="team-fanout",
            deadline=utcnow() + timedelta(hours=12), runtime_minutes=30, power_kw=1.0,
            region="IN-TG", container_image="greenshift/sample-workload:latest", deferrable=True,
        )
        job2 = submit_job(db, req2, tenant_id="tenant-fanout", submitted_by_user_id=submitter.id)
        job2.status = JobStatus.PENDING_APPROVAL
        db.commit()
        res2 = client.post("/jobs/JOB-FANOUT-CANCEL-2/cancel", headers={"Authorization": f"Bearer {token}"})
        assert res2.status_code == 200

        admin_notifs2 = (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == "JOB-FANOUT-CANCEL-2", NotificationORM.recipient_user_id == tenant_with_admin["admin"].id)
            .all()
        )
        assert len(admin_notifs2) == 1
        assert admin_notifs2[0].dedup_key.endswith(":admin")


class TestPlatformAdminCriticalEscalation:
    """Platform Admin is the platform's universal escalation authority for
    CRITICAL events (SCHEDULING_FAILED, K8S_JOB_FAILED — both unconditionally
    CRITICAL by construction, matching Platform Admin's documented scope of
    'critical execution/system failures'). It must NOT be cc'd on ordinary,
    non-critical events — that would be 'emailing every role for every
    event', which the spec explicitly forbids."""

    @pytest.fixture
    def platform_and_tenant(self, db):
        platform_admin = UserORM(
            username="notif_pa_escalation", email="pa_escalation@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.PLATFORM_ADMIN,
            tenant_id=None, is_active=True,
        )
        tenant_admin = UserORM(
            username="notif_ta_escalation", email="ta_escalation@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_ADMIN,
            tenant_id="tenant-escalation", is_active=True,
        )
        submitter = UserORM(
            username="notif_sub_escalation", email="sub_escalation@greenshift.io",
            hashed_password=hash_password("pass12345"), role=UserRole.COMPANY_USER,
            tenant_id="tenant-escalation", is_active=True,
        )
        db.add_all([platform_admin, tenant_admin, submitter])
        db.commit()
        for u in (platform_admin, tenant_admin, submitter):
            db.refresh(u)
        return {"platform_admin": platform_admin, "tenant_admin": tenant_admin, "submitter": submitter}

    def test_scheduling_failed_reaches_platform_admin(self, db, platform_and_tenant):
        from app.decide.service import process_pending_jobs
        from app.shared.models import JobSubmitRequest
        from app.ingest.jobs import submit_job

        submitter = platform_and_tenant["submitter"]
        req = JobSubmitRequest(
            job_id="JOB-PA-ESCALATION-1", team_id="team-escalation",
            deadline=utcnow() + timedelta(hours=12), runtime_minutes=60, power_kw=0.5,
            region="IN-WE", container_image="greenshift/sample-workload:latest",
            carbon_budget_kg=0.000001,
        )
        submit_job(db, req, tenant_id="tenant-escalation", submitted_by_user_id=submitter.id)
        process_pending_jobs(db)

        notifs = (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == "JOB-PA-ESCALATION-1", NotificationORM.event_type == EventType.SCHEDULING_FAILED)
            .all()
        )
        recipient_ids = {n.recipient_user_id for n in notifs}
        assert platform_and_tenant["platform_admin"].id in recipient_ids
        assert platform_and_tenant["tenant_admin"].id in recipient_ids

    def test_execution_failed_reaches_platform_admin(self, db, platform_and_tenant):
        from unittest.mock import MagicMock
        from app.dispatch.dispatcher import refresh_job_status
        from app.shared.models import KubernetesExecutionORM

        submitter = platform_and_tenant["submitter"]
        now = utcnow()
        job = JobORM(
            job_id="JOB-PA-ESCALATION-2", team_id="team-escalation", tenant_id="tenant-escalation",
            submitted_by_user_id=submitter.id, submitted_at=now, deadline=now + timedelta(hours=12),
            runtime_minutes=30, power_kw=1.0, region="IN-TG",
            container_image="greenshift/sample-workload:latest", status=JobStatus.RUNNING,
        )
        execution = KubernetesExecutionORM(
            job_id="JOB-PA-ESCALATION-2", kubernetes_job_name="gs-job-pa-escalation-2",
            kubernetes_namespace="greenshift", planned_start=now, planned_end=now + timedelta(minutes=30),
            gs_status=JobStatus.RUNNING, pod_name="gs-job-pa-escalation-2-pod", created_at=now,
        )
        job.kubernetes_execution = execution
        db.add(job)
        db.commit()

        mock_batch, mock_core = MagicMock(), MagicMock()
        with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch), \
             patch("app.dispatch.dispatcher.get_core_v1", return_value=mock_core), \
             patch("app.dispatch.dispatcher.get_job_status", return_value=("Failed", JobStatus.FAILED)), \
             patch("app.dispatch.dispatcher.get_pod_start_time", return_value=now), \
             patch("app.dispatch.dispatcher.get_job_completion_time", return_value=now + timedelta(minutes=5)):
            refresh_job_status(db, execution)

        notifs = (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == "JOB-PA-ESCALATION-2", NotificationORM.event_type == EventType.K8S_JOB_FAILED)
            .all()
        )
        recipient_ids = {n.recipient_user_id for n in notifs}
        assert platform_and_tenant["platform_admin"].id in recipient_ids

    def test_platform_admin_not_notified_for_non_critical_approval_granted(self, db, platform_and_tenant):
        """Confirms escalation is scoped to CRITICAL events only — Platform
        Admin is not cc'd on routine approval-granted notifications."""
        submitter = platform_and_tenant["submitter"]
        create_notification(
            db, recipient_user_id=submitter.id, event_type=EventType.APPROVAL_GRANTED,
            category="APPROVAL", severity="INFO", title="Approved", message="m",
            tenant_id="tenant-escalation", job_id="JOB-PA-ESCALATION-3",
        )
        notifs = (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == "JOB-PA-ESCALATION-3")
            .all()
        )
        recipient_ids = {n.recipient_user_id for n in notifs}
        assert platform_and_tenant["platform_admin"].id not in recipient_ids


class TestEmailUrgencySubjects:
    """Subject lines use the LOW/MEDIUM/HIGH/CRITICAL severity scheme —
    only HIGH/CRITICAL are bracketed, matching the exact format:
    "[SEVERITY] GreenShift: Title — Workload"."""

    def _job(self, db, tenant_id, job_id, status=JobStatus.FAILED):
        job = JobORM(
            job_id=job_id, team_id="team-x", tenant_id=tenant_id,
            submitted_by_user_id=None, submitted_at=utcnow(), deadline=utcnow() + timedelta(hours=6),
            runtime_minutes=30, power_kw=2.0, region="IN-TG",
            container_image="greenshift/sample-workload:latest", status=status,
            workload_name="urgency-test-workload",
        )
        db.add(job)
        db.commit()
        return job

    def test_job_submitted_subject_is_low_no_bracket(self, db, two_users):
        from app.notify.templates import render_email
        alice = two_users["alice"]
        self._job(db, alice.tenant_id, "JOB-URGENCY-0", status=JobStatus.SUBMITTED)
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.JOB_SUBMITTED,
            category="WORKLOAD", severity="INFO", title="fallback", message="fallback",
            tenant_id=alice.tenant_id, job_id="JOB-URGENCY-0",
        )
        subject, _ = render_email(db, notif)
        assert subject.startswith("GreenShift: Workload Submitted")
        assert "[" not in subject

    def test_scheduling_failed_subject_is_bracketed_critical(self, db, two_users):
        """Per spec section 5, Scheduling Failed is CRITICAL (not HIGH) —
        it is unconditionally CRITICAL in this system by construction."""
        from app.notify.templates import render_email
        alice = two_users["alice"]
        self._job(db, alice.tenant_id, "JOB-URGENCY-1")
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.SCHEDULING_FAILED,
            category="SCHEDULING", severity="CRITICAL", title="fallback", message="fallback",
            tenant_id=alice.tenant_id, job_id="JOB-URGENCY-1",
        )
        subject, _ = render_email(db, notif)
        assert subject == "[CRITICAL] GreenShift: Scheduling Failed — urgency-test-workload"

    def test_execution_failed_subject_is_bracketed_critical(self, db, two_users):
        from app.notify.templates import render_email
        alice = two_users["alice"]
        self._job(db, alice.tenant_id, "JOB-URGENCY-2")
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.K8S_JOB_FAILED,
            category="EXECUTION", severity="CRITICAL", title="fallback", message="fallback",
            tenant_id=alice.tenant_id, job_id="JOB-URGENCY-2",
        )
        subject, _ = render_email(db, notif)
        assert subject == "[CRITICAL] GreenShift: Workload Execution Failed — urgency-test-workload"

    def test_approval_required_subject_is_bracketed_high(self, db, two_users):
        """Per spec section 5's literal example: "[HIGH] GreenShift: Approval
        Required — JOB-123" — Approval Required IS bracketed (a change from
        treating it as an unbracketed call-to-action)."""
        from app.notify.templates import render_email
        alice = two_users["alice"]
        self._job(db, alice.tenant_id, "JOB-URGENCY-3", status=JobStatus.PENDING_APPROVAL)
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.SCHEDULE_PROPOSED,
            category="APPROVAL", severity="INFO", title="fallback", message="fallback",
            tenant_id=alice.tenant_id, job_id="JOB-URGENCY-3",
        )
        subject, _ = render_email(db, notif)
        assert subject == "[HIGH] GreenShift: Approval Required — urgency-test-workload"

    def test_schedule_proposed_submitter_subject_is_medium_no_bracket(self, db, two_users):
        from app.notify.templates import render_email
        alice = two_users["alice"]
        self._job(db, alice.tenant_id, "JOB-URGENCY-3b", status=JobStatus.PENDING_APPROVAL)
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.SCHEDULE_PROPOSED,
            category="SCHEDULING", severity="INFO", title="fallback", message="fallback",
            tenant_id=alice.tenant_id, job_id="JOB-URGENCY-3b",
        )
        subject, _ = render_email(db, notif)
        assert subject == "GreenShift: Schedule Proposed — urgency-test-workload"
        assert "[" not in subject

    def test_workload_scheduled_subject_is_low_no_bracket(self, db, two_users):
        from app.notify.templates import render_email
        alice = two_users["alice"]
        self._job(db, alice.tenant_id, "JOB-URGENCY-4", status=JobStatus.APPROVED)
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.JOB_SCHEDULED,
            category="WORKLOAD", severity="INFO", title="fallback", message="fallback",
            tenant_id=alice.tenant_id, job_id="JOB-URGENCY-4",
        )
        subject, _ = render_email(db, notif)
        assert subject == "GreenShift: Workload Scheduled — urgency-test-workload"

    def test_schedule_declined_includes_real_reason_and_approver(self, db, two_users):
        from app.notify.templates import render_email
        from app.shared.models import ApprovalORM, ScheduleDecisionORM
        alice = two_users["alice"]
        job = self._job(db, alice.tenant_id, "JOB-URGENCY-5", status=JobStatus.DECLINED)
        decision = ScheduleDecisionORM(
            job_id=job.job_id, selected_start=utcnow(), selected_end=utcnow() + timedelta(minutes=30),
            carbon_intensity=200.0, carbon_emission=0.1, electricity_cost=0.05, reason="test",
            region_id=job.region, currency="INR", native_cost=4.0,
        )
        db.add(decision)
        db.commit()
        approval = ApprovalORM(
            job_id=job.job_id, schedule_decision_id=decision.id, decision="DECLINED",
            reason="Carbon budget exceeded for this window", approved_by="company_admin_x",
        )
        db.add(approval)
        db.commit()

        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.APPROVAL_DECLINED,
            category="APPROVAL", severity="WARNING", title="fallback", message="fallback",
            tenant_id=alice.tenant_id, job_id=job.job_id,
        )
        subject, body = render_email(db, notif)
        assert subject == "[HIGH] GreenShift: Schedule Declined — urgency-test-workload"
        assert "Carbon budget exceeded for this window" in body
        assert "company_admin_x" in body

    def test_no_value_is_ever_fabricated_missing_fields_say_not_available(self, db, two_users):
        """Spec section 6: unavailable values must read 'Not available',
        never a fabricated number/date/currency. carbon_budget_kg is
        genuinely optional (nullable) on JobORM — deadline is NOT NULL at
        the schema level, so a job can never actually exist without one;
        this exercises the one field that legitimately can be missing."""
        from app.notify.templates import render_email
        alice = two_users["alice"]
        job = JobORM(
            job_id="JOB-URGENCY-6", team_id="team-x", tenant_id=alice.tenant_id,
            submitted_by_user_id=None, submitted_at=utcnow(), deadline=utcnow() + timedelta(hours=6),
            runtime_minutes=30, power_kw=2.0, region="IN-TG",
            container_image="greenshift/sample-workload:latest", status=JobStatus.FAILED,
            carbon_budget_kg=None,
        )
        db.add(job)
        db.commit()
        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.SCHEDULING_FAILED,
            category="SCHEDULING", severity="CRITICAL", title="fallback", message="fallback",
            tenant_id=alice.tenant_id, job_id="JOB-URGENCY-6",
        )
        _, body = render_email(db, notif)
        assert "Carbon budget: Not available" in body


class TestNotificationStreamEndpoint:
    """GET /notifications/stream — authenticated SSE. The endpoint itself
    only needs an auth smoke test over HTTP (its generator runs forever by
    design, which a synchronous TestClient can't safely iterate); the
    generator's actual framing/degradation logic is tested directly as an
    async generator below, and per-user channel isolation is covered by
    TestRealtimePublish (publish_notification_event only ever targets the
    one recipient_user_id passed to it)."""

    def test_stream_requires_authentication(self, db):
        res = client.get("/notifications/stream")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_generator_yields_connected_frame_with_realtime_true_when_redis_available(self, db):
        from app.notify.realtime import notification_event_stream
        gen = notification_event_stream(user_id=999999)
        first = await gen.__anext__()
        assert first == 'event: connected\ndata: {"realtime": true}\n\n'
        await gen.aclose()

    @pytest.mark.asyncio
    async def test_generator_degrades_to_realtime_false_when_redis_unavailable(self, db):
        from app.notify import realtime
        with patch.object(realtime, "get_redis_client", return_value=None):
            gen = realtime.notification_event_stream(user_id=999999)
            first = await gen.__anext__()
            assert first == 'event: connected\ndata: {"realtime": false}\n\n'
            await gen.aclose()

    @pytest.mark.asyncio
    async def test_generator_delivers_a_published_event_to_only_its_own_channel(self, db, two_users):
        from app.notify.realtime import notification_event_stream, publish_notification_event
        alice, bob = two_users["alice"], two_users["bob"]

        alice_gen = notification_event_stream(user_id=alice.id)
        await alice_gen.__anext__()  # consume the "connected" frame

        publish_notification_event(bob.id, {"id": 1, "title": "for bob"})
        publish_notification_event(alice.id, {"id": 2, "title": "for alice"})

        frame = await asyncio.wait_for(alice_gen.__anext__(), timeout=5.0)
        assert "for alice" in frame
        assert "for bob" not in frame
        await alice_gen.aclose()


class TestEmailContentIsolationAcrossTenants:
    """Email Consistency & Security Hardening Pass: with two tenants' jobs
    persisted simultaneously (not just one tenant per test, as elsewhere in
    this file), confirm render_email() for one tenant's notification never
    includes the other tenant's workload name, job id, or cost — closing the
    literal "email content cannot contain another tenant's data" requirement
    with a genuine multi-tenant-contention test, not just single-tenant
    template-correctness tests."""

    def test_render_email_for_one_tenant_never_leaks_the_others_job_data(self, db, two_users):
        from app.notify.templates import render_email

        alice, bob = two_users["alice"], two_users["bob"]
        # Captured as plain values up front — create_notification() commits
        # internally (once per recipient), which expires every ORM instance
        # in the session; re-touching alice/bob's attributes afterward would
        # force an unrelated mid-test reload, so route through plain ids/
        # strings instead of the ORM objects from here on.
        alice_id, alice_tenant_id = alice.id, alice.tenant_id
        bob_id, bob_tenant_id = bob.id, bob.tenant_id
        job_a_id, job_b_id = "JOB-ISO-TENANT-A", "JOB-ISO-TENANT-B"

        job_a = JobORM(
            job_id=job_a_id, team_id="team-a", tenant_id=alice_tenant_id,
            submitted_by_user_id=alice_id, submitted_at=utcnow(),
            deadline=utcnow() + timedelta(hours=2), runtime_minutes=15, power_kw=2.0,
            region="IN-TG", container_image="greenshift/sample:v1",
            status=JobStatus.PENDING_APPROVAL, workload_name="Tenant-A Confidential Forecast Job",
            job_type="DATA_PROCESSING",
        )
        job_b = JobORM(
            job_id=job_b_id, team_id="team-b", tenant_id=bob_tenant_id,
            submitted_by_user_id=bob_id, submitted_at=utcnow(),
            deadline=utcnow() + timedelta(hours=2), runtime_minutes=15, power_kw=2.0,
            region="AU-SA-Small", container_image="greenshift/sample:v1",
            status=JobStatus.PENDING_APPROVAL, workload_name="Tenant-B Payroll Batch Job",
            job_type="ETL",
        )
        db.add_all([job_a, job_b])
        db.commit()

        notif_a = create_notification(
            db, recipient_user_id=alice_id, event_type=EventType.JOB_SUBMITTED,
            category="WORKLOAD", severity="INFO", title="Workload submitted", message="fallback",
            tenant_id=alice_tenant_id, job_id=job_a_id, email_required=True,
        )
        notif_b = create_notification(
            db, recipient_user_id=bob_id, event_type=EventType.JOB_SUBMITTED,
            category="WORKLOAD", severity="INFO", title="Workload submitted", message="fallback",
            tenant_id=bob_tenant_id, job_id=job_b_id, email_required=True,
        )

        _, body_a = render_email(db, notif_a)
        _, body_b = render_email(db, notif_b)

        assert "Tenant-A Confidential Forecast Job" in body_a
        assert job_a_id in body_a
        assert "Tenant-B Payroll Batch Job" not in body_a
        assert job_b_id not in body_a

        assert "Tenant-B Payroll Batch Job" in body_b
        assert job_b_id in body_b
        assert "Tenant-A Confidential Forecast Job" not in body_b
        assert job_a_id not in body_b


class TestUnauthorizedEmailTriggeringActionRejected:
    """An approval decision fans out an APPROVAL_GRANTED/DECLINED email-eligible
    notification (app.approval.service) — that trigger path must require the
    same authentication as the underlying business action, and a rejected,
    unauthenticated attempt must leave zero trace (no ApprovalORM row, no
    notification, no job status change)."""

    def test_unauthenticated_approve_request_is_rejected_and_creates_no_notification(self, db, two_users):
        from app.shared.models import ApprovalORM, ScheduleDecisionORM

        alice = two_users["alice"]
        job = JobORM(
            job_id="JOB-UNAUTH-APPROVE", team_id="team-a", tenant_id=alice.tenant_id,
            submitted_by_user_id=alice.id, submitted_at=utcnow(),
            deadline=utcnow() + timedelta(hours=2), runtime_minutes=15, power_kw=2.0,
            region="IN-TG", container_image="greenshift/sample:v1",
            status=JobStatus.PENDING_APPROVAL,
        )
        db.add(job)
        db.commit()

        decision = ScheduleDecisionORM(
            job_id=job.job_id,
            selected_start=utcnow() + timedelta(minutes=30),
            selected_end=utcnow() + timedelta(minutes=60),
            carbon_intensity=400.0, carbon_emission=4.0, electricity_cost=1.0, reason="test",
        )
        db.add(decision)
        db.commit()
        db.refresh(decision)

        res = client.post(f"/approval/{job.job_id}/approve", json={"schedule_id": decision.id})
        assert res.status_code == 401

        db.refresh(job)
        assert job.status == JobStatus.PENDING_APPROVAL
        assert db.query(ApprovalORM).filter(ApprovalORM.job_id == job.job_id).first() is None
        assert (
            db.query(NotificationORM)
            .filter(NotificationORM.job_id == job.job_id, NotificationORM.event_type == EventType.APPROVAL_GRANTED)
            .first()
            is None
        )


class TestSendEmailTransportAndConfig:
    """Real SMTP Email-Delivery Integration pass: exercises app.notify.email
    .send_email()'s own transport logic directly (mocking smtplib.SMTP one
    level deeper than TestEmailFailureIsolation's tests, which mock
    send_email() itself) — the from-address fallback, TLS/login sequencing,
    and that credentials never leak into anything persisted or raised."""

    def _mock_smtp_server(self):
        from unittest.mock import MagicMock
        server = MagicMock()
        server.__enter__.return_value = server
        server.__exit__.return_value = False
        return server

    def test_from_address_falls_back_to_username_when_unset(self, db):
        from app.notify.email import send_email
        from app.shared.config import settings

        original = (settings.smtp_enabled, settings.smtp_host, settings.smtp_username,
                    settings.smtp_password, settings.smtp_from_address)
        settings.smtp_enabled = True
        settings.smtp_host = "smtp.example.com"
        settings.smtp_username = "sender@example.com"
        settings.smtp_password = "app-specific-password"
        settings.smtp_from_address = ""  # deliberately unset
        try:
            server = self._mock_smtp_server()
            with patch("smtplib.SMTP", return_value=server) as mock_smtp_cls:
                send_email("recipient@example.com", "Subject", "Body")
            sent_msg = server.send_message.call_args.args[0]
            assert sent_msg["From"] == "sender@example.com"
            mock_smtp_cls.assert_called_once_with("smtp.example.com", settings.smtp_port, timeout=10)
            server.login.assert_called_once_with("sender@example.com", "app-specific-password")
        finally:
            (settings.smtp_enabled, settings.smtp_host, settings.smtp_username,
             settings.smtp_password, settings.smtp_from_address) = original

    def test_explicit_from_address_is_used_when_set(self, db):
        from app.notify.email import send_email
        from app.shared.config import settings

        original = (settings.smtp_enabled, settings.smtp_host, settings.smtp_username,
                    settings.smtp_from_address)
        settings.smtp_enabled = True
        settings.smtp_host = "smtp.example.com"
        settings.smtp_username = "sender@example.com"
        settings.smtp_from_address = "notifications@greenshift-verified.example.com"
        try:
            server = self._mock_smtp_server()
            with patch("smtplib.SMTP", return_value=server):
                send_email("recipient@example.com", "Subject", "Body")
            sent_msg = server.send_message.call_args.args[0]
            assert sent_msg["From"] == "notifications@greenshift-verified.example.com"
        finally:
            (settings.smtp_enabled, settings.smtp_host, settings.smtp_username,
             settings.smtp_from_address) = original

    def test_missing_from_address_and_username_raises_clear_error(self, db):
        from app.notify.email import send_email
        from app.shared.config import settings

        original = (settings.smtp_enabled, settings.smtp_host, settings.smtp_username,
                    settings.smtp_from_address)
        settings.smtp_enabled = True
        settings.smtp_host = "smtp.example.com"
        settings.smtp_username = ""
        settings.smtp_from_address = ""
        try:
            with pytest.raises(RuntimeError, match="SMTP_FROM_ADDRESS"):
                send_email("recipient@example.com", "Subject", "Body")
        finally:
            (settings.smtp_enabled, settings.smtp_host, settings.smtp_username,
             settings.smtp_from_address) = original

    def test_tls_started_when_configured(self, db):
        from app.notify.email import send_email
        from app.shared.config import settings

        original = (settings.smtp_enabled, settings.smtp_host, settings.smtp_username,
                    settings.smtp_from_address, settings.smtp_use_tls)
        settings.smtp_enabled = True
        settings.smtp_host = "smtp.example.com"
        settings.smtp_username = "sender@example.com"
        settings.smtp_from_address = "sender@example.com"
        settings.smtp_use_tls = True
        try:
            server = self._mock_smtp_server()
            with patch("smtplib.SMTP", return_value=server):
                send_email("recipient@example.com", "Subject", "Body")
            server.starttls.assert_called_once()
        finally:
            (settings.smtp_enabled, settings.smtp_host, settings.smtp_username,
             settings.smtp_from_address, settings.smtp_use_tls) = original

    def test_credential_never_appears_in_recorded_last_error(self, db, two_users):
        """Even if the underlying SMTP exception message happened to echo the
        password (some servers include the failed credential in an auth
        error), _deliver_one() only ever stores type(exc).__name__ — never
        str(exc) — so a secret can never end up in a persisted last_error."""
        alice = two_users["alice"]
        secret_password = "S3cr3t-App-Password-Do-Not-Leak"
        job = JobORM(
            job_id="JOB-CRED-LEAK-CHECK", team_id="team-x", tenant_id=alice.tenant_id,
            submitted_by_user_id=alice.id, submitted_at=utcnow(),
            deadline=utcnow() + timedelta(hours=2), runtime_minutes=10, power_kw=1.0,
            region="IN-TG", container_image="greenshift/sample:v1", status=JobStatus.SUBMITTED,
        )
        db.add(job)
        db.commit()

        notif = create_notification(
            db, recipient_user_id=alice.id, event_type=EventType.JOB_SUBMITTED,
            category="WORKLOAD", severity="INFO", title="Workload submitted", message="fallback",
            tenant_id=alice.tenant_id, job_id=job.job_id, email_required=True,
        )

        from app.shared.config import settings
        original_enabled, original_host = settings.smtp_enabled, settings.smtp_host
        settings.smtp_enabled = True
        settings.smtp_host = "smtp.example.com"
        try:
            with patch(
                "app.notify.email.send_email",
                side_effect=RuntimeError(f"Authentication failed for password={secret_password}"),
            ):
                process_pending_emails(db, limit=10)
        finally:
            settings.smtp_enabled, settings.smtp_host = original_enabled, original_host

        db.refresh(notif)
        assert secret_password not in (notif.last_error or "")
        assert "RuntimeError" in (notif.last_error or "")


def test_settings_loads_smtp_env_vars(monkeypatch):
    """Settings (pydantic-settings) must pick up the documented SMTP_* env
    var names verbatim — reusing the existing configuration mechanism, not a
    second/renamed one — without ever needing a restart-time code change."""
    monkeypatch.setenv("SMTP_ENABLED", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.testprovider.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "test-account@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "irrelevant-for-this-test")
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    monkeypatch.setenv("SMTP_FROM_ADDRESS", "verified-sender@example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com")

    from app.shared.config import Settings
    fresh = Settings()

    assert fresh.smtp_enabled is True
    assert fresh.smtp_host == "smtp.testprovider.example.com"
    assert fresh.smtp_port == 2525
    assert fresh.smtp_username == "test-account@example.com"
    assert fresh.smtp_use_tls is False
    assert fresh.smtp_from_address == "verified-sender@example.com"
    assert fresh.frontend_base_url == "https://app.example.com"
