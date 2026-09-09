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
