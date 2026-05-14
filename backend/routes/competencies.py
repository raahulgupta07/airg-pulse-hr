"""Competency library — frameworks + competencies CRUD."""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.core.database import get_cursor
from backend.core.permissions import has_min_role

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if not has_min_role(user, "admin"):
        logger.warning("rbac_denied user_id=%s role=%s path=%s requires=admin",
                       user.get("user_id"), user.get("role"), request.url.path)
        raise HTTPException(status_code=403, detail="requires admin+")
    return user


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class CompetencyCreate(BaseModel):
    framework_id: Optional[int] = None
    key: str
    label: str
    category: Optional[str] = None
    description: Optional[str] = None
    level_descriptors: Optional[dict] = None
    star_questions: Optional[list] = None
    related_keys: Optional[list[str]] = None


class CompetencyUpdate(BaseModel):
    label: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    level_descriptors: Optional[dict] = None
    star_questions: Optional[list] = None
    related_keys: Optional[list[str]] = None
    active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/")
async def list_competencies(
    request: Request,
    framework: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    active: Optional[bool] = Query(True),
):
    get_current_user(request)
    conds = []
    params: list = []
    if framework:
        conds.append("f.name = %s"); params.append(framework)
    if category:
        conds.append("c.category = %s"); params.append(category)
    if active is not None:
        conds.append("c.active = %s"); params.append(active)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    with get_cursor() as cur:
        cur.execute(f"""
            SELECT c.id, c.uuid, c.framework_id, f.name AS framework_name,
                   c.key, c.label, c.category, c.description,
                   c.level_descriptors, c.star_questions, c.related_keys,
                   c.active, c.created_at
            FROM competencies c
            LEFT JOIN competency_frameworks f ON f.id = c.framework_id
            {where}
            ORDER BY c.category NULLS LAST, c.label
        """, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"competencies": rows, "total": len(rows)}


@router.get("/frameworks")
async def list_frameworks(request: Request):
    get_current_user(request)
    with get_cursor() as cur:
        cur.execute("""
            SELECT f.id, f.name, f.description, f.is_default, f.created_at,
                   COUNT(c.id) FILTER (WHERE c.active) AS competencies_count
            FROM competency_frameworks f
            LEFT JOIN competencies c ON c.framework_id = f.id
            GROUP BY f.id
            ORDER BY f.is_default DESC, f.name
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"frameworks": rows}


@router.post("/")
async def create_competency(body: CompetencyCreate, request: Request):
    user = _require_admin(request)
    fid = body.framework_id
    if fid is None:
        with get_cursor() as cur:
            cur.execute("SELECT id FROM competency_frameworks WHERE is_default = TRUE LIMIT 1")
            row = cur.fetchone()
            if not row:
                raise HTTPException(400, "No default framework configured")
            fid = row[0]
    with get_cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO competencies (framework_id, key, label, category, description,
                    level_descriptors, star_questions, related_keys)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                RETURNING id
            """, (
                fid, body.key, body.label, body.category, body.description,
                json.dumps(body.level_descriptors or {}),
                json.dumps(body.star_questions or []),
                body.related_keys or [],
            ))
            new_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
                (user.get("user_id"), "COMPETENCY_CREATE", "competencies", new_id,
                 json.dumps({"key": body.key})),
            )
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                raise HTTPException(409, "Competency key already exists in this framework")
            raise
    return {"id": new_id, "message": "created"}


@router.put("/{comp_id}")
async def update_competency(comp_id: int, body: CompetencyUpdate, request: Request):
    user = _require_admin(request)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    sets, params = [], []
    for k, v in fields.items():
        if k in ("level_descriptors", "star_questions"):
            sets.append(f"{k} = %s::jsonb"); params.append(json.dumps(v))
        else:
            sets.append(f"{k} = %s"); params.append(v)
    params.append(comp_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE competencies SET {', '.join(sets)} WHERE id = %s RETURNING id", params)
        if not cur.fetchone():
            raise HTTPException(404, "Competency not found")
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
            (user.get("user_id"), "COMPETENCY_UPDATE", "competencies", comp_id, json.dumps(fields)),
        )
    return {"id": comp_id, "message": "updated"}


@router.delete("/{comp_id}")
async def delete_competency(comp_id: int, request: Request):
    user = _require_admin(request)
    with get_cursor() as cur:
        cur.execute("UPDATE competencies SET active = FALSE WHERE id = %s RETURNING id", (comp_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Competency not found")
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
            (user.get("user_id"), "COMPETENCY_DELETE", "competencies", comp_id, json.dumps({"soft": True})),
        )
    return {"id": comp_id, "message": "deactivated"}
