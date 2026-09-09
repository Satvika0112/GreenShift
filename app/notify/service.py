"""
GreenShift — Notification Service.

In-app notification persistence + query. Recipient identity is always
server-derived by the caller (never trust a client-supplied user id).

Notification creation must never fail or roll back the business transaction
that triggered it: callers wrap create_notification()/notify_* in try/except,
mirroring the existing app.trust.service audit-event pattern.
"""

import logging
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared.models import EventType, NotificationORM, UserORM, UserRole
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)


def _dedup_key(event_type: EventType, job_id: Optional[str], suffix: Optional[str] = None) -> str:
    key = f"{event_type.value if hasattr(event_type, 'value') else event_type}:{job_id or 'none'}"
    if suffix:
        key += f":{suffix}"
    return key


def create_notification(
    db: Session,
    recipient_user_id: int,
    event_type: EventType,
    category: str,
    severity: str,
    title: str,
    message: str,
    tenant_id: Optional[str] = None,
    job_id: Optional[str] = None,
    action_url: Optional[str] = None,
    dedup_suffix: Optional[str] = None,
    email_required: bool = False,
) -> Optional[NotificationORM]:
    """
    Persist one notification. Idempotent per (recipient, event_type, job_id[,suffix]):
    a duplicate logical event for the same recipient is silently absorbed, not
    inserted as a second row (uq_notifications_recipient_dedup).
    """
    notif = NotificationORM(
        tenant_id=tenant_id,
        recipient_user_id=recipient_user_id,
        job_id=job_id,
        event_type=event_type,
        category=category,
        severity=severity,
        title=title,
        message=message,
        action_url=action_url,
        created_at=utcnow(),
        dedup_key=_dedup_key(event_type, job_id, dedup_suffix),
        email_required=email_required,
        email_status="PENDING" if email_required else "NOT_REQUIRED",
    )
    # Pre-check avoids relying on constraint-violation control flow (and the
    # SAVEPOINT/rollback interactions that brings on a shared test session);
    # the unique constraint remains as the real concurrent-write backstop.
    existing = (
        db.query(NotificationORM)
        .filter(
            NotificationORM.recipient_user_id == recipient_user_id,
            NotificationORM.dedup_key == notif.dedup_key,
        )
        .first()
    )
    if existing is not None:
        logger.debug(
            "Duplicate notification suppressed (recipient=%s, event=%s, job=%s)",
            recipient_user_id, event_type, job_id,
        )
        return None

    db.add(notif)
    try:
        db.commit()
    except IntegrityError:
        # Rare race: another writer inserted the same dedup key between our
        # check and this commit. This is the *last* operation in the caller's
        # notification step (always called after its own business commit),
        # so a rollback here is scoped to just this insert attempt.
        db.rollback()
        logger.debug(
            "Duplicate notification suppressed on concurrent insert (recipient=%s, event=%s, job=%s)",
            recipient_user_id, event_type, job_id,
        )
        return None
    db.refresh(notif)
    return notif


def notify_users(
    db: Session,
    recipient_user_ids: List[int],
    **kwargs,
) -> List[NotificationORM]:
    """Fan out the same logical event to multiple recipients."""
    results = []
    for uid in recipient_user_ids:
        n = create_notification(db, recipient_user_id=uid, **kwargs)
        if n is not None:
            results.append(n)
    return results


def resolve_tenant_admin_user_ids(db: Session, tenant_id: Optional[str]) -> List[int]:
    """Company Admins (and legacy tenant-scoped ADMIN) for a given tenant."""
    if not tenant_id:
        return []
    q = db.query(UserORM.id).filter(
        UserORM.tenant_id == tenant_id,
        UserORM.role.in_([UserRole.COMPANY_ADMIN, UserRole.ADMIN, UserRole.TEAM_LEAD]),
        UserORM.is_active == True,  # noqa: E712
    )
    return [row[0] for row in q.all()]


def resolve_platform_admin_user_ids(db: Session) -> List[int]:
    """Global Platform Admins (role PLATFORM_ADMIN, or legacy ADMIN with no tenant)."""
    q = db.query(UserORM.id).filter(
        UserORM.role.in_([UserRole.PLATFORM_ADMIN, UserRole.ADMIN]),
        UserORM.tenant_id.is_(None),
        UserORM.is_active == True,  # noqa: E712
    )
    return [row[0] for row in q.all()]


def get_notifications(
    db: Session,
    recipient_user_id: int,
    unread_only: bool = False,
    limit: int = 50,
) -> List[NotificationORM]:
    query = db.query(NotificationORM).filter(NotificationORM.recipient_user_id == recipient_user_id)
    if unread_only:
        query = query.filter(NotificationORM.read_at.is_(None))
    return query.order_by(NotificationORM.created_at.desc()).limit(limit).all()


def get_unread_count(db: Session, recipient_user_id: int) -> int:
    return (
        db.query(NotificationORM)
        .filter(NotificationORM.recipient_user_id == recipient_user_id, NotificationORM.read_at.is_(None))
        .count()
    )


def mark_read(db: Session, recipient_user_id: int, notification_id: int) -> Optional[NotificationORM]:
    """Mark one notification read. Scoped to the caller — never another user's row."""
    notif = (
        db.query(NotificationORM)
        .filter(NotificationORM.id == notification_id, NotificationORM.recipient_user_id == recipient_user_id)
        .first()
    )
    if notif is None:
        return None
    if notif.read_at is None:
        notif.read_at = utcnow()
        db.commit()
        db.refresh(notif)
    return notif


def mark_all_read(db: Session, recipient_user_id: int) -> int:
    """Mark all of the caller's unread notifications read. Returns count updated."""
    now = utcnow()
    updated = (
        db.query(NotificationORM)
        .filter(NotificationORM.recipient_user_id == recipient_user_id, NotificationORM.read_at.is_(None))
        .update({"read_at": now}, synchronize_session=False)
    )
    db.commit()
    return updated
