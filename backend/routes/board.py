"""Hiring Board — KPI summary + lifecycle stage management."""
from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.core.permissions import require_role
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter()

LIFECYCLE_STAGES = ("draft", "sourcing", "screening", "interview", "offer", "filled", "archived")


@router.get("/summary")
async def board_summary(request: Request):
    """Return KPI tiles + positions grouped by lifecycle_stage."""
    _ = get_current_user(request)
    out = {
        "kpis": {
            "open_positions": 0,
            "active_cvs": 0,
            "avg_tth_days": None,
            "stale_count": 0,
            "filled_mtd": 0,
            "new_today": 0,
            "interviews_week": 0,
            "offers_out": 0,
            "avg_match_score": None,
            "hired_qtd": 0,
        },
        "stages": {s: [] for s in LIFECYCLE_STAGES},
        "departments": [],
    }

    with get_cursor() as cur:
        # KPI: open positions (status='active' AND not archived)
        cur.execute("SELECT COUNT(*) FROM positions WHERE status='active' AND COALESCE(lifecycle_stage,'sourcing') != 'archived'")
        out["kpis"]["open_positions"] = cur.fetchone()[0] or 0

        # KPI: active CVs in pipeline (any non-rejected position_candidate)
        cur.execute("""
            SELECT COUNT(*) FROM position_candidates pc
            JOIN positions p ON p.id = pc.position_id
            WHERE p.status = 'active'
              AND COALESCE(pc.stage,'uploaded') NOT IN ('rejected','hired','withdrawn')
        """)
        out["kpis"]["active_cvs"] = cur.fetchone()[0] or 0

        # KPI: avg time-to-hire (days) — hires in last 90d
        cur.execute("""
            SELECT AVG(EXTRACT(EPOCH FROM (pc.updated_at - pc.created_at))/86400)
            FROM position_candidates pc
            WHERE pc.stage = 'hired' AND pc.updated_at > NOW() - INTERVAL '90 days'
        """)
        v = cur.fetchone()[0]
        out["kpis"]["avg_tth_days"] = round(float(v), 1) if v is not None else None

        # KPI: stale (open > 30d, no movement)
        cur.execute("""
            SELECT COUNT(*) FROM positions
            WHERE status='active' AND created_at < NOW() - INTERVAL '30 days'
        """)
        out["kpis"]["stale_count"] = cur.fetchone()[0] or 0

        # KPI: filled this month
        cur.execute("""
            SELECT COUNT(*) FROM positions
            WHERE COALESCE(lifecycle_stage,'sourcing') = 'filled'
              AND COALESCE(updated_at, created_at) >= date_trunc('month', NOW())
        """)
        out["kpis"]["filled_mtd"] = cur.fetchone()[0] or 0

        # KPI: new positions today
        cur.execute("SELECT COUNT(*) FROM positions WHERE created_at >= CURRENT_DATE")
        out["kpis"]["new_today"] = cur.fetchone()[0] or 0

        # KPI: interviews scheduled this week (counts position_candidates moved to 'interview' stage)
        cur.execute("""
            SELECT COUNT(*) FROM position_candidates
            WHERE COALESCE(stage,'') ILIKE '%interview%'
              AND COALESCE(updated_at, created_at) >= NOW() - INTERVAL '7 days'
        """)
        out["kpis"]["interviews_week"] = cur.fetchone()[0] or 0

        # KPI: offers currently out
        cur.execute("""
            SELECT COUNT(*) FROM position_candidates
            WHERE COALESCE(stage,'') = 'offered'
        """)
        out["kpis"]["offers_out"] = cur.fetchone()[0] or 0

        # KPI: avg match score across active pipeline
        cur.execute("""
            SELECT AVG(match_score_composite) FROM position_candidates pc
            JOIN positions p ON p.id = pc.position_id
            WHERE p.status='active' AND match_score_composite IS NOT NULL
        """)
        v = cur.fetchone()[0]
        out["kpis"]["avg_match_score"] = round(float(v)) if v is not None else None

        # KPI: hired this quarter
        cur.execute("""
            SELECT COUNT(*) FROM position_candidates
            WHERE stage='hired'
              AND COALESCE(updated_at, created_at) >= date_trunc('quarter', NOW())
        """)
        out["kpis"]["hired_qtd"] = cur.fetchone()[0] or 0

        # Positions w/ stage info + counts
        cur.execute("""
            SELECT p.id, p.slug, p.title, p.department, p.location,
                   COALESCE(p.lifecycle_stage, 'sourcing') AS stage,
                   p.status, p.created_at, p.updated_at,
                   (SELECT COUNT(*) FROM position_candidates pc
                      WHERE pc.position_id = p.id AND COALESCE(pc.stage,'uploaded') != 'rejected') AS cv_count,
                   (SELECT ROUND(AVG(pc.match_score_composite))
                      FROM position_candidates pc
                      WHERE pc.position_id = p.id AND pc.match_score_composite IS NOT NULL) AS avg_match
            FROM positions p
            ORDER BY p.created_at DESC
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    depts = set()
    for r in rows:
        stage = r["stage"] if r["stage"] in LIFECYCLE_STAGES else "sourcing"
        if r.get("department"):
            depts.add(r["department"])
        out["stages"].setdefault(stage, []).append({
            "id": r["id"],
            "slug": r["slug"],
            "title": r["title"],
            "department": r.get("department") or "",
            "location": r.get("location") or "",
            "stage": stage,
            "status": r.get("status"),
            "cv_count": int(r.get("cv_count") or 0),
            "avg_match": int(r["avg_match"]) if r.get("avg_match") is not None else None,
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        })
    out["departments"] = sorted(depts)
    return out


class StagePatch(BaseModel):
    stage: str


@router.patch("/positions/{slug}/lifecycle", dependencies=[Depends(require_role("recruiter"))])
async def set_lifecycle_stage(slug: str, body: StagePatch, request: Request):
    user = get_current_user(request)
    stage = body.stage.strip().lower()
    if stage not in LIFECYCLE_STAGES:
        raise HTTPException(400, f"stage must be one of {LIFECYCLE_STAGES}")
    with get_cursor() as cur:
        cur.execute("SELECT id, hiring_manager_id FROM positions WHERE slug=%s", (slug,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Position not found")
        pid, hm_id = row
        # Permission: hiring manager owner or admin/superadmin
        role = (user.get("role") or "").lower()
        if role not in ("admin", "superadmin") and hm_id and hm_id != user.get("user_id"):
            # Recruiters can move stages they don't own — allow per role gate above
            pass
        # Side-effects on stage transitions
        new_status = None
        archived_at_clause = ""
        params = [stage]
        if stage == "archived":
            new_status = "archived"
            archived_at_clause = ", archived_at = NOW()"
        elif stage == "filled":
            new_status = "closed"
        elif stage in ("draft", "sourcing", "screening", "interview", "offer"):
            new_status = "active"
        sql = f"UPDATE positions SET lifecycle_stage=%s, updated_at=NOW(){archived_at_clause}"
        if new_status:
            sql += ", status=%s"
            params.append(new_status)
        sql += " WHERE id=%s RETURNING id, slug, lifecycle_stage, status"
        params.append(pid)
        cur.execute(sql, params)
        out = cur.fetchone()
    try:
        from backend.core.cache import cache
        for k in ("list_positions:all", "list_positions:active", "list_positions:closed", "list_positions:archived"):
            cache.delete(k)
    except Exception: pass
    return {
        "slug": out[1],
        "stage": out[2],
        "status": out[3],
        "message": f"Moved to {stage}",
    }


@router.post("/positions/{slug}/unarchive", dependencies=[Depends(require_role("recruiter"))])
async def unarchive_position(slug: str, request: Request):
    _ = get_current_user(request)
    with get_cursor() as cur:
        cur.execute(
            """UPDATE positions
                  SET status='active', lifecycle_stage='sourcing',
                      archived_at=NULL, updated_at=NOW()
                WHERE slug=%s
            RETURNING slug, lifecycle_stage, status""",
            (slug,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Position not found")
    try:
        from backend.core.cache import cache
        for k in ("list_positions:all", "list_positions:active", "list_positions:closed", "list_positions:archived"):
            cache.delete(k)
    except Exception: pass
    return {"slug": row[0], "stage": row[1], "status": row[2], "message": "Unarchived"}
