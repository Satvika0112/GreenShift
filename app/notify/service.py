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

from app.shared.models import EventType, NotificationORM, NotificationPreferenceORM, UserORM, UserRole
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)

# category -> the NotificationPreferenceORM column governing its email channel.
# ACCOUNT/SECURITY/INFRASTRUCTURE are intentionally not user-disableable — a
# category missing from this map is treated as always-eligible (fail open
# on the *allow* side only; create_notification's caller still decides
# email_required in the first place, this only ever narrows it further).
_CATEGORY_PREFERENCE_FIELD = {
    "WORKLOAD": "email_workload",
    "SCHEDULING": "email_scheduling",
    "APPROVAL": "email_approval",
    "EXECUTION": "email_execution",
}


def _dedup_key(event_type: EventType, job_id: Optional[str], suffix: Optional[str] = None) -> str:
    key = f"{event_type.value if hasattr(event_type, 'value') else event_type}:{job_id or 'none'}"
    if suffix:
        key += f":{suffix}"
    return key


_PENDING_APPROVAL_EVENT_TYPES = frozenset({EventType.SCHEDULE_PROPOSED})


def _default_action_url(category: str, job_id: Optional[str], event_type: Optional[EventType] = None) -> Optional[str]:
    """
    Meaningful, always-real navigation target for a notification, built only
    from existing frontend routes (see frontend/src/App.tsx):
      - a still-pending approval request (SCHEDULE_PROPOSED, category
        APPROVAL) -> the approvals queue, since that's where it can be
        acted on (no per-job approval route exists to deep-link to)
      - an already-resolved APPROVAL event (APPROVAL_GRANTED/DECLINED) or
        any other category with a job_id -> that workload's detail page —
        once resolved, the approvals queue no longer holds it, and a
        COMPANY_USER submitter isn't an approver in the first place
      - no job_id (account/security/system events) -> no destination
    Never invents a route; a notification with nothing meaningful to link to
    is left with action_url=None rather than a guessed/broken URL.
    """
    if category == "APPROVAL" and event_type in _PENDING_APPROVAL_EVENT_TYPES:
        return "/approvals"
    if job_id:
        return f"/workloads/{job_id}"
    return None


def get_or_create_preferences(db: Session, user_id: int) -> NotificationPreferenceORM:
    """Lazily create an all-enabled preference row on first access."""
    prefs = db.query(NotificationPreferenceORM).filter(NotificationPreferenceORM.user_id == user_id).first()
    if prefs is not None:
        return prefs
    prefs = NotificationPreferenceORM(user_id=user_id, created_at=utcnow())
    db.add(prefs)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent first-access race — another request already created it.
        db.rollback()
        prefs = db.query(NotificationPreferenceORM).filter(NotificationPreferenceORM.user_id == user_id).first()
        if prefs is not None:
            return prefs
        raise
    db.refresh(prefs)
    return prefs


def update_preferences(db: Session, user_id: int, **fields) -> NotificationPreferenceORM:
    """Update only the editable (non-security) preference fields that were actually supplied."""
    prefs = get_or_create_preferences(db, user_id)
    for key, value in fields.items():
        if value is None:
            continue
        if key not in _CATEGORY_PREFERENCE_FIELD.values():
            continue  # never allow writing email_system or an unknown column here
        setattr(prefs, key, value)
    prefs.updated_at = utcnow()
    db.commit()
    db.refresh(prefs)
    return prefs


def _email_allowed_by_preference(db: Session, recipient_user_id: int, category: str) -> bool:
    """Security-critical categories are always eligible; others follow the recipient's stored preference."""
    field = _CATEGORY_PREFERENCE_FIELD.get(category)
    if field is None:
        return True
    prefs = get_or_create_preferences(db, recipient_user_id)
    return bool(getattr(prefs, field, True))


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

    The in-app notification is always created regardless of preference —
    only the email channel is gated: if the caller requested email_required
    but the recipient has disabled that category, the row is still created
    with email_required=False (never silently dropped, never emailed
    against the recipient's stated preference).
    """
    if email_required and not _email_allowed_by_preference(db, recipient_user_id, category):
        email_required = False

    notif = NotificationORM(
        tenant_id=tenant_id,
        recipient_user_id=recipient_user_id,
        job_id=job_id,
        event_type=event_type,
        category=category,
        severity=severity,
        title=title,
        message=message,
        action_url=action_url if action_url is not None else _default_action_url(category, job_id, event_type),
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

    try:
        from app.notify.realtime import publish_notification_event
        from app.shared.models import NotificationResponse
        publish_notification_event(
            recipient_user_id,
            NotificationResponse.model_validate(notif).model_dump(mode="json"),
        )
    except Exception:
        logger.debug("Realtime publish failed for notification %s", notif.id, exc_info=True)

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
    """Company Admins for a given tenant."""
    if not tenant_id:
        return []
    q = db.query(UserORM.id).filter(
        UserORM.tenant_id == tenant_id,
        UserORM.role == UserRole.COMPANY_ADMIN,
        UserORM.is_active == True,  # noqa: E712
    )
    return [row[0] for row in q.all()]


def resolve_platform_admin_user_ids(db: Session) -> List[int]:
    """Global Platform Admins (role PLATFORM_ADMIN, no tenant)."""
    q = db.query(UserORM.id).filter(
        UserORM.role == UserRole.PLATFORM_ADMIN,
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
