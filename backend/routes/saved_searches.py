"""Saved Searches / Talent Alerts — save, load, run filters, check alerts."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse

from backend.core.auth import get_current_user
from backend.core.database import get_cursor, list_candidates
from backend.core.permissions import require_role
from backend.routes.notifications import create_notification

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# List saved searches for current user
# ---------------------------------------------------------------------------
@router.get("/")
async def list_saved_searches(request: Request):
    """List all saved searches for the current user."""
    user = get_current_user(request)
    user_id = user["user_id"]

    with get_cursor() as cur:
        cur.execute("""
            SELECT id, name, filters, notify_on_match, last_result_count,
                   last_checked_at, created_at
            FROM saved_searches
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))
        cols = [desc[0] for desc in cur.description]
        searches = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {"searches": searches, "count": len(searches)}


# ---------------------------------------------------------------------------
# Create a saved search
# ---------------------------------------------------------------------------
@router.post("/")
async def create_saved_search(request: Request):
    """Save current search filters."""
    user = get_current_user(request)
    user_id = user["user_id"]
    body = await request.json()

    name = body.get("name")
    filters = body.get("filters", {})
    notify_on_match = body.get("notify_on_match", False)

    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO saved_searches (user_id, name, filters, notify_on_match)
            VALUES (%s, %s, %s, %s)
            RETURNING id, created_at
        """, (user_id, name, json.dumps(filters), notify_on_match))
        row = cur.fetchone()

    return {"id": row[0], "created_at": row[1], "status": "created"}


# ---------------------------------------------------------------------------
# Delete a saved search
# ---------------------------------------------------------------------------
@router.delete("/{search_id}")
async def delete_saved_search(search_id: int, request: Request):
    """Delete a saved search."""
    user = get_current_user(request)
    user_id = user["user_id"]

    with get_cursor() as cur:
        cur.execute(
            "DELETE FROM saved_searches WHERE id = %s AND user_id = %s RETURNING id",
            (search_id, user_id),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Saved search not found")

    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Toggle alert on/off
# ---------------------------------------------------------------------------
@router.patch("/{search_id}")
async def update_saved_search(search_id: int, request: Request):
    """Update a saved search (toggle notify_on_match)."""
    user = get_current_user(request)
    user_id = user["user_id"]
    body = await request.json()

    notify = body.get("notify_on_match")
    if notify is None:
        raise HTTPException(status_code=400, detail="notify_on_match is required")

    with get_cursor() as cur:
        cur.execute(
            "UPDATE saved_searches SET notify_on_match = %s WHERE id = %s AND user_id = %s RETURNING id",
            (notify, search_id, user_id),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Saved search not found")

    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Run a saved search
# ---------------------------------------------------------------------------
@router.post("/{search_id}/run")
async def run_saved_search(search_id: int, request: Request):
    """Run a saved search and return matching candidates."""
    user = get_current_user(request)
    user_id = user["user_id"]

    with get_cursor() as cur:
        cur.execute(
            "SELECT filters FROM saved_searches WHERE id = %s AND user_id = %s",
            (search_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Saved search not found")
        filters = row[0] if isinstance(row[0], dict) else json.loads(row[0])

    # Apply filters using existing list_candidates function
    skills_list = None
    if filters.get("skills"):
        skills_val = filters["skills"]
        if isinstance(skills_val, str):
            skills_list = [s.strip() for s in skills_val.split(",") if s.strip()]
        elif isinstance(skills_val, list):
            skills_list = skills_val

    candidates = list_candidates(
        search=filters.get("search"),
        skills=skills_list,
        seniority=filters.get("seniority"),
        limit=100,
        offset=0,
    )

    # Update last result count and checked time
    with get_cursor() as cur:
        cur.execute(
            "UPDATE saved_searches SET last_result_count = %s, last_checked_at = NOW() WHERE id = %s",
            (len(candidates), search_id),
        )

    return {"candidates": candidates, "total": len(candidates)}


# ---------------------------------------------------------------------------
# Check alerts — find new matches for all alert-enabled searches
# ---------------------------------------------------------------------------
@router.post("/check-alerts", dependencies=[Depends(require_role("admin"))])
async def check_alerts(request: Request):
    """Check all alert-enabled saved searches for new matches."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT id, user_id, name, filters, last_result_count
            FROM saved_searches
            WHERE notify_on_match = TRUE
        """)
        cols = [desc[0] for desc in cur.description]
        alert_searches = [dict(zip(cols, row)) for row in cur.fetchall()]

    alerts_triggered = 0

    for search in alert_searches:
        filters = search["filters"] if isinstance(search["filters"], dict) else json.loads(search["filters"])

        skills_list = None
        if filters.get("skills"):
            skills_val = filters["skills"]
            if isinstance(skills_val, str):
                skills_list = [s.strip() for s in skills_val.split(",") if s.strip()]
            elif isinstance(skills_val, list):
                skills_list = skills_val

        candidates = list_candidates(
            search=filters.get("search"),
            skills=skills_list,
            seniority=filters.get("seniority"),
            limit=200,
            offset=0,
        )

        current_count = len(candidates)
        previous_count = search["last_result_count"] or 0

        if current_count > previous_count:
            new_matches = current_count - previous_count
            try:
                create_notification(
                    user_id=search["user_id"],
                    type="talent_alert",
                    title=f"{new_matches} new match(es) for '{search['name']}'",
                    message=f"Your saved search '{search['name']}' found {new_matches} new candidate(s).",
                    link="/candidates",
                )
                alerts_triggered += 1
            except Exception as e:
                logger.warning(f"Failed to create alert notification: {e}")

        # Update count
        with get_cursor() as cur:
            cur.execute(
                "UPDATE saved_searches SET last_result_count = %s, last_checked_at = NOW() WHERE id = %s",
                (current_count, search["id"]),
            )

    return {"checked": len(alert_searches), "alerts_triggered": alerts_triggered}
