"""
GreenShift — Notification API Router.

Endpoints:
- GET   /notifications
- GET   /notifications/unread-count
- PATCH /notifications/{id}/read
- PATCH /notifications/read-all

Recipient identity is always the authenticated caller — never a
client-supplied user id. A user can only read/update their own notifications.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.notify.service import get_notifications, get_unread_count, mark_all_read, mark_read
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.models import NotificationResponse, UnreadCountResponse, UserORM

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
