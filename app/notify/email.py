"""
GreenShift — Notification Email Delivery.

Delivers NotificationORM rows with email_required=True via SMTP, entirely
outside the business transaction that created them. An email failure here
must NEVER change job/workload/execution state — this module only ever
touches the notifications table.

Content rules (see spec section 34):
  - never include JWTs, passwords, API keys, secrets, SQL, stack traces,
    internal filesystem paths, Kubernetes internals, or cross-tenant data
  - plain-text body (no HTML injection surface)
  - subject/recipient values are sanitized against header injection
  - recipient is always the notification's own recipient_user_id's email —
    never a client-supplied address
"""

import logging
import smtplib
import time
from datetime import timedelta
from email.message import EmailMessage
from typing import Optional

from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import NotificationORM, UserORM
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)


def _sanitize_header_value(value: str) -> str:
    """Strip CR/LF to prevent email header injection via a stored title/subject."""
    return (value or "").replace("\r", " ").replace("\n", " ").strip()


def _backoff_seconds(attempt_number: int) -> int:
    """Exponential backoff capped at 1 hour: 60s, 120s, 240s, ... """
    return min(3600, 60 * (2 ** max(0, attempt_number - 1)))


def send_email(to_address: str, subject: str, body: str) -> None:
    """Send one plain-text email via SMTP. Raises on failure — caller handles retry bookkeeping."""
    if not settings.smtp_enabled:
        raise RuntimeError("SMTP delivery is disabled (SMTP_ENABLED=false)")
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is not configured")

    msg = EmailMessage()
    msg["Subject"] = _sanitize_header_value(subject)
    msg["From"] = settings.smtp_from_address
    msg["To"] = _sanitize_header_value(to_address)
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)


def _deliver_one(db: Session, notif: NotificationORM) -> None:
    now = utcnow()
    recipient = db.get(UserORM, notif.recipient_user_id)
    if recipient is None or not recipient.email:
        notif.email_status = "FAILED"
        notif.email_failed_at = now
        notif.last_error = "Recipient has no email address on file"
        db.commit()
        try:
            from app.shared.models import EventType
            from app.trust.ledger import append_event
            append_event(
                db, EventType.EMAIL_DELIVERY_FAILED, job_id=notif.job_id,
                payload={"notification_id": notif.id, "recipient_user_id": notif.recipient_user_id, "reason": "no_email_on_file"},
                tenant_id=notif.tenant_id, source_service="notify",
            )
        except Exception:
            pass
        # In-app delivery already happened at creation time (this module only
        # ever touches the email channel) — the business event itself is
        # unaffected by the recipient having no email on file.
        return

    notif.email_attempts = (notif.email_attempts or 0) + 1
    try:
        from app.notify.templates import render_email
        subject, body = render_email(db, notif)
        send_email(recipient.email, subject, body)
        notif.email_status = "SENT"
        notif.email_sent_at = now
        notif.last_error = None
        notif.next_attempt_at = None
    except Exception as exc:
        # Never leak internals (stack traces, SMTP creds, etc.) into the stored error.
        notif.last_error = f"Delivery attempt {notif.email_attempts} failed: {type(exc).__name__}"
        max_attempts = settings.notification_email_max_attempts
        if notif.email_attempts >= max_attempts:
            notif.email_status = "FAILED"
            notif.email_failed_at = now
            notif.next_attempt_at = None
            logger.warning(
                "Notification %s email delivery permanently failed after %d attempts",
                notif.id, notif.email_attempts,
            )
            try:
                from app.shared.models import EventType
                from app.trust.ledger import append_event
                append_event(
                    db, EventType.EMAIL_DELIVERY_FAILED, job_id=notif.job_id,
                    payload={"notification_id": notif.id, "recipient_user_id": notif.recipient_user_id, "attempts": notif.email_attempts},
                    tenant_id=notif.tenant_id, source_service="notify",
                )
            except Exception:
                # Audit is best-effort here too — must never block the
                # notifications-table commit below.
                pass
        else:
            notif.next_attempt_at = now + timedelta(seconds=_backoff_seconds(notif.email_attempts))
            logger.info(
                "Notification %s email delivery attempt %d failed, retrying at %s",
                notif.id, notif.email_attempts, notif.next_attempt_at.isoformat(),
            )
    db.commit()


def process_pending_emails(db: Session, limit: int = 20) -> int:
    """Attempt delivery for due PENDING notifications. Returns count processed."""
    if not settings.smtp_enabled:
        return 0

    now = utcnow()
    pending = (
        db.query(NotificationORM)
        .filter(
            NotificationORM.email_required == True,  # noqa: E712
            NotificationORM.email_status == "PENDING",
        )
        .filter(
            (NotificationORM.next_attempt_at.is_(None)) | (NotificationORM.next_attempt_at <= now)
        )
        .order_by(NotificationORM.created_at.asc())
        .limit(limit)
        .all()
    )
    for notif in pending:
        try:
            _deliver_one(db, notif)
        except Exception as exc:
            # Belt-and-braces: a bug in delivery bookkeeping must not crash the
            # worker loop or touch any other table.
            logger.error("Unexpected error delivering notification %s: %s", notif.id, exc, exc_info=True)
            db.rollback()
    return len(pending)


def run_email_loop() -> None:
    """Long-running notification email worker. Mirrors the ingest/decide/dispatch service pattern."""
    from app.shared.database import init_db

    init_db()
    interval = settings.notification_poll_interval_seconds
    logger.info(
        "Notification email worker starting (smtp_enabled=%s, interval=%ds)",
        settings.smtp_enabled, interval,
    )
    while True:
        db = SessionLocal()
        try:
            count = process_pending_emails(db)
            if count:
                logger.info("Processed %d pending notification email(s)", count)
        except Exception as exc:
            logger.error("Notification email loop iteration failed: %s", exc, exc_info=True)
        finally:
            db.close()
        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_email_loop()
