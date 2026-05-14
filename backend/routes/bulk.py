"""Bulk actions — move stage, reject, add to position."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse

from backend.core.auth import get_current_user
from backend.core.database import get_cursor
from backend.core.permissions import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


def _log_activity(cur, candidate_id: int, position_id: int, user_id: int,
                  activity_type: str, details: dict = None):
    """Log candidate activity."""
    cur.execute("""
        INSERT INTO candidate_activity (candidate_id, position_id, user_id, activity_type, details)
        VALUES (%s, %s, %s, %s, %s)
    """, (candidate_id, position_id, user_id, activity_type, json.dumps(details or {})))


@router.post("/move-stage", dependencies=[Depends(require_role("recruiter"))])
async def bulk_move_stage(request: Request):
    """Move multiple candidates to a new pipeline stage."""
    user = get_current_user(request)
    body = await request.json()

    candidate_ids = body.get("candidate_ids", [])
    position_id = body.get("position_id")
    new_stage = body.get("new_stage")
    rejection_reason = body.get("rejection_reason")

    if not candidate_ids or not position_id or not new_stage:
        raise HTTPException(status_code=400, detail="candidate_ids, position_id, and new_stage are required")

    updated = 0
    with get_cursor() as cur:
        for cid in candidate_ids:
            # Sync attachment_state with stage transitions:
            #   stage='rejected' → attachment_state='rejected'
            #   any other stage → attachment_state='attached' (covers re-promote from rejected)
            new_att_state = 'rejected' if new_stage == 'rejected' else 'attached'
            cur.execute("""
                UPDATE position_candidates
                SET stage = %s, stage_changed_at = NOW(), rejection_reason = %s,
                    attachment_state = %s, dismissed = %s, updated_at = NOW()
                WHERE position_id = %s AND candidate_id = %s
            """, (new_stage, rejection_reason, new_att_state, new_stage == 'rejected', position_id, cid))
            if cur.rowcount > 0:
                updated += 1
                _log_activity(cur, cid, position_id, user["user_id"], "stage_change", {
                    "new_stage": new_stage,
                    "rejection_reason": rejection_reason,
                    "bulk": True,
                })

    return {"status": "updated", "updated": updated, "total": len(candidate_ids)}


@router.post("/reject", dependencies=[Depends(require_role("recruiter"))])
async def bulk_reject(request: Request):
    """Reject multiple candidates."""
    user = get_current_user(request)
    body = await request.json()

    candidate_ids = body.get("candidate_ids", [])
    position_id = body.get("position_id")
    rejection_reason = body.get("rejection_reason", "")

    if not candidate_ids or not position_id:
        raise HTTPException(status_code=400, detail="candidate_ids and position_id are required")

    rejected = 0
    with get_cursor() as cur:
        for cid in candidate_ids:
            cur.execute("""
                UPDATE position_candidates
                SET stage = 'rejected', stage_changed_at = NOW(),
                    rejection_reason = %s, attachment_state = 'rejected',
                    dismissed = TRUE, updated_at = NOW()
                WHERE position_id = %s AND candidate_id = %s AND stage != 'rejected'
            """, (rejection_reason, position_id, cid))
            if cur.rowcount > 0:
                rejected += 1
                _log_activity(cur, cid, position_id, user["user_id"], "stage_change", {
                    "new_stage": "rejected",
                    "rejection_reason": rejection_reason,
                    "bulk": True,
                })

    return {"status": "rejected", "rejected": rejected, "total": len(candidate_ids)}


@router.post("/add-to-position", dependencies=[Depends(require_role("recruiter"))])
async def bulk_add_to_position(request: Request):
    """Add multiple candidates to a position."""
    user = get_current_user(request)
    body = await request.json()

    candidate_ids = body.get("candidate_ids", [])
    position_slug = body.get("position_slug")

    if not candidate_ids or not position_slug:
        raise HTTPException(status_code=400, detail="candidate_ids and position_slug are required")

    with get_cursor() as cur:
        cur.execute("SELECT id FROM positions WHERE slug = %s", (position_slug,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Position not found")
        position_id = row[0]

        added = 0
        for cid in candidate_ids:
            try:
                cur.execute("""
                    INSERT INTO position_candidates (position_id, candidate_id, stage, added_by)
                    VALUES (%s, %s, 'uploaded', 'manual')
                    ON CONFLICT (position_id, candidate_id) DO NOTHING
                    RETURNING id
                """, (position_id, cid))
                if cur.fetchone():
                    added += 1
                    _log_activity(cur, cid, position_id, user["user_id"], "added_to_position", {
                        "position_slug": position_slug,
                        "bulk": True,
                    })
            except Exception as e:
                logger.warning(f"Failed to add candidate {cid} to position {position_slug}: {e}")

    return {"status": "added", "added": added, "total": len(candidate_ids), "position_id": position_id}


@router.post("/delete-candidates", dependencies=[Depends(require_role("admin"))])
async def bulk_delete_candidates(request: Request):
    """Hard-delete multiple candidates. Admin/superadmin only. Cascade FKs."""
    from pathlib import Path
    user = get_current_user(request)
    body = await request.json()
    candidate_ids = body.get("candidate_ids", [])
    if not candidate_ids:
        raise HTTPException(400, "candidate_ids required")
    if len(candidate_ids) > 200:
        raise HTTPException(400, "max 200 per call")

    deleted = 0
    paths: list[str] = []
    with get_cursor() as cur:
        for cid in candidate_ids:
            try:
                cur.execute("SELECT pdf_path FROM candidates WHERE id = %s", (cid,))
                r = cur.fetchone()
                if not r:
                    continue
                if r[0]:
                    paths.append(r[0])
                cur.execute("DELETE FROM candidates WHERE id = %s", (cid,))
                if cur.rowcount > 0:
                    deleted += 1
            except Exception as e:
                logger.warning(f"bulk delete cv {cid} failed: {e}")
    # Best-effort file cleanup
    for p in paths:
        try:
            f = Path(p)
            if f.exists() and f.is_file():
                f.unlink()
        except Exception:
            pass
    return {"status": "deleted", "deleted": deleted, "total": len(candidate_ids)}


@router.post("/delete-jds", dependencies=[Depends(require_role("admin"))])
async def bulk_delete_jds(request: Request):
    """Hard-delete multiple JDs. Admin/superadmin only. Cascade FKs."""
    user = get_current_user(request)
    body = await request.json()
    jd_ids = body.get("jd_ids", [])
    if not jd_ids:
        raise HTTPException(400, "jd_ids required")
    if len(jd_ids) > 200:
        raise HTTPException(400, "max 200 per call")

    deleted = 0
    with get_cursor() as cur:
        for jid in jd_ids:
            try:
                cur.execute("DELETE FROM jd_repository WHERE id = %s", (jid,))
                if cur.rowcount > 0:
                    deleted += 1
            except Exception as e:
                logger.warning(f"bulk delete jd {jid} failed: {e}")
    return {"status": "deleted", "deleted": deleted, "total": len(jd_ids)}
