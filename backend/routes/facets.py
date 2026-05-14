"""
facets — Self-growing AI filter facet API.

GET  /api/facets?type=skill&limit=50&search=python
GET  /api/facets/groups
POST /api/facets/dismiss/{id}
POST /api/facets/recompute   (admin)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.database import get_conn
from backend.core.permissions import require_role

logger = logging.getLogger(__name__)

router = APIRouter()

CV_FACET_TYPES = ("skill", "company", "location", "language", "cert", "education")
JD_FACET_TYPES = ("jd_skill", "jd_dept", "jd_location", "jd_employment_type", "jd_seniority")
FACET_TYPES = CV_FACET_TYPES + JD_FACET_TYPES


def _autofade_old_new() -> int:
    """Clear is_new for entries older than 7 days. Fast UPDATE."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE facet_options
                       SET is_new = FALSE
                     WHERE is_new = TRUE
                       AND added_at < NOW() - INTERVAL '7 days'
                    """
                )
                n = cur.rowcount or 0
            conn.commit()
        return n
    except Exception as e:
        logger.warning(f"autofade failed: {e}")
        return 0


@router.get("")
@router.get("/")
def list_facets(
    type: str = Query(..., description="skill|company|location|language|cert|education"),
    limit: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
):
    if type not in FACET_TYPES:
        raise HTTPException(400, f"unknown facet type {type!r}")
    sql = (
        "SELECT id, value, canonical, count, is_new, added_at "
        "FROM facet_options WHERE facet_type = %s"
    )
    params: list = [type]
    if search:
        sql += " AND canonical ILIKE %s"
        params.append(f"%{search.strip().lower()}%")
    sql += " ORDER BY count DESC, value ASC LIMIT %s"
    params.append(limit)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        if r.get("added_at"):
            r["added_at"] = r["added_at"].isoformat()
    return rows


@router.get("/groups")
def facet_groups(domain: Optional[str] = Query(None, description="cv | jd | (default: all)")):
    """Return summary across all facet types: top-N by count, plus is_new entries.
    Pass ?domain=cv to filter to CV-only facets, ?domain=jd for JD-only."""
    _autofade_old_new()
    if domain == "cv":
        types = CV_FACET_TYPES
    elif domain == "jd":
        types = JD_FACET_TYPES
    else:
        types = FACET_TYPES
    out: dict = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for ft in types:
                cur.execute(
                    """
                    SELECT id, value, canonical, count, is_new, added_at
                      FROM facet_options
                     WHERE facet_type = %s
                     ORDER BY count DESC, value ASC
                     LIMIT 50
                    """,
                    (ft,),
                )
                cols = [d[0] for d in cur.description]
                top_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT id, value, canonical, count, is_new, added_at
                      FROM facet_options
                     WHERE facet_type = %s AND is_new = TRUE
                     ORDER BY added_at DESC
                     LIMIT 20
                    """,
                    (ft,),
                )
                cols2 = [d[0] for d in cur.description]
                new_rows = [dict(zip(cols2, r)) for r in cur.fetchall()]

                cur.execute("SELECT COUNT(*) FROM facet_options WHERE facet_type = %s", (ft,))
                total = cur.fetchone()[0]

                for collection in (top_rows, new_rows):
                    for r in collection:
                        if r.get("added_at"):
                            r["added_at"] = r["added_at"].isoformat()

                out[ft] = {"top": top_rows, "new": new_rows, "total": total}
    # Compute aggregate "new today" badge count
    new_total = sum(len(v["new"]) for v in out.values())
    return {"groups": out, "new_total": new_total}


@router.post("/dismiss/{facet_id}", dependencies=[Depends(require_role("admin"))])
def dismiss_new_badge(facet_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE facet_options SET is_new = FALSE WHERE id = %s RETURNING id",
                (facet_id,),
            )
            r = cur.fetchone()
        conn.commit()
    if not r:
        raise HTTPException(404, "facet not found")
    return {"ok": True, "id": facet_id}


@router.post("/recompute", dependencies=[Depends(require_role("admin"))])
def recompute_all(domain: Optional[str] = Query(None, description="cv | jd | (default: both)")):
    """Admin: re-run facet miner on all candidates and/or JDs."""
    from backend.agents.facet_miner import mine_all, mine_all_jds
    result: dict = {}
    if domain in (None, "cv"):
        result["cv"] = mine_all()
    if domain in (None, "jd"):
        result["jd"] = mine_all_jds()
    return result
