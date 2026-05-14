"""Merge proposals — list, preview, approve, reject, revert duplicate-merge proposals."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.core.database import get_cursor
from backend.core.permissions import require_role
from backend.agents.merge import preview_merge, apply_merge, reject_merge, revert_merge
from backend.agents.dedup import (
    propose_candidate_dups, propose_jd_dups,
    dedup_sweep_candidates, dedup_sweep_jds,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ApproveRequest(BaseModel):
    field_choices: Optional[dict] = None
    archive: bool = True


class RejectRequest(BaseModel):
    notes: Optional[str] = None


class SweepRequest(BaseModel):
    entity_type: str  # "candidate" | "jd"


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@router.get("/")
async def list_proposals(
    request: Request,
    entity_type: Optional[str] = Query(None),
    status: Optional[str] = Query("pending"),
    limit: int = Query(100),
    offset: int = Query(0),
):
    get_current_user(request)
    conditions, params = [], []
    if entity_type:
        conditions.append("entity_type = %s"); params.append(entity_type)
    if status:
        conditions.append("status = %s"); params.append(status)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM merge_proposals {where}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"""SELECT id, entity_type, winner_id, loser_id, confidence, method,
                       status, decided_by, decided_at, notes, created_at
                FROM merge_proposals {where}
                ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            params + [limit, offset],
        )
        cols = [d[0] for d in cur.description]
        items = [dict(zip(cols, r)) for r in cur.fetchall()]

        # Augment with summary names
        for it in items:
            tbl = "candidates" if it["entity_type"] == "candidate" else "jd_repository"
            name_col = "name" if it["entity_type"] == "candidate" else "title"
            try:
                cur.execute(f"SELECT id, {name_col} FROM {tbl} WHERE id IN (%s, %s)",
                            (it["winner_id"], it["loser_id"]))
                rows = {r[0]: r[1] for r in cur.fetchall()}
                it["winner_label"] = rows.get(it["winner_id"])
                it["loser_label"] = rows.get(it["loser_id"])
            except Exception:
                pass

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/pending-count")
async def pending_count(request: Request):
    get_current_user(request)
    with get_cursor() as cur:
        cur.execute("SELECT entity_type, COUNT(*) FROM merge_proposals WHERE status='pending' GROUP BY entity_type")
        rows = dict(cur.fetchall())
    cands = int(rows.get("candidate", 0))
    jds = int(rows.get("jd", 0))
    return {"candidates": cands, "jds": jds, "total": cands + jds}


@router.get("/{proposal_id}")
async def get_proposal(proposal_id: int, request: Request):
    get_current_user(request)
    return preview_merge(proposal_id)


@router.post("/{proposal_id}/approve", dependencies=[Depends(require_role("admin"))])
async def approve_proposal(proposal_id: int, body: ApproveRequest, request: Request):
    user = get_current_user(request)
    return apply_merge(
        proposal_id,
        field_choices=body.field_choices or {},
        archive=body.archive,
        user_id=user.get("user_id"),
    )


@router.post("/{proposal_id}/reject", dependencies=[Depends(require_role("admin"))])
async def reject_proposal(proposal_id: int, body: RejectRequest, request: Request):
    user = get_current_user(request)
    return reject_merge(proposal_id, user_id=user.get("user_id"), notes=body.notes)


@router.post("/{proposal_id}/revert")
async def revert_proposal(proposal_id: int, request: Request):
    user = get_current_user(request)
    if user.get("role") not in ("admin", "group_hr"):
        # Allow in dev mode
        import os
        if not os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes"):
            raise HTTPException(403, "Admin only")
    return revert_merge(proposal_id, user_id=user.get("user_id"))


@router.post("/scan/candidate/{candidate_id}", dependencies=[Depends(require_role("admin"))])
async def scan_candidate(candidate_id: int, request: Request):
    get_current_user(request)
    created = propose_candidate_dups(candidate_id)
    return {"candidate_id": candidate_id, "proposals_created": len(created), "ids": created}


@router.post("/scan/jd/{jd_id}", dependencies=[Depends(require_role("admin"))])
async def scan_jd(jd_id: int, request: Request):
    get_current_user(request)
    created = propose_jd_dups(jd_id)
    return {"jd_id": jd_id, "proposals_created": len(created), "ids": created}


@router.post("/scan/sweep", dependencies=[Depends(require_role("admin"))])
async def sweep(body: SweepRequest, request: Request):
    get_current_user(request)
    if body.entity_type == "candidate":
        return dedup_sweep_candidates()
    elif body.entity_type == "jd":
        return dedup_sweep_jds()
    raise HTTPException(400, "entity_type must be 'candidate' or 'jd'")
