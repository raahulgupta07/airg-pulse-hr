"""Notification routes — bell notifications for HR users."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request, HTTPException

from backend.core.auth import get_current_user
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helper — callable from other routes
# ---------------------------------------------------------------------------
def create_notification(user_id: int, type: str, title: str,
                        message: str = "", link: str = ""):
    """Create a notification for a user. Called from other routes."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO notifications (user_id, type, title, message, link)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, type, title, message, link))
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/")
async def list_notifications(request: Request, limit: int = 30):
    """List notifications for current user, unread first."""
    user = get_current_user(request)
    user_id = user["user_id"]

    with get_cursor() as cur:
        cur.execute("""
            SELECT id, type, title, message, link, is_read, created_at
            FROM notifications
            WHERE user_id = %s
            ORDER BY is_read ASC, created_at DESC
            LIMIT %s
        """, (user_id, limit))
        cols = [desc[0] for desc in cur.description]
        notifications = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {"notifications": notifications}


@router.get("/count")
async def unread_count(request: Request):
    """Get unread notification count for current user."""
    user = get_current_user(request)
    user_id = user["user_id"]

    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = FALSE",
            (user_id,),
        )
        count = cur.fetchone()[0]

    return {"count": count}


@router.post("/read/{notification_id}")
async def mark_read(notification_id: int, request: Request):
    """Mark a single notification as read."""
    user = get_current_user(request)
    user_id = user["user_id"]

    with get_cursor() as cur:
        cur.execute(
            "UPDATE notifications SET is_read = TRUE WHERE id = %s AND user_id = %s",
            (notification_id, user_id),
        )

    return {"message": "Notification marked as read"}


@router.post("/read-all")
async def mark_all_read(request: Request):
    """Mark all notifications as read for current user."""
    user = get_current_user(request)
    user_id = user["user_id"]

    with get_cursor() as cur:
        cur.execute(
            "UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE",
            (user_id,),
        )

    return {"message": "All notifications marked as read"}
