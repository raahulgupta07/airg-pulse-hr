"""Unified ingest endpoint — single drop zone for any HR document."""
from __future__ import annotations

import os
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException, Query, Form
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.core.database import get_cursor
from backend.core.permissions import require_role
from backend.agents.ingest import ingest_file

logger = logging.getLogger(__name__)
router = APIRouter()

_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(_ROOT / "data")))
INGEST_DIR = DATA_DIR / "ingest"
INGEST_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/", dependencies=[Depends(require_role("recruiter"))])
async def ingest_endpoint(
    request: Request,
    files: list[UploadFile] = File(...),
    force_type: Optional[str] = Form(None),
    auto_process: bool = Form(True),
    raw_only: bool = Form(False),
):
    """Upload one or more files; agent classifies + routes.

    If auto_process=False, just stage file + create stub candidate; user runs pipeline manually.
    """
    user = get_current_user(request)
    results = []
    for file in files:
        ext = Path(file.filename or "").suffix.lower()
        file_id = str(uuid.uuid4())
        save_path = INGEST_DIR / f"{file_id}{ext}"
        content = await file.read()
        save_path.write_bytes(content)

        try:
            r = await ingest_file(
                str(save_path), file.filename or "unknown",
                len(content), user, force_type=force_type,
                auto_process=auto_process, raw_only=raw_only,
            )
            results.append(r)
        except Exception as e:
            logger.error(f"Ingest failed for {file.filename}: {e}")
            results.append({
                "filename": file.filename, "status": "error", "error_msg": str(e),
            })
    return {"results": results, "count": len(results)}


@router.get("/log")
async def list_ingest_log(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
):
    get_current_user(request)
    conds = []; params = []
    if status:
        conds.append("status = %s"); params.append(status)
    where = "WHERE " + " AND ".join(conds) if conds else ""
    with get_cursor() as cur:
        cur.execute(f"""
            SELECT id, user_id, filename, file_size, file_type, extracted_chars,
                   classified_as, confidence, reason, pipeline, target_type,
                   target_id, status, error_msg, elapsed_ms, created_at
            FROM ingest_log {where}
            ORDER BY created_at DESC LIMIT %s
        """, (*params, limit))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("confidence") is not None:
                r["confidence"] = float(r["confidence"])
    return {"items": rows}


class ResolveRequest(BaseModel):
    classified_as: str  # CV | JD | OFFER | CERTIFICATE | OTHER


@router.post("/log/{ingest_id}/resolve", dependencies=[Depends(require_role("recruiter"))])
async def resolve_pending(ingest_id: int, body: ResolveRequest, request: Request):
    """Force-classify a pending review item; re-runs the appropriate router."""
    user = get_current_user(request)
    with get_cursor() as cur:
        cur.execute("SELECT filename, file_path, raw_text, file_size FROM ingest_log WHERE id = %s AND status = 'pending_review'",
                    (ingest_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Pending item not found")
        filename, file_path, raw_text, file_size = row
    r = await ingest_file(file_path, filename, file_size or 0, user, force_type=body.classified_as)
    with get_cursor() as cur:
        cur.execute("UPDATE ingest_log SET status = 'resolved', decided_by = %s, decided_at = NOW() WHERE id = %s",
                    (user.get("user_id"), ingest_id))
    return r


@router.delete("/log/{ingest_id}", dependencies=[Depends(require_role("recruiter"))])
async def dismiss_pending(ingest_id: int, request: Request):
    user = get_current_user(request)
    with get_cursor() as cur:
        cur.execute("UPDATE ingest_log SET status = 'dismissed', decided_by = %s, decided_at = NOW() WHERE id = %s RETURNING id",
                    (user.get("user_id"), ingest_id))
        if not cur.fetchone():
            raise HTTPException(404, "Not found")
    return {"id": ingest_id, "dismissed": True}
