"""Brain & Q&A endpoints — admin doc upload, unanswered question review,
recruiter Q&A queue + retrieval, FAQ list.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Body
from pydantic import BaseModel

from backend.core.auth import get_current_user, require_role
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)

# Two routers so we can mount with different prefixes / role gates
admin_router = APIRouter()    # mounted at /api/admin/brain
qa_router = APIRouter()       # mounted at /api/qa
faq_router = APIRouter()      # mounted at /api/faq

BRAIN_DIR = Path(os.getenv("BRAIN_UPLOAD_DIR", "/data/brain"))
ALLOWED_EXT = {".pdf", ".docx", ".doc", ".txt"}
MAX_BYTES = 25 * 1024 * 1024  # 25MB


# ---------------------------------------------------------------------------
# Admin — Brain doc upload + unanswered review
# ---------------------------------------------------------------------------
@admin_router.post("/upload")
async def brain_upload(request: Request, file: UploadFile = File(...)):
    """Upload an HR policy doc — written to disk + queued for doc-ingestor agent."""
    user = require_role("admin", "superadmin")(request)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(415, f"Unsupported file type: {suffix}. Allowed: {sorted(ALLOWED_EXT)}")
    try:
        BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(500, f"brain dir not writable: {e}")
    import secrets
    fname = f"{secrets.token_urlsafe(16)}{suffix}"
    fpath = (BRAIN_DIR / fname).resolve()
    # Defense-in-depth: ensure resolved path stays within BRAIN_DIR (no traversal)
    if not str(fpath).startswith(str(BRAIN_DIR.resolve()) + os.sep):
        raise HTTPException(400, "invalid file path")
    written = 0
    try:
        with open(fpath, "wb") as out:
            while True:
                chunk = await file.read(1 << 20)  # 1 MB
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_BYTES:
                    out.close()
                    try: fpath.unlink()
                    except Exception: pass
                    raise HTTPException(413, "File too large (>25MB)")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"write failed: {e}")

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO org_brain_uploads (file_path, uploaded_by_id, status)
               VALUES (%s, %s, 'pending') RETURNING id""",
            (str(fpath), user.get("user_id")),
        )
        row = cur.fetchone()
        upload_id = row[0] if row else None

    return {
        "ok": True,
        "upload_id": upload_id,
        "file_path": str(fpath),
        "size_bytes": written,
        "status": "pending",
        "original_filename": file.filename,
    }


@admin_router.get("/unanswered")
async def list_unanswered(request: Request, limit: int = 100, include_addressed: bool = False):
    require_role("admin", "superadmin")(request)
    with get_cursor() as cur:
        if include_addressed:
            cur.execute(
                """SELECT id, question, session_id, asked_at, addressed,
                          addressed_at, addressed_by_id
                   FROM brain_unanswered
                   ORDER BY asked_at DESC LIMIT %s""",
                (limit,),
            )
        else:
            cur.execute(
                """SELECT id, question, session_id, asked_at, addressed,
                          addressed_at, addressed_by_id
                   FROM brain_unanswered
                   WHERE addressed = FALSE
                   ORDER BY asked_at DESC LIMIT %s""",
                (limit,),
            )
        rows = cur.fetchall()
    out = [
        {
            "id": r[0], "question": r[1], "session_id": r[2],
            "asked_at": r[3].isoformat() if r[3] else None,
            "addressed": r[4],
            "addressed_at": r[5].isoformat() if r[5] else None,
            "addressed_by_id": r[6],
        }
        for r in rows
    ]
    return {"items": out, "count": len(out)}


@admin_router.post("/unanswered/{uid}/address")
async def address_unanswered(request: Request, uid: int):
    user = require_role("admin", "superadmin")(request)
    with get_cursor() as cur:
        cur.execute(
            """UPDATE brain_unanswered
               SET addressed = TRUE, addressed_at = NOW(), addressed_by_id = %s
               WHERE id = %s
               RETURNING id""",
            (user.get("user_id"), uid),
        )
        if not cur.fetchone():
            raise HTTPException(404, "unanswered question not found")
    return {"ok": True, "id": uid, "addressed": True}


@admin_router.get("/uploads")
async def list_uploads(request: Request, limit: int = 50):
    require_role("admin", "superadmin")(request)
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, file_path, uploaded_by_id, uploaded_at, status,
                      chunks_created, error
               FROM org_brain_uploads
               ORDER BY uploaded_at DESC LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()
    return {
        "items": [
            {
                "id": r[0], "file_path": r[1], "uploaded_by_id": r[2],
                "uploaded_at": r[3].isoformat() if r[3] else None,
                "status": r[4], "chunks_created": r[5], "error": r[6],
            } for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Q&A Suggester
# ---------------------------------------------------------------------------
class QABody(BaseModel):
    candidate_id: int
    position_id: int


@qa_router.post("/queue")
async def queue_qa(request: Request, body: QABody):
    user = require_role("recruiter", "hiring_manager", "admin", "superadmin")(request)
    with get_cursor() as cur:
        # Dedup: if there is a recent (last 5min) unfulfilled request for same pair, return that
        cur.execute(
            """SELECT id FROM qa_suggestion_queue
               WHERE candidate_id=%s AND position_id=%s
                 AND fulfilled = FALSE
                 AND requested_at > NOW() - INTERVAL '5 minutes'
               ORDER BY requested_at DESC LIMIT 1""",
            (body.candidate_id, body.position_id),
        )
        row = cur.fetchone()
        if row:
            return {"ok": True, "id": row[0], "queued": False, "deduped": True}
        cur.execute(
            """INSERT INTO qa_suggestion_queue (candidate_id, position_id)
               VALUES (%s, %s) RETURNING id""",
            (body.candidate_id, body.position_id),
        )
        row = cur.fetchone()
    return {"ok": True, "id": row[0] if row else None, "queued": True}


@qa_router.get("/{candidate_id}/{position_id}")
async def get_qa(request: Request, candidate_id: int, position_id: int):
    require_role("recruiter", "hiring_manager", "admin", "superadmin")(request)
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, suggestions, fulfilled, requested_at
               FROM qa_suggestion_queue
               WHERE candidate_id=%s AND position_id=%s
               ORDER BY requested_at DESC LIMIT 1""",
            (candidate_id, position_id),
        )
        r = cur.fetchone()
    if not r:
        return {"id": None, "suggestions": [], "fulfilled": False, "status": "none"}
    return {
        "id": r[0],
        "suggestions": r[1] or [],
        "fulfilled": r[2],
        "requested_at": r[3].isoformat() if r[3] else None,
        "status": "ready" if r[2] else "pending",
    }


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------
@faq_router.get("/")
async def list_faq(request: Request, limit: int = 50):
    get_current_user(request)
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, question, answer, cluster_size, last_built_at
               FROM faq_entries
               ORDER BY cluster_size DESC, last_built_at DESC LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()
    return {
        "items": [
            {
                "id": r[0], "question": r[1], "answer": r[2],
                "cluster_size": r[3],
                "last_built_at": r[4].isoformat() if r[4] else None,
            } for r in rows
        ],
        "count": len(rows),
    }
