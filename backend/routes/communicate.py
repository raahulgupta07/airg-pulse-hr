"""Communicate — Phase 0 (waitlist only).

Future phases will add announcements/invitations/articles message CRUD,
template library, AI body + image generation, and channel send (email,
SharePoint, Teams, Slack).
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.core.database import get_cursor
from backend.core.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_FEATURES = ("announcements", "invitations", "articles", "copilot")


class WaitlistRequest(BaseModel):
    feature: str


@router.post("/waitlist")
async def join_waitlist(body: WaitlistRequest, request: Request):
    user = get_current_user(request)
    if body.feature not in ALLOWED_FEATURES:
        raise HTTPException(400, f"feature must be one of {ALLOWED_FEATURES}")
    uid = user.get("user_id")
    with get_cursor() as cur:
        # ON CONFLICT DO NOTHING in case user clicks twice
        cur.execute(
            """INSERT INTO comm_waitlist (user_id, feature) VALUES (%s, %s)
               ON CONFLICT (user_id, feature) DO NOTHING
               RETURNING id""",
            (uid, body.feature),
        )
        row = cur.fetchone()
    return {
        "feature": body.feature,
        "added": bool(row),
        "message": "added to waitlist" if row else "already on waitlist",
    }


@router.get("/waitlist/counts")
async def waitlist_counts(request: Request):
    _ = get_current_user(request)
    counts = {f: 0 for f in ALLOWED_FEATURES}
    with get_cursor() as cur:
        cur.execute("SELECT feature, COUNT(*) FROM comm_waitlist GROUP BY feature")
        for f, n in cur.fetchall():
            counts[f] = n
    return {"counts": counts}


@router.get("/me/waitlist")
async def my_waitlist(request: Request):
    user = get_current_user(request)
    uid = user.get("user_id")
    with get_cursor() as cur:
        cur.execute("SELECT feature FROM comm_waitlist WHERE user_id=%s", (uid,))
        joined = [r[0] for r in cur.fetchall()]
    return {"joined": joined}
