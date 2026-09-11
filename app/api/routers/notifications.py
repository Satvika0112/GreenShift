"""
GreenShift — Notification API Router.

Endpoints:
- GET   /notifications
- GET   /notifications/unread-count
- PATCH /notifications/{id}/read
- PATCH /notifications/read-all
- GET   /notifications/preferences
- PUT   /notifications/preferences

Recipient identity is always the authenticated caller — never a
client-supplied user id. A user can only read/update their own notifications
and their own preferences.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.notify.service import (
    get_notifications,
    get_or_create_preferences,
    get_unread_count,
    mark_all_read,
    mark_read,
    update_preferences,
)
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.models import (
    NotificationPreferenceResponse,
    NotificationPreferenceUpdateRequest,
    NotificationResponse,
    UnreadCountResponse,
    UserORM,
)

router = APIRouter(tags=["Notifications"])


@router.get("/notifications", response_model=List[NotificationResponse])
def api_get_notifications(
    unread_only: bool = Query(False, description="Only return unread notifications"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """List the authenticated user's own notifications, newest first."""
    return get_notifications(db, recipient_user_id=current_user.id, unread_only=unread_only, limit=limit)


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
def api_get_unread_count(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    return UnreadCountResponse(unread_count=get_unread_count(db, recipient_user_id=current_user.id))


@router.patch("/notifications/{notification_id}/read", response_model=NotificationResponse)
def api_mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    notif = mark_read(db, recipient_user_id=current_user.id, notification_id=notification_id)
    if notif is None:
        # 404 regardless of whether the id exists for someone else — avoids
        # leaking existence of other users' notifications.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return notif


@router.patch("/notifications/read-all")
def api_mark_all_read(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    count = mark_all_read(db, recipient_user_id=current_user.id)
    return {"marked_read": count}


@router.get("/notifications/preferences", response_model=NotificationPreferenceResponse)
def api_get_preferences(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """The authenticated user's own email notification preferences (lazily created with all-enabled defaults)."""
    return get_or_create_preferences(db, user_id=current_user.id)


@router.put("/notifications/preferences", response_model=NotificationPreferenceResponse)
def api_update_preferences(
    body: NotificationPreferenceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Update the caller's own preferences. `email_system` is not an accepted
    field on the request body — security/account/infrastructure email
    notifications cannot be disabled.
    """
    return update_preferences(db, user_id=current_user.id, **body.model_dump(exclude_unset=True))
