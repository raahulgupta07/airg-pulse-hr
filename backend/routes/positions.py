"""Position routes — CRUD, JD management, team, weights."""
from __future__ import annotations

import re
import os
import time as _time
import hmac as _hmac
import hashlib as _hashlib
import json
import asyncio
import csv as _csv
import io as _io
import logging
from typing import Optional

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.core.permissions import (
    has_min_role,
    require_role,
    ensure_owner_or_min,
)
from backend.core.database import (
    insert_position, get_position, list_positions,
    get_position_candidates, get_pipeline_counts,
    insert_candidate, add_candidate_to_position,
    get_cursor, get_candidate,
)
from backend.core.config import llm_call, embed_text, CHAT_MODEL
from backend.core.rate_limit import limiter
from backend.routes.matching import score_candidate_against_position
from backend.routes.notifications import create_notification
from backend.routes.evaluation import auto_generate_rubrics, match_template_to_position

logger = logging.getLogger(__name__)
router = APIRouter()


async def _safe_background(coro, name="task"):
    try:
        await coro
    except Exception as e:
        logger.error(f"Background {name} failed: {e}")


# ---------------------------------------------------------------------------
# SSE signed-URL helpers (mirrors /candidates/.../file/sign HMAC pattern)
# ---------------------------------------------------------------------------
SSE_SIGN_TTL = 5 * 60  # 5 minutes


def _sse_sign_secret() -> bytes:
    secret = os.getenv("FILE_SIGN_SECRET") or os.getenv("JWT_SECRET") or "dev-insecure-fallback"
    return secret.encode() if isinstance(secret, str) else secret


def _compute_sse_sig(slug: str, user_id: int | str, exp: int) -> str:
    msg = f"{slug}:{user_id}:{exp}".encode()
    return _hmac.new(_sse_sign_secret(), msg, _hashlib.sha256).hexdigest()


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


class CreatePositionRequest(BaseModel):
    title: str
    department: str = ""
    location: str = ""
    employment_type: str = "full-time"
    icon: str = "💼"
    jd_text: str = ""
    required_skills: list[str] = []
    nice_to_have_skills: list[str] = []
    min_experience_years: int = 0
    education_level: str = ""
    industry_keywords: list[str] = []
    weight_skills: int = 40
    weight_experience: int = 25
    weight_education: int = 10
    weight_certifications: int = 10
    weight_industry: int = 15
    min_match_score: int = 50


class UpdateWeightsRequest(BaseModel):
    weight_skills: int = 40
    weight_experience: int = 25
    weight_education: int = 10
    weight_certifications: int = 10
    weight_industry: int = 15
    min_match_score: int = 50


@router.get("/")
async def list_positions_route(
    request: Request,
    status: Optional[str] = Query(None),
):
    """List all positions with candidate counts."""
    get_current_user(request)

    from backend.core.cache import cache
    cache_key = f"list_positions:{status or 'all'}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    positions = list_positions(status=status)
    result = {"positions": positions}
    cache.set(cache_key, result, ttl=10)
    return result


@router.post("/", dependencies=[Depends(require_role("hiring_manager"))])
async def create_position(body: CreatePositionRequest, request: Request):
    """Create a new position with optional JD."""
    user = get_current_user(request)

    slug = slugify(body.title)

    # Check duplicate
    existing = get_position(slug)
    if existing:
        # Append number
        import time
        slug = f"{slug}-{int(time.time()) % 10000}"

    data = {
        "slug": slug,
        "title": body.title,
        "department": body.department,
        "location": body.location,
        "employment_type": body.employment_type,
        "hiring_manager_id": user.get("user_id"),
        "status": "active",
        "icon": body.icon,
        "jd_text": body.jd_text or None,
        "required_skills": body.required_skills,
        "nice_to_have_skills": body.nice_to_have_skills,
        "min_experience_years": body.min_experience_years,
        "education_level": body.education_level,
        "industry_keywords": body.industry_keywords,
        "weight_skills": body.weight_skills,
        "weight_experience": body.weight_experience,
        "weight_education": body.weight_education,
        "weight_certifications": body.weight_certifications,
        "weight_industry": body.weight_industry,
        "min_match_score": body.min_match_score,
    }

    position_id = insert_position(data)

    # If JD provided, extract requirements and embed
    if body.jd_text:
        try:
            await _extract_and_embed_jd(slug, body.jd_text)
        except Exception as e:
            logger.warning(f"JD processing failed for {slug}: {e}")
        # Auto-scan CVs in background. Pre-create scan row so /ai endpoint
        # surfaces 'queued' state immediately.
        _scan_id = _create_ai_scan_row(position_id)
        asyncio.create_task(_safe_background(
            auto_scan_for_position(position_id, slug, scan_id=_scan_id, match_source="auto_scan_on_create"),
            "auto_scan",
        ))
    # Always enqueue background sync scan (uses sync agent, dedup'd)
    try:
        from backend.agents.sync import enqueue_dedup
        enqueue_dedup("auto_scan_position", {"position_id": position_id})
    except Exception as e:
        logger.warning(f"enqueue auto_scan failed: {e}")

    return {"position_id": position_id, "slug": slug, "message": "Position created"}


@router.get("/templates")
async def list_position_templates(request: Request):
    """List all position templates."""
    get_current_user(request)
    from backend.core.database import get_cursor
    with get_cursor() as cur:
        cur.execute("""
            SELECT id, name, title, department, employment_type,
                   required_skills, nice_to_have_skills, min_experience_years,
                   weight_skills, weight_experience, weight_education,
                   weight_certifications, weight_industry, created_at
            FROM position_templates
            ORDER BY created_at DESC
        """)
        cols = [desc[0] for desc in cur.description]
        templates = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"templates": templates}


@router.post("/templates", dependencies=[Depends(require_role("hiring_manager"))])
async def create_position_template(request: Request):
    """Save a position as a reusable template."""
    user = get_current_user(request)
    body = await request.json()
    name = body.get("name")
    from_slug = body.get("from_slug")

    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not from_slug:
        raise HTTPException(status_code=400, detail="from_slug is required")

    position = get_position(from_slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    from backend.core.database import get_cursor
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO position_templates (
                name, title, department, employment_type, jd_text,
                required_skills, nice_to_have_skills, min_experience_years,
                weight_skills, weight_experience, weight_education,
                weight_certifications, weight_industry, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """, (
            name,
            position.get("title", ""),
            position.get("department", ""),
            position.get("employment_type", "full-time"),
            position.get("jd_text"),
            position.get("required_skills", []),
            position.get("nice_to_have_skills", []),
            position.get("min_experience_years", 0),
            position.get("weight_skills", 40),
            position.get("weight_experience", 25),
            position.get("weight_education", 10),
            position.get("weight_certifications", 10),
            position.get("weight_industry", 15),
            user.get("user_id"),
        ))
        row = cur.fetchone()

    return {"id": row[0], "created_at": row[1], "message": "Template saved"}


@router.post("/from-template/{template_id}", dependencies=[Depends(require_role("hiring_manager"))])
async def create_from_template(template_id: int, request: Request):
    """Create a new position from a template."""
    user = get_current_user(request)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}

    from backend.core.database import get_cursor
    with get_cursor() as cur:
        cur.execute("SELECT * FROM position_templates WHERE id = %s", (template_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Template not found")
        cols = [desc[0] for desc in cur.description]
        tpl = dict(zip(cols, row))

    title = body.get("title", tpl["title"])
    slug = slugify(title)

    existing = get_position(slug)
    if existing:
        import time
        slug = f"{slug}-{int(time.time()) % 10000}"

    data = {
        "slug": slug,
        "title": title,
        "department": body.get("department", tpl.get("department", "")),
        "location": body.get("location", ""),
        "employment_type": tpl.get("employment_type", "full-time"),
        "hiring_manager_id": user.get("user_id"),
        "status": "active",
        "icon": body.get("icon", "💼"),
        "jd_text": tpl.get("jd_text"),
        "required_skills": tpl.get("required_skills", []),
        "nice_to_have_skills": tpl.get("nice_to_have_skills", []),
        "min_experience_years": tpl.get("min_experience_years", 0),
        "education_level": "",
        "industry_keywords": [],
        "weight_skills": tpl.get("weight_skills", 40),
        "weight_experience": tpl.get("weight_experience", 25),
        "weight_education": tpl.get("weight_education", 10),
        "weight_certifications": tpl.get("weight_certifications", 10),
        "weight_industry": tpl.get("weight_industry", 15),
        "min_match_score": 50,
    }

    position_id = insert_position(data)

    return {"position_id": position_id, "slug": slug, "message": "Position created from template"}


@router.post("/{slug}/archive")
async def archive_position(slug: str, request: Request):
    """Archive (close) a position."""
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if not has_min_role(user, "admin"):
        from backend.core.permissions import _log_denied
        _log_denied(user, request, "admin")
        raise HTTPException(403, "requires admin+ to archive position")

    from backend.core.database import get_cursor
    with get_cursor() as cur:
        cur.execute(
            "UPDATE positions SET status = 'closed', updated_at = NOW() WHERE id = %s",
            (position["id"],),
        )
    return {"message": "Position archived", "slug": slug}


@router.delete("/{slug}")
async def delete_position(slug: str, request: Request, hard: bool = Query(False)):
    """Soft-archive (default) or hard-delete with ?hard=true. Creator or superadmin only."""
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    from backend.core.database import get_cursor
    if hard:
        if user.get("role") != "superadmin":
            from backend.core.permissions import _log_denied
            _log_denied(user, request, "superadmin")
            raise HTTPException(403, "Only superadmin can hard-delete a position")
        pid = position["id"]
        # Cascade delete from all FK-referencing tables (positions has 20 FK refs).
        # Single transaction so partial deletes can't orphan rows.
        cascade_tables = [
            "candidate_activity", "candidate_flags", "candidate_notes",
            "chat_sessions", "email_log",
            "evaluation_consensus", "evaluation_rubrics",
            "generated_documents",
            "hr_brain", "hr_brain_learnings",
            "interview_questions",
            "position_ai_scans", "position_candidates", "position_competencies",
            "position_members",
            "qoh_reviews", "recruitment_costs", "referrals",
            "screening_answers", "screening_questions",
        ]
        with get_cursor() as cur:
            for tbl in cascade_tables:
                try:
                    cur.execute(f"DELETE FROM {tbl} WHERE position_id = %s", (pid,))
                except Exception as _e:
                    logger.warning(f"[delete_position] cascade {tbl} failed: {_e}")
            cur.execute("DELETE FROM positions WHERE id = %s", (pid,))
        # Invalidate position list cache (10s TTL otherwise = stale UI after delete)
        try:
            from backend.core.cache import cache
            for k in ("list_positions:all", "list_positions:active", "list_positions:closed", "list_positions:archived"):
                cache.delete(k)
        except Exception: pass
        logger.info(f"[delete_position] hard-deleted position {slug} (id={pid}) + cascade")
        return {"message": f"Position {slug} hard-deleted", "hard": True, "slug": slug}

    # Soft archive — admin+ per policy
    if not has_min_role(user, "admin"):
        from backend.core.permissions import _log_denied
        _log_denied(user, request, "admin")
        raise HTTPException(403, "requires admin+ to archive position")
    with get_cursor() as cur:
        cur.execute("UPDATE positions SET status = 'closed', updated_at = NOW() WHERE id = %s", (position["id"],))
    try:
        from backend.core.cache import cache
        for k in ("list_positions:all", "list_positions:active", "list_positions:closed", "list_positions:archived"):
            cache.delete(k)
    except Exception: pass
    return {"message": "Position archived", "slug": slug}


@router.post("/{slug}/reopen", dependencies=[Depends(require_role("admin"))])
async def reopen_position(slug: str, request: Request):
    """Reopen a closed position."""
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    from backend.core.database import get_cursor
    with get_cursor() as cur:
        cur.execute(
            "UPDATE positions SET status = 'active', updated_at = NOW() WHERE id = %s",
            (position["id"],),
        )
    return {"message": "Position reopened", "slug": slug}


@router.get("/{slug}")
async def get_position_route(slug: str, request: Request):
    """Get position details with candidate stats."""
    get_current_user(request)

    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    # Get pipeline counts
    pipeline = get_pipeline_counts(position["id"])
    position["pipeline"] = pipeline
    position["cv_count"] = sum(pipeline.values())

    return position


@router.patch("/{slug}")
async def update_position(slug: str, request: Request):
    """Update position fields."""
    user = get_current_user(request)
    body = await request.json()

    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)

    allowed = {
        "title", "department", "location", "employment_type", "status", "icon",
        "jd_text", "required_skills", "nice_to_have_skills",
        "min_experience_years", "education_level", "industry_keywords",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields")

    from backend.core.database import get_cursor
    set_parts = []
    values = []
    for k, v in updates.items():
        if isinstance(v, (list, dict)):
            set_parts.append(f"{k} = %s")
            values.append(json.dumps(v) if isinstance(v, dict) else v)
        else:
            set_parts.append(f"{k} = %s")
            values.append(v)

    set_parts.append("updated_at = NOW()")
    values.append(position["id"])

    with get_cursor() as cur:
        cur.execute(
            f"UPDATE positions SET {', '.join(set_parts)} WHERE id = %s",
            values,
        )

    # Re-embed JD if changed
    jd_text = updates.get("jd_text")
    if jd_text:
        try:
            await _extract_and_embed_jd(slug, jd_text)
        except Exception as e:
            logger.warning(f"JD re-processing failed: {e}")
        # Auto-generate evaluation rubrics from JD
        try:
            if jd_text:
                auto_generate_rubrics(position["id"], jd_text)
        except Exception as e:
            logger.warning(f"Auto rubric generation failed: {e}")
        # Auto-scan CVs in background
        _scan_id = _create_ai_scan_row(position["id"])
        asyncio.create_task(_safe_background(
            auto_scan_for_position(position["id"], slug, scan_id=_scan_id, match_source="auto_scan_on_jd_update"),
            "auto_scan",
        ))

    return {"message": "Position updated"}


@router.put("/{slug}/weights")
async def update_weights(slug: str, body: UpdateWeightsRequest, request: Request):
    """Update scoring weights for a position."""
    user = get_current_user(request)

    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)

    total = body.weight_skills + body.weight_experience + body.weight_education + body.weight_certifications + body.weight_industry
    if total != 100:
        raise HTTPException(status_code=400, detail=f"Weights must sum to 100, got {total}")

    from backend.core.database import get_cursor
    with get_cursor() as cur:
        cur.execute("""
            UPDATE positions SET
                weight_skills = %s, weight_experience = %s, weight_education = %s,
                weight_certifications = %s, weight_industry = %s, min_match_score = %s,
                weights_overridden = TRUE,
                updated_at = NOW()
            WHERE id = %s
        """, (
            body.weight_skills, body.weight_experience, body.weight_education,
            body.weight_certifications, body.weight_industry, body.min_match_score,
            position["id"],
        ))

    return {"message": "Weights updated"}


# ---------------------------------------------------------------------------
# Position weights — full PATCH (incl. culture + knockout + override flag)
# ---------------------------------------------------------------------------
class PositionWeightsPatch(BaseModel):
    weight_skills: Optional[float] = None
    weight_experience: Optional[float] = None
    weight_industry: Optional[float] = None
    weight_education: Optional[float] = None
    weight_certifications: Optional[float] = None
    weight_culture: Optional[float] = None
    knockout_threshold: Optional[float] = None
    weights_overridden: Optional[bool] = None
    reset_from_jd: bool = False
    normalize: bool = True


@router.patch("/{slug}/weights")
async def patch_position_weights(slug: str, body: PositionWeightsPatch, request: Request):
    user = get_current_user(request)
    from backend.core.database import get_cursor as _gc
    with _gc() as cur:
        cur.execute("SELECT * FROM positions WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Position not found")
        cols = [d[0] for d in cur.description]
        pos = dict(zip(cols, row))
        ensure_owner_or_min(user, pos.get("hiring_manager_id"), "admin", request)

        # Reset from JD: pull weights from source JD
        if body.reset_from_jd and pos.get("weights_source_jd_id"):
            cur.execute("""
                SELECT weight_skills, weight_experience, weight_industry, weight_education,
                       weight_certifications, weight_culture, knockout_threshold
                FROM jd_repository WHERE id = %s
            """, (pos["weights_source_jd_id"],))
            jd_row = cur.fetchone()
            if jd_row:
                cur.execute("""
                    UPDATE positions SET
                        weight_skills = %s, weight_experience = %s, weight_industry = %s,
                        weight_education = %s, weight_certifications = %s, weight_culture = %s,
                        knockout_threshold = %s, weights_overridden = FALSE,
                        updated_at = NOW()
                    WHERE slug = %s
                """, (*jd_row, slug))
                return {"slug": slug, "reset": True}
            raise HTTPException(404, "Source JD not found")

        # Check JD lock — skip locked dims
        locked_dims = []
        jd_locked = False
        if pos.get("weights_source_jd_id"):
            cur.execute("SELECT weights_locked, weights_locked_dims FROM jd_repository WHERE id = %s",
                        (pos["weights_source_jd_id"],))
            jd_row = cur.fetchone()
            if jd_row:
                jd_locked = bool(jd_row[0])
                ld = jd_row[1] or []
                if isinstance(ld, str):
                    import json as _j2
                    try: ld = _j2.loads(ld)
                    except Exception: ld = []
                locked_dims = ld
        if jd_locked:
            raise HTTPException(403, "JD weights are locked — cannot override")

        merged = {k: float(pos.get(k) or 0) for k in (
            "weight_skills","weight_experience","weight_industry",
            "weight_education","weight_certifications","weight_culture")}
        fields = body.model_dump(exclude_none=True)
        skipped_locked = []
        for k, v in fields.items():
            if k in merged:
                dim = k.replace("weight_", "")
                if dim in locked_dims:
                    skipped_locked.append(dim); continue
                merged[k] = float(v)

        if body.normalize:
            total = sum(merged.values())
            if total > 0:
                merged = {k: round(v * 100.0 / total, 2) for k, v in merged.items()}

        sets, params = [], []
        for k, v in merged.items():
            sets.append(f"{k} = %s"); params.append(v)
        if body.knockout_threshold is not None:
            sets.append("knockout_threshold = %s"); params.append(body.knockout_threshold)
        sets.append("weights_overridden = TRUE")
        sets.append("updated_at = NOW()")
        params.append(slug)
        cur.execute(f"UPDATE positions SET {', '.join(sets)} WHERE slug = %s", params)

        import json as _json
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
            (user.get("user_id"), "POSITION_WEIGHTS_UPDATE", "positions", pos["id"], _json.dumps(merged)),
        )
    try:
        from backend.agents.sync import enqueue_dedup
        enqueue_dedup("auto_rescore_position", {"position_id": pos["id"]})
    except Exception as e:
        logger.warning(f"enqueue auto_rescore_position failed: {e}")
    return {"slug": slug, **merged, "weights_overridden": True}


class PositionPresetRequest(BaseModel):
    profile: str


@router.post("/{slug}/preset")
async def apply_position_preset(slug: str, body: PositionPresetRequest, request: Request):
    from backend.routes.jd_repo import SCORING_PRESETS
    if body.profile not in SCORING_PRESETS:
        raise HTTPException(400, f"Unknown profile. Choose: {', '.join(SCORING_PRESETS)}")
    p = SCORING_PRESETS[body.profile]
    patch = PositionWeightsPatch(**p, normalize=False)
    return await patch_position_weights(slug, patch, request)


@router.get("/{slug}/candidates")
async def get_candidates_for_position(
    slug: str,
    request: Request,
    stage: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """Get ranked candidates for a position."""
    get_current_user(request)

    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    candidates = get_position_candidates(
        position["id"], stage=stage, limit=limit, offset=offset,
    )
    pipeline = get_pipeline_counts(position["id"])

    return {"candidates": candidates, "pipeline": pipeline}


@router.post("/{slug}/upload-cvs")
async def upload_cvs_to_position(
    slug: str,
    request: Request,
    files: list[UploadFile] = File(...),
):
    """Upload CVs to a position — saves to central repo AND links to this position."""
    user = get_current_user(request)
    if not has_min_role(user, "recruiter"):
        from backend.core.permissions import _log_denied
        _log_denied(user, request, "recruiter")
        raise HTTPException(403, "requires recruiter+")

    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    import os
    _PROJECT_ROOT = Path(__file__).parent.parent.parent
    CV_DIR = Path(os.getenv("DATA_DIR", str(_PROJECT_ROOT / "data"))) / "cvs"
    CV_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for file in files:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in {".pdf", ".docx", ".doc"}:
            results.append({"filename": file.filename, "status": "error", "error": f"Only PDF and DOCX supported, got {ext}"})
            continue

        # Read and validate file content
        content = await file.read()

        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
        if len(content) > MAX_FILE_SIZE:
            results.append({"filename": file.filename, "status": "error", "error": f"File too large ({len(content) // 1024 // 1024}MB). Max 10MB."})
            continue

        # Validate file content (not just extension)
        if content[:4] == b'%PDF':
            pass  # valid PDF
        elif content[:2] == b'PK':
            pass  # valid DOCX (ZIP-based)
        else:
            results.append({"filename": file.filename, "status": "error", "error": "Invalid file content — only PDF and DOCX accepted"})
            continue

        # Save file
        file_id = str(uuid.uuid4())
        save_path = CV_DIR / f"{file_id}{ext}"
        save_path.write_bytes(content)

        try:
            # 1. Add to central CV repo
            candidate_id = insert_candidate({
                "name": Path(file.filename or "unknown").stem.replace("_", " ").replace("-", " ").title(),
                "email": None, "phone": None, "location": None, "linkedin_url": None,
                "current_role": None, "current_company": None,
                "total_experience_years": None, "seniority_level": None,
                "skills_technical": [], "skills_soft": [], "tools": [], "languages": [],
                "experience": "[]", "education": "[]", "certifications": "[]", "projects": "[]",
                "summary_short": None, "summary_detailed": None, "raw_text": None,
                "pdf_path": str(save_path), "file_type": ext.lstrip("."),
                "file_name": file.filename, "page_count": 0,
                "quality_score": 0, "tags": [], "source": "position_upload",
                "status": "active", "is_processed": False,
            })

            # 2. Link to this position
            add_candidate_to_position(position["id"], candidate_id, added_by="position_upload")

            # 3. Trigger processing
            import asyncio
            from backend.routes.candidates import _process_cv_background
            asyncio.create_task(_safe_background(_process_cv_background(candidate_id, str(save_path), file.filename), "cv_process"))

            results.append({"filename": file.filename, "candidate_id": candidate_id, "status": "uploaded"})
            logger.info(f"CV uploaded to position {slug}: {file.filename} -> candidate_id={candidate_id}")

        except Exception as e:
            logger.error(f"Failed to save CV: {e}")
            results.append({"filename": file.filename, "status": "error", "error": str(e)})

    return {
        "uploaded": len([r for r in results if r["status"] == "uploaded"]),
        "errors": len([r for r in results if r["status"] == "error"]),
        "results": results,
        "message": f"CVs uploaded to central repo and linked to {slug}",
    }


@router.post("/{slug}/jd/generate")
async def generate_jd(slug: str, request: Request):
    """AI-generate a JD from position details + bullet points."""
    user = get_current_user(request)
    body = await request.json()

    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)

    bullets = body.get("bullets", [])
    role = position.get("title", slug)
    dept = position.get("department", "")
    level = body.get("level", "")

    tone = body.get("tone", "professional")

    prompt = f"""Generate a comprehensive, detailed job description (500+ words).

Role: {role}
Department: {dept}
Level: {level}
Tone: {tone}
Key Points:
{chr(10).join('- ' + b for b in bullets) if bullets else '(Generate based on role title and level)'}

Structure in Markdown with ALL sections:
## About the Role (3-5 sentences — impact, team, why this matters)
## Key Responsibilities (8-12 action-oriented bullet points)
## Required Qualifications (6-10 specific must-haves with technologies and years)
## Preferred Qualifications (4-6 nice-to-haves)
## Technical Skills (list specific technologies, tools, platforms)
## What We Offer (6-8 benefits and perks)

RULES: Inclusive language, specific technologies not vague terms, verb-first responsibilities, measurable where possible."""

    jd_text = llm_call(prompt, temperature=0.4, max_tokens=4000)
    if not jd_text:
        raise HTTPException(status_code=500, detail="JD generation failed")

    # Save to position
    from backend.core.database import get_cursor
    with get_cursor() as cur:
        cur.execute(
            "UPDATE positions SET jd_text = %s, updated_at = NOW() WHERE id = %s",
            (jd_text, position["id"]),
        )

    # Extract requirements and embed
    try:
        await _extract_and_embed_jd(slug, jd_text)
    except Exception as e:
        logger.warning(f"JD extraction failed: {e}")

    # Auto-scan CVs in background
    asyncio.create_task(_safe_background(auto_scan_for_position(position["id"], slug), "auto_scan"))

    return {"jd_text": jd_text, "message": "JD generated"}


@router.post("/{slug}/jd/enhance")
async def enhance_jd(slug: str, request: Request):
    """AI-enhance an existing JD — DEI check, completeness, improvements."""
    user = get_current_user(request)

    position = get_position(slug)
    if not position or not position.get("jd_text"):
        raise HTTPException(status_code=404, detail="Position or JD not found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)

    jd = position["jd_text"]

    prompt = f"""Review and enhance this job description. Make these improvements:

1. **DEI Language**: Replace any non-inclusive terms (e.g., "rockstar" -> "talented", "manpower" -> "team")
2. **Completeness**: Add any missing standard sections
3. **Clarity**: Make requirements more specific and measurable
4. **Legal**: Remove any potentially discriminatory requirements

Current JD:
{jd}

Return the enhanced JD in Markdown. After the JD, add a section called "## Changes Made" listing what was changed."""

    enhanced = llm_call(prompt, temperature=0.3, max_tokens=3000)
    if not enhanced:
        raise HTTPException(status_code=500, detail="Enhancement failed")

    # Run compliance checks
    compliance = await _check_jd_compliance(enhanced)

    from backend.core.database import get_cursor
    with get_cursor() as cur:
        cur.execute("""
            UPDATE positions SET
                jd_text = %s, jd_enhanced = TRUE,
                dei_score = %s, legal_check = %s, completeness_score = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (
            enhanced,
            compliance.get("dei_score"),
            compliance.get("legal_pass"),
            compliance.get("completeness"),
            position["id"],
        ))

    # Auto-generate evaluation rubrics from JD
    try:
        if enhanced:
            auto_generate_rubrics(position["id"], enhanced)
    except Exception as e:
        logger.warning(f"Auto rubric generation failed: {e}")

    # Auto-scan CVs in background after JD enhancement
    asyncio.create_task(_safe_background(auto_scan_for_position(position["id"], slug), "auto_scan"))

    return {
        "jd_text": enhanced,
        "compliance": compliance,
        "message": "JD enhanced",
    }


@router.post("/{slug}/jd/extract")
async def extract_requirements(slug: str, request: Request):
    """Extract structured requirements from JD text."""
    user = get_current_user(request)

    position = get_position(slug)
    if not position or not position.get("jd_text"):
        raise HTTPException(status_code=404, detail="No JD found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)

    extracted = await _extract_jd_requirements(position["jd_text"])
    if not extracted:
        raise HTTPException(status_code=500, detail="Extraction failed")

    # Save extracted fields
    from backend.core.database import get_cursor
    with get_cursor() as cur:
        cur.execute("""
            UPDATE positions SET
                required_skills = %s, nice_to_have_skills = %s,
                min_experience_years = %s, education_level = %s,
                industry_keywords = %s, updated_at = NOW()
            WHERE id = %s
        """, (
            extracted.get("required_skills", []),
            extracted.get("nice_to_have", []),
            extracted.get("min_experience_years", 0),
            extracted.get("education_level", ""),
            extracted.get("industry_keywords", []),
            position["id"],
        ))

    return {"extracted": extracted, "message": "Requirements extracted"}


# ---------------------------------------------------------------------------
# Auto-Scan: when JD is saved, scan all processed CVs for matches
# ---------------------------------------------------------------------------
def _create_ai_scan_row(position_id: int) -> int | None:
    """Insert a queued position_ai_scans row, return its id.

    If a unique-violation fires from the partial index `uniq_pas_active`
    (mig 042 — only one queued/running scan per position), reuse the
    already-active scan id instead of erroring.
    """
    try:
        with get_cursor() as cur:
            cur.execute(
                "INSERT INTO position_ai_scans (position_id, status) VALUES (%s, 'queued') RETURNING id",
                (position_id,),
            )
            return cur.fetchone()[0]
    except Exception as e:
        # Detect unique violation on the active-scan partial index.
        msg = str(e).lower()
        is_dupe = (
            "uniq_pas_active" in msg
            or "uniqueviolation" in msg
            or "duplicate key" in msg
            or e.__class__.__name__ == "UniqueViolation"
        )
        if is_dupe:
            try:
                with get_cursor() as cur:
                    cur.execute(
                        "SELECT id FROM position_ai_scans "
                        "WHERE position_id = %s AND status IN ('queued', 'running') "
                        "ORDER BY created_at DESC LIMIT 1",
                        (position_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        existing_id = row[0]
                        logger.info(
                            f"[ai-scan] dedupe — reusing scan id={existing_id} for position={position_id}"
                        )
                        return existing_id
            except Exception as e2:
                logger.warning(f"[auto_scan] dedupe lookup failed: {e2}")
        logger.warning(f"[auto_scan] could not create scan row: {e}")
        return None


def _update_ai_scan_row(scan_id: int | None, **fields):
    """Patch a position_ai_scans row. Silently skips if scan_id is None."""
    if not scan_id or not fields:
        return
    try:
        cols = ", ".join(f"{k} = %s" for k in fields)
        with get_cursor() as cur:
            cur.execute(
                f"UPDATE position_ai_scans SET {cols} WHERE id = %s",
                (*fields.values(), scan_id),
            )
    except Exception as e:
        logger.warning(f"[auto_scan] could not update scan row {scan_id}: {e}")


async def auto_scan_for_position(
    position_id: int,
    slug: str,
    scan_id: int | None = None,
    match_source: str = "auto_scan_on_create",
):
    """Background task: score all processed CVs against this position and add top matches.

    Tracks lifecycle in position_ai_scans (queued -> running -> done/error).
    Stamps match_source on inserted position_candidates rows.
    """
    # Ensure we have a tracking row even if caller did not pre-create one
    if scan_id is None:
        scan_id = _create_ai_scan_row(position_id)

    _update_ai_scan_row(
        scan_id,
        status="running",
        started_at=__import__("datetime").datetime.utcnow(),
    )
    try:
        from backend.agents.registry import heartbeat as _hb_scan, cycle_done as _cd_scan
        _hb_scan("scan", status="running", action=f"scoring CVs for {slug}")
    except Exception:
        _hb_scan = _cd_scan = lambda *a, **kw: None  # noqa

    n_scored = 0
    n_matched = 0
    _scan_t0 = _time.time()
    logger.info(json.dumps({"event": "scan.started", "scan_id": scan_id, "position_id": position_id, "slug": slug, "match_source": match_source}))
    try:
        position = get_position(slug)
        if not position:
            logger.warning(f"[auto_scan] Position {slug} not found")
            _update_ai_scan_row(
                scan_id,
                status="error",
                error=f"position {slug} not found",
                finished_at=__import__("datetime").datetime.utcnow(),
            )
            return

        # Get all processed candidates
        with get_cursor() as cur:
            cur.execute("""
                SELECT * FROM candidates
                WHERE status = 'active' AND is_processed = TRUE
            """)
            cols = [desc[0] for desc in cur.description]
            all_candidates = [dict(zip(cols, row)) for row in cur.fetchall()]

        if not all_candidates:
            logger.info(f"[auto_scan] No processed candidates to scan for {slug}")
            _update_ai_scan_row(
                scan_id,
                status="done",
                n_scored=0,
                n_matched=0,
                finished_at=__import__("datetime").datetime.utcnow(),
            )
            return

        min_score = position.get("min_match_score", 50)
        scored = []

        for candidate in all_candidates:
            # Parse JSONB fields
            for field in ("experience", "education", "certifications", "projects"):
                val = candidate.get(field)
                if isinstance(val, str):
                    try:
                        candidate[field] = json.loads(val)
                    except json.JSONDecodeError:
                        candidate[field] = []

            scores = score_candidate_against_position(candidate, position)
            n_scored += 1
            if scores["composite"] >= min_score:
                scored.append((candidate, scores))
            # Batch progress write every 5 candidates so SSE consumers see live counter.
            if n_scored % 5 == 0:
                _update_ai_scan_row(scan_id, n_scored=n_scored)

        # Sort by composite descending, take top 20
        scored.sort(key=lambda x: x[1]["composite"], reverse=True)
        top = scored[:20]

        added = 0
        added_pc_ids: list[int] = []
        for candidate, scores in top:
            try:
                pc_id = add_candidate_to_position(
                    position_id, candidate["id"],
                    scores={
                        "composite": scores["composite"],
                        "skills": scores["skills"],
                        "experience": scores["experience"],
                        "education": scores["education"],
                        "certifications": scores["certifications"],
                        "industry": scores["industry"],
                        "semantic": None,
                        "explanation": None,
                        "skills_matched": scores.get("skills_matched", []),
                        "skills_missing": scores.get("skills_missing", []),
                    },
                    added_by="ai_auto_scan",
                )
                added += 1
                if pc_id:
                    added_pc_ids.append(pc_id)
                # Running n_matched so live UI reflects each new match.
                _update_ai_scan_row(scan_id, n_matched=added)
                logger.info(json.dumps({"event": "match.added", "scan_id": scan_id, "candidate_id": candidate["id"], "score": scores["composite"]}))
            except Exception as e:
                logger.warning(f"[auto_scan] Failed to add candidate {candidate['id']}: {e}")

        n_matched = added

        # Stamp match_source AND attachment_state='suggested' on inserted rows
        # (auto-scan output is a SUGGESTION, not an attachment until user promotes)
        if added_pc_ids:
            try:
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE position_candidates SET match_source = %s, attachment_state = 'suggested' WHERE id = ANY(%s)",
                        (match_source, added_pc_ids),
                    )
            except Exception as e:
                logger.warning(f"[auto_scan] match_source/state update failed: {e}")

        # Create notification for hiring manager
        if added > 0:
            hiring_manager_id = position.get("hiring_manager_id")
            if hiring_manager_id:
                try:
                    create_notification(
                        user_id=hiring_manager_id,
                        type="ai_scan",
                        title=f"AI found {added} matching candidates for {position.get('title', slug)}",
                        message=f"Auto-scan matched {added} candidates (from {len(all_candidates)} processed CVs) above {min_score}% threshold.",
                        link=f"/positions/{slug}",
                    )
                except Exception as e:
                    logger.warning(f"[auto_scan] Notification failed: {e}")

            # Log activity
            try:
                with get_cursor() as cur:
                    cur.execute("""
                        INSERT INTO candidate_activity (candidate_id, position_id, user_id, activity_type, details)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        top[0][0]["id"] if top else None,
                        position_id,
                        hiring_manager_id,
                        "ai_auto_scan",
                        json.dumps({"added": added, "scanned": len(all_candidates), "threshold": min_score}),
                    ))
            except Exception:
                pass

        _dur_ms = int((_time.time() - _scan_t0) * 1000)
        logger.info(f"[auto_scan] Position {slug}: scanned {len(all_candidates)}, added {added} matches")
        logger.info(json.dumps({"event": "scan.completed", "scan_id": scan_id, "n_scored": n_scored, "n_matched": n_matched, "duration_ms": _dur_ms}))
        _update_ai_scan_row(
            scan_id,
            status="done",
            n_scored=n_scored,
            n_matched=n_matched,
            finished_at=__import__("datetime").datetime.utcnow(),
        )
        try: _cd_scan("scan", events=int(n_scored or 0))
        except Exception: pass

        # Auto-generate generic interview kit if not already present (idempotent)
        try:
            from backend.routes.interview_kit import _auto_generate_kit_for_position
            import asyncio as _aio2
            n_kit = await _aio2.to_thread(_auto_generate_kit_for_position, position_id)
            if n_kit > 0:
                logger.info(f"[agent:scan] auto-generated {n_kit} interview questions for position {slug}")
        except Exception as _e:
            logger.warning(f"[agent:scan] auto interview-kit gen failed: {_e}")

    except Exception as e:
        logger.error(f"[agent:scan] failed for position {slug}: {e}")
        logger.error(json.dumps({"event": "scan.error", "scan_id": scan_id, "error": str(e)}))
        try: _cd_scan("scan", error=str(e))
        except Exception: pass
        _update_ai_scan_row(
            scan_id,
            status="error",
            error=str(e)[:500],
            n_scored=n_scored,
            n_matched=n_matched,
            finished_at=__import__("datetime").datetime.utcnow(),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
async def _extract_and_embed_jd(slug: str, jd_text: str):
    """Extract requirements from JD and create embedding."""
    # Extract requirements
    extracted = await _extract_jd_requirements(jd_text)
    if extracted:
        from backend.core.database import get_cursor
        position = get_position(slug)
        if position:
            with get_cursor() as cur:
                cur.execute("""
                    UPDATE positions SET
                        required_skills = %s, nice_to_have_skills = %s,
                        min_experience_years = %s, education_level = %s,
                        industry_keywords = %s
                    WHERE id = %s
                """, (
                    extracted.get("required_skills", []),
                    extracted.get("nice_to_have", []),
                    extracted.get("min_experience_years", 0),
                    extracted.get("education_level", ""),
                    extracted.get("industry_keywords", []),
                    position["id"],
                ))

    # Create JD embedding
    embedding = await embed_text(jd_text[:8000])  # Truncate for embedding
    if embedding:
        from backend.core.database import get_cursor
        position = get_position(slug)
        if position:
            with get_cursor() as cur:
                cur.execute(
                    "UPDATE positions SET jd_embedding = %s WHERE id = %s",
                    (embedding, position["id"]),
                )


async def _extract_jd_requirements(jd_text: str) -> dict | None:
    """Use LLM to extract structured requirements from JD text."""
    prompt = f"""Extract structured requirements from this job description.
Return ONLY valid JSON with these fields:
{{
    "required_skills": ["skill1", "skill2"],
    "nice_to_have": ["skill1", "skill2"],
    "min_experience_years": 3,
    "education_level": "bachelor",
    "industry_keywords": ["fintech", "saas"],
    "certifications": ["AWS Solutions Architect"]
}}

JD:
{jd_text[:4000]}"""

    from backend.core.config import LITE_MODEL
    result = llm_call(prompt, model=LITE_MODEL, temperature=0.1, max_tokens=1000)
    if not result:
        return None

    try:
        # Extract JSON from response
        import re
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError:
        logger.warning("Failed to parse JD extraction result")
    return None


async def _check_jd_compliance(jd_text: str) -> dict:
    """Run DEI, legal, and completeness checks on JD."""
    prompt = f"""Analyze this job description for compliance. Return ONLY valid JSON:
{{
    "dei_score": 85,
    "dei_issues": ["found term X, suggest Y"],
    "legal_pass": true,
    "legal_issues": [],
    "completeness": 90,
    "missing_sections": []
}}

JD:
{jd_text[:4000]}"""

    from backend.core.config import LITE_MODEL
    result = llm_call(prompt, model=LITE_MODEL, temperature=0.1, max_tokens=500)
    if not result:
        return {"dei_score": None, "legal_pass": None, "completeness": None}

    try:
        import re
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    return {"dei_score": None, "legal_pass": None, "completeness": None}


# ---------------------------------------------------------------------------
# Resolved weights (inheritance chain visualisation)
# ---------------------------------------------------------------------------
@router.get("/{slug}/weights/resolved")
async def get_resolved_weights(slug: str, request: Request):
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    from backend.core.weights import resolve_weights
    return resolve_weights(position)


# ---------------------------------------------------------------------------
# AI Suggestions
# ---------------------------------------------------------------------------
@router.get("/{slug}/weight-suggestions")
async def get_weight_suggestions(slug: str, request: Request, refresh: bool = False):
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    from backend.core.database import get_cursor as _gc
    with _gc() as cur:
        if not refresh:
            cur.execute("""
                SELECT id, suggestion_type, description, weights, knockout, expected_pass_count, created_at
                FROM weight_suggestions
                WHERE position_id = %s AND dismissed = FALSE AND applied = FALSE
                ORDER BY created_at DESC LIMIT 5
            """, (position["id"],))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            for r in rows:
                if r.get("created_at"): r["created_at"] = r["created_at"].isoformat()
            if rows:
                return {"suggestions": rows, "from_cache": True}

        # Generate fresh suggestions
        cur.execute("""
            SELECT match_score_composite, match_score_skills, match_score_experience,
                   match_score_education, match_score_certifications, match_score_industry
            FROM position_candidates
            WHERE position_id = %s AND COALESCE(dismissed, FALSE) = FALSE
            ORDER BY match_score_composite DESC NULLS LAST
            LIMIT 30
        """, (position["id"],))
        scored = cur.fetchall()

    if not scored:
        return {"suggestions": [], "reason": "No candidates scanned yet"}

    knockout = float(position.get("knockout_threshold") or 0)
    pass_count = sum(1 for r in scored if (r[0] or 0) >= knockout)
    if pass_count >= max(3, len(scored) // 3):
        return {"suggestions": [], "reason": "Enough candidates pass current weights"}

    # Generate options programmatically (LLM optional / fallback heuristics)
    suggestions = []

    # Option A: lower knockout
    sorted_comp = sorted([r[0] or 0 for r in scored], reverse=True)
    if sorted_comp:
        target = max(int(sorted_comp[min(2, len(sorted_comp)-1)] - 5), 30)
        if target < int(knockout):
            suggestions.append({
                "type": "lower_knockout",
                "description": f"Lower knockout from {int(knockout)}% to {target}% — would pass {sum(1 for s in sorted_comp if s >= target)} candidates",
                "weights": None,
                "knockout": target,
                "expected_pass_count": sum(1 for s in sorted_comp if s >= target),
            })

    # Option B: boost experience (find dim where avg score is highest)
    avgs = {
        "skills":         sum((r[1] or 0) for r in scored) / len(scored),
        "experience":     sum((r[2] or 0) for r in scored) / len(scored),
        "education":      sum((r[3] or 0) for r in scored) / len(scored),
        "certifications": sum((r[4] or 0) for r in scored) / len(scored),
        "industry":       sum((r[5] or 0) for r in scored) / len(scored),
    }
    cur_w = {
        "skills":         int(position.get("weight_skills") or 40),
        "experience":     int(position.get("weight_experience") or 25),
        "industry":       int(position.get("weight_industry") or 15),
        "education":      int(position.get("weight_education") or 10),
        "certifications": int(position.get("weight_certifications") or 10),
        "culture":        int(position.get("weight_culture") or 0),
    }
    best_dim = max(avgs, key=avgs.get)
    boosted = dict(cur_w)
    if best_dim in boosted:
        boosted[best_dim] = min(60, boosted[best_dim] + 15)
        # take from the smallest non-best dim
        donors = sorted([(k, v) for k, v in boosted.items() if k != best_dim], key=lambda x: x[1], reverse=True)
        take = 15
        for k, v in donors:
            if take <= 0: break
            d = min(take, max(0, v - 5))
            boosted[k] = v - d; take -= d
    suggestions.append({
        "type": "boost_dim",
        "description": f"Boost {best_dim} weight (avg score {int(avgs[best_dim])}) — candidates score highest on this dimension",
        "weights": boosted,
        "knockout": None,
        "expected_pass_count": None,
        "dim": best_dim,
    })

    # Option C: drop weakest (where avg < 40)
    weak = [d for d, v in avgs.items() if v < 40]
    if weak:
        dropped = dict(cur_w)
        freed = 0
        for d in weak:
            if d in dropped:
                freed += max(0, dropped[d] - 5)
                dropped[d] = 5
        # redistribute to top dim
        if freed > 0:
            top = max(avgs, key=avgs.get)
            dropped[top] = dropped.get(top, 0) + freed
        suggestions.append({
            "type": "drop_weak",
            "description": f"De-emphasize weak dimensions ({', '.join(weak)}) — no candidate scores well here",
            "weights": dropped,
            "knockout": None,
            "expected_pass_count": None,
            "dims": weak,
        })

    # Persist
    with _gc() as cur:
        cur.execute("""
            UPDATE weight_suggestions SET dismissed = TRUE
            WHERE position_id = %s AND applied = FALSE AND dismissed = FALSE
        """, (position["id"],))
        for s in suggestions:
            cur.execute("""
                INSERT INTO weight_suggestions (position_id, suggestion_type, description, weights, knockout, expected_pass_count)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s) RETURNING id
            """, (position["id"], s["type"], s["description"],
                  json.dumps(s.get("weights")) if s.get("weights") else None,
                  s.get("knockout"), s.get("expected_pass_count")))
            s["id"] = cur.fetchone()[0]

    return {"suggestions": suggestions, "from_cache": False}


@router.post("/{slug}/weight-suggestions/{sug_id}/apply")
async def apply_weight_suggestion(slug: str, sug_id: int, request: Request):
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)
    from backend.core.database import get_cursor as _gc
    with _gc() as cur:
        cur.execute("SELECT suggestion_type, weights, knockout FROM weight_suggestions WHERE id = %s AND position_id = %s",
                    (sug_id, position["id"]))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Suggestion not found")
        s_type, weights, knockout = row
        if s_type == "lower_knockout" and knockout is not None:
            cur.execute("UPDATE positions SET knockout_threshold = %s, weights_overridden = TRUE WHERE id = %s",
                        (knockout, position["id"]))
        elif weights:
            cur.execute("UPDATE positions SET weight_skills=%s, weight_experience=%s, weight_industry=%s, weight_education=%s, weight_certifications=%s, weight_culture=%s, weights_overridden=TRUE WHERE id=%s",
                        (weights.get("skills"), weights.get("experience"), weights.get("industry"),
                         weights.get("education"), weights.get("certifications"), weights.get("culture"),
                         position["id"]))
        cur.execute("UPDATE weight_suggestions SET applied = TRUE WHERE id = %s", (sug_id,))
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
            (user["user_id"], "WEIGHT_SUGGESTION_APPLY", "positions", position["id"],
             json.dumps({"suggestion_id": sug_id, "type": s_type})),
        )
    return {"applied": True, "type": s_type}


@router.post("/{slug}/weight-suggestions/{sug_id}/dismiss")
async def dismiss_weight_suggestion(slug: str, sug_id: int, request: Request):
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)
    from backend.core.database import get_cursor as _gc
    with _gc() as cur:
        cur.execute("UPDATE weight_suggestions SET dismissed = TRUE WHERE id = %s AND position_id = %s",
                    (sug_id, position["id"]))
    return {"dismissed": True}


# ---------------------------------------------------------------------------
# Position Competencies
# ---------------------------------------------------------------------------
@router.get("/{slug}/competencies")
async def list_position_competencies(slug: str, request: Request):
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    from backend.core.database import get_cursor as _gc
    with _gc() as cur:
        cur.execute("""
            SELECT pc.competency_id, c.key, c.label, c.category,
                   pc.required_level, pc.importance, pc.weight, pc.source, pc.notes
            FROM position_competencies pc
            JOIN competencies c ON c.id = pc.competency_id
            WHERE pc.position_id = %s
            ORDER BY pc.importance, c.label
        """, (position["id"],))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"competencies": rows, "total": len(rows)}


@router.put("/{slug}/competencies")
async def replace_position_competencies(slug: str, request: Request):
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)
    body = await request.json()
    if not isinstance(body, list):
        raise HTTPException(400, "Expected JSON array")

    from backend.core.database import get_cursor as _gc

    # Pull JD's required levels (if any) to detect overrides
    jd_id = position.get("weights_source_jd_id")
    jd_map: dict = {}
    if jd_id:
        with _gc() as cur:
            cur.execute("SELECT competency_id, required_level, importance FROM jd_competencies WHERE jd_id = %s",
                        (jd_id,))
            for cid, lvl, imp in cur.fetchall():
                jd_map[cid] = (lvl, imp)

    with _gc() as cur:
        cur.execute("DELETE FROM position_competencies WHERE position_id = %s", (position["id"],))
        for row in body:
            cid = row.get("competency_id")
            lvl = row.get("required_level")
            if cid is None or lvl is None:
                continue
            try:
                lvl = int(lvl)
            except Exception:
                continue
            lvl = max(1, min(5, lvl))
            importance = row.get("importance") or "required"
            weight = row.get("weight") or 1.0
            jd_data = jd_map.get(cid)
            source = "jd" if (jd_data and jd_data[0] == lvl and jd_data[1] == importance) else "override"
            cur.execute("""
                INSERT INTO position_competencies (position_id, competency_id, required_level, importance, weight, source, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (position_id, competency_id) DO UPDATE SET
                    required_level = EXCLUDED.required_level,
                    importance = EXCLUDED.importance,
                    weight = EXCLUDED.weight,
                    source = EXCLUDED.source,
                    notes = EXCLUDED.notes
            """, (position["id"], cid, lvl, importance, weight, source, row.get("notes")))
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
            (user.get("user_id"), "POSITION_COMP_REPLACE", "positions", position["id"], json.dumps({"count": len(body)})),
        )
    return {"slug": slug, "count": len(body), "message": "saved"}


@router.post("/{slug}/competencies/sync-from-jd")
async def sync_position_competencies_from_jd(slug: str, request: Request):
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)
    jd_id = position.get("weights_source_jd_id")
    if not jd_id:
        return {"slug": slug, "synced": 0, "message": "No JD attached to this position"}
    from backend.routes.jd_repo import _sync_position_competencies_from_jd as _sync
    n = _sync(jd_id, position["id"])
    return {"slug": slug, "jd_id": jd_id, "synced": n}


@router.get("/{slug}/competency-fit/{candidate_id}")
async def competency_fit(slug: str, candidate_id: int, request: Request):
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    from backend.core.weights import score_competencies
    result = score_competencies(candidate_id, position["id"])
    gaps = result.get("gaps", [])
    critical = sum(1 for g in gaps if g.get("importance") == "required" and (g.get("gap") or 0) < 0)
    return {
        "slug": slug,
        "candidate_id": candidate_id,
        "fit_pct": result.get("score", 0),
        "per_comp": gaps,
        "critical_gaps_count": critical,
        "no_requirements": result.get("no_requirements", False),
    }


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
@router.get("/export.csv")
async def export_positions_csv(request: Request):
    """Export positions as CSV."""
    get_current_user(request)
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["slug", "title", "department", "status", "hiring_manager_id",
                "stage", "candidate_count", "created_at"])
    with get_cursor() as cur:
        cur.execute("""
            SELECT p.slug, p.title, p.department, p.status, p.hiring_manager_id,
                   p.status AS stage,
                   COALESCE((SELECT COUNT(*) FROM position_candidates pc
                             WHERE pc.position_id = p.id
                               AND COALESCE(pc.dismissed, FALSE) = FALSE), 0) AS candidate_count,
                   p.created_at
            FROM positions p
            ORDER BY p.created_at DESC
        """)
        for r in cur.fetchall():
            w.writerow([("" if v is None else v) for v in r])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="positions.csv"'},
    )


# ---------------------------------------------------------------------------
# AI Tab — latest auto-scan + top matches; on-demand rescan
# ---------------------------------------------------------------------------
@router.get(
    "/{slug}/ai",
    summary="Get AI auto-scan status + top matches",
    description="Returns the latest auto-scan row for the position together with the top 20 AI-matched candidates (with full 7-dimension score breakdown). Used by the position workspace AI tab.",
)
async def get_position_ai(slug: str, request: Request):
    """Return latest auto-scan status and top-20 AI-matched candidates."""
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    pid = position["id"]

    # Latest scan row
    scan = None
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT id, position_id, status, started_at, finished_at,
                       n_scored, n_matched, error, created_at
                FROM position_ai_scans
                WHERE position_id = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (pid,))
            row = cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                scan = dict(zip(cols, row))
    except Exception as e:
        logger.warning(f"[ai-tab] scan lookup failed for {slug}: {e}")

    # Top 20 matches: include score breakdown when columns exist
    matches: list[dict] = []
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT pc.id AS pc_id,
                       pc.candidate_id,
                       pc.match_score_composite,
                       pc.match_score_skills,
                       pc.match_score_experience,
                       pc.match_score_education,
                       pc.match_score_certifications,
                       pc.match_score_industry,
                       pc.match_score_culture,
                       pc.match_score_semantic,
                       pc.skills_matched,
                       pc.skills_missing,
                       pc.match_explanation,
                       pc.stage,
                       pc.added_by,
                       COALESCE(pc.match_source, 'manual') AS match_source,
                       pc.auto_added,
                       pc.created_at AS attached_at,
                       c.name, c.email, c.current_role, c.current_company,
                       c.total_experience_years AS years_experience, c.location AS candidate_location,
                       c.public_id AS candidate_public_id
                FROM position_candidates pc
                JOIN candidates c ON c.id = pc.candidate_id
                WHERE pc.position_id = %s
                  AND COALESCE(pc.dismissed, FALSE) = FALSE
                  AND COALESCE(pc.attachment_state, 'attached') = 'suggested'
                ORDER BY pc.match_score_composite DESC NULLS LAST
                LIMIT 20
            """, (pid,))
            cols = [d[0] for d in cur.description]
            matches = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"[ai-tab] matches lookup failed for {slug}: {e}")

    return {
        "position": {
            "id": pid,
            "slug": slug,
            "title": position.get("title"),
            "min_match_score": position.get("min_match_score", 50),
            "has_jd": bool(position.get("jd_text")) or bool(position.get("weights_source_jd_id")),
            "weights_source_jd_id": position.get("weights_source_jd_id"),
        },
        "scan": scan,
        "matches": matches,
    }


@router.post(
    "/{slug}/ai/rescan",
    dependencies=[Depends(require_role("hiring_manager"))],
    summary="Re-launch AI auto-scan for a position",
    description="Queues a fresh auto_scan_for_position background task. Dedupes against any active queued/running scan for the same position; returns the existing scan_id when one is already in progress.",
)
@limiter.limit("5/minute")
async def rescan_position_ai(slug: str, request: Request):
    """Re-launch auto_scan_for_position in background. Returns the new scan_id."""
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if user.get('role') not in ('admin', 'superadmin') and position.get('hiring_manager_id') != user.get('user_id'):
        raise HTTPException(status_code=403, detail="Not your position")

    pid = position["id"]

    # Dedupe — if an active scan is already queued/running, return it instead
    # of stacking a parallel one. Defends against double-clicks + race against
    # mig 042's partial unique index.
    try:
        with get_cursor() as cur:
            cur.execute(
                "SELECT id FROM position_ai_scans "
                "WHERE position_id = %s AND status IN ('queued', 'running') "
                "ORDER BY created_at DESC LIMIT 1",
                (pid,),
            )
            row = cur.fetchone()
            if row:
                existing_id = row[0]
                logger.info(
                    f"[ai-scan] dedupe — reusing scan id={existing_id} for position={pid}"
                )
                return {
                    "scan_id": existing_id,
                    "status": "in_progress",
                    "dedup": True,
                    "position_id": pid,
                    "slug": slug,
                }
    except Exception as e:
        logger.warning(f"[auto_scan] rescan dedupe check failed: {e}")

    scan_id = _create_ai_scan_row(pid)
    asyncio.create_task(_safe_background(
        auto_scan_for_position(pid, slug, scan_id=scan_id, match_source="auto_scan_rescan"),
        "auto_scan_rescan",
    ))
    return {"scan_id": scan_id, "status": "queued", "position_id": pid, "slug": slug}


@router.post(
    "/{slug}/rescore-attached",
    dependencies=[Depends(require_role("recruiter"))],
    summary="Re-score only candidates already attached to this position",
    description="Recomputes match_score_* columns for existing position_candidates rows. Does NOT scan the central pool, does NOT add new candidates. Use after weights or JD changes.",
)
@limiter.limit("10/minute")
async def rescore_attached(slug: str, request: Request):
    """Re-score only attached candidates (no new attachments). Synchronous, fast."""
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    if user.get("role") not in ("admin", "superadmin") and position.get("hiring_manager_id") not in (None, user.get("user_id")):
        raise HTTPException(403, "Not your position")
    pid = position["id"]
    try:
        from backend.agents.registry import heartbeat as _hb, cycle_done as _cd
        _hb("match", status="running", action=f"re-scoring attached candidates for {slug}")
    except Exception:
        _hb = _cd = lambda *a, **kw: None  # noqa

    n = 0
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT pc.candidate_id FROM position_candidates pc
                    WHERE pc.position_id=%s AND COALESCE(pc.stage,'uploaded') != 'rejected'""",
                (pid,),
            )
            cand_ids = [r[0] for r in cur.fetchall()]
        if not cand_ids:
            _cd("match", events=0)
            return {"slug": slug, "rescored": 0, "message": "No attached candidates to re-score"}

        for cid in cand_ids:
            with get_cursor() as cur:
                cur.execute("SELECT * FROM candidates WHERE id=%s", (cid,))
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                if not row: continue
                cand = dict(zip(cols, row))
            for f in ("experience", "education", "certifications", "projects"):
                v = cand.get(f)
                if isinstance(v, str):
                    try: cand[f] = json.loads(v)
                    except Exception: cand[f] = []
            try:
                s = score_candidate_against_position(cand, position)
            except Exception as e:
                logger.warning(f"[agent:match] score failed cand {cid}: {e}")
                continue
            with get_cursor() as cur:
                cur.execute(
                    """UPDATE position_candidates SET
                        match_score_composite=%s, match_score_skills=%s, match_score_experience=%s,
                        match_score_education=%s, match_score_certifications=%s, match_score_industry=%s,
                        match_score_culture=%s, updated_at=NOW()
                       WHERE position_id=%s AND candidate_id=%s""",
                    (
                        s.get("composite"), s.get("skills"), s.get("experience"),
                        s.get("education"), s.get("certifications"), s.get("industry"),
                        s.get("culture"),
                        pid, cid,
                    ),
                )
            n += 1
        _cd("match", events=n)
        return {"slug": slug, "rescored": n, "message": f"Re-scored {n} attached candidate(s)"}
    except Exception as e:
        logger.error(f"[agent:match] rescore-attached failed: {e}")
        try: _cd("match", error=str(e))
        except Exception: pass
        raise HTTPException(500, str(e))


@router.get("/{slug}/ai/top-scored")
async def top_scored_below_threshold(slug: str, request: Request, limit: int = Query(5, ge=1, le=20)):
    """Re-score all CVs against this position. Return top N regardless of threshold.

    Used by AI Match empty state to show WHY no matches: "highest was Sithu Zeya at 32%
    but threshold is 50%". Read-only, does NOT persist or attach.
    """
    _ = get_current_user(request)  # auth gate
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    threshold = int(position.get("min_match_score") or 50)
    with get_cursor() as cur:
        cur.execute("SELECT * FROM candidates WHERE status='active' AND is_processed=TRUE LIMIT 200")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    scored = []
    for c in rows:
        for f in ("experience", "education", "certifications", "projects"):
            v = c.get(f)
            if isinstance(v, str):
                try: c[f] = json.loads(v)
                except Exception: c[f] = []
        try:
            s = score_candidate_against_position(c, position)
        except Exception as e:
            logger.warning("[top-scored] score failed cand %s: %s", c.get("id"), e)
            continue
        scored.append({
            "candidate_id": c.get("id"),
            "name": c.get("name") or "Unknown",
            "current_role": c.get("current_role") or "",
            "years_experience": c.get("total_experience_years") or 0,
            "composite": int(s.get("composite") or 0),
            "skills": int(s.get("skills") or 0),
            "experience": int(s.get("experience") or 0),
            "industry": int(s.get("industry") or 0),
            "above_threshold": (s.get("composite") or 0) >= threshold,
        })
    scored.sort(key=lambda x: x["composite"], reverse=True)
    top = scored[:limit]
    suggested = None
    if top and not top[0]["above_threshold"]:
        # Suggest threshold = round down to nearest 5 below the highest score
        suggested = max(10, (top[0]["composite"] // 5) * 5)
    return {
        "threshold": threshold,
        "total_scored": len(scored),
        "n_above_threshold": sum(1 for x in scored if x["above_threshold"]),
        "top": top,
        "suggested_threshold": suggested,
    }


@router.post(
    "/{slug}/ai/{candidate_id}/promote",
    dependencies=[Depends(require_role("recruiter"))],
    summary="Promote one AI-matched candidate to screened",
    description="Moves a single AI-matched candidate into the 'screened' stage and stamps match_source='ai_promoted'. Writes a stage_change row to candidate_activity (source='ai_promote') for audit.",
)
@limiter.limit("30/minute")
async def promote_ai_match(slug: str, candidate_id: int, request: Request):
    """Promote an AI-matched candidate from 'uploaded' into the screened pipeline."""
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if user.get('role') not in ('admin', 'superadmin') and position.get('hiring_manager_id') != user.get('user_id'):
        raise HTTPException(status_code=403, detail="Not your position")
    pid = position["id"]
    with get_cursor() as cur:
        cur.execute("""
            UPDATE position_candidates
               SET stage = 'screened',
                   stage_changed_at = NOW(),
                   match_source = 'ai_promoted',
                   attachment_state = 'attached',
                   dismissed = FALSE,
                   updated_at = NOW()
             WHERE position_id = %s AND candidate_id = %s
        """, (pid, candidate_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Candidate not attached to position")
        try:
            cur.execute("""
                INSERT INTO candidate_activity (candidate_id, position_id, user_id, activity_type, details)
                VALUES (%s, %s, %s, 'stage_change', %s)
            """, (candidate_id, pid, user["user_id"],
                  json.dumps({"new_stage": "screened", "source": "ai_promote"})))
        except Exception:
            pass
    return {"status": "promoted", "candidate_id": candidate_id, "stage": "screened"}


class _BulkPromoteBody(BaseModel):
    candidate_ids: list[int]


@router.post(
    "/{slug}/ai/bulk-promote",
    dependencies=[Depends(require_role("recruiter"))],
    summary="Bulk promote AI-matched candidates",
    description="Promotes up to 50 AI-matched candidates to the 'screened' stage in a single request. Each successful promotion writes an audit row to candidate_activity (source='ai_bulk_promote').",
)
@limiter.limit("10/minute")
async def bulk_promote_ai_matches(slug: str, request: Request, body: _BulkPromoteBody):
    """Promote N AI-matched candidates in a single transaction. Cap N=50."""
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if user.get('role') not in ('admin', 'superadmin') and position.get('hiring_manager_id') != user.get('user_id'):
        raise HTTPException(status_code=403, detail="Not your position")
    ids = list(body.candidate_ids or [])
    if len(ids) > 50:
        raise HTTPException(status_code=400, detail="Too many candidates (max 50)")
    if not ids:
        return {"promoted": [], "failed": [], "total": 0}
    pid = position["id"]
    promoted: list[int] = []
    failed: list[dict] = []
    with get_cursor() as cur:
        for cid in ids:
            try:
                cur.execute("""
                    UPDATE position_candidates
                       SET stage = 'screened',
                           stage_changed_at = NOW(),
                           match_source = 'ai_promoted',
                           attachment_state = 'attached',
                           dismissed = FALSE,
                           updated_at = NOW()
                     WHERE position_id = %s AND candidate_id = %s
                """, (pid, cid))
                if cur.rowcount == 0:
                    failed.append({"cid": cid, "reason": "not_attached"})
                    continue
                try:
                    cur.execute("""
                        INSERT INTO candidate_activity (candidate_id, position_id, user_id, activity_type, details)
                        VALUES (%s, %s, %s, 'stage_change', %s)
                    """, (cid, pid, user["user_id"],
                          json.dumps({"new_stage": "screened", "source": "ai_bulk_promote"})))
                except Exception:
                    pass
                promoted.append(cid)
            except Exception as e:
                failed.append({"cid": cid, "reason": str(e)})
    return {"promoted": promoted, "failed": failed, "total": len(ids)}


@router.post(
    "/{slug}/ai/{candidate_id}/reject",
    dependencies=[Depends(require_role("recruiter"))],
    summary="Reject (dismiss) an AI-matched candidate",
    description="Dismisses a candidate from the position's AI match list and sets their stage to 'rejected'. Records the actor and writes an audit row to candidate_activity (source='ai_reject').",
)
@limiter.limit("30/minute")
async def reject_ai_match(slug: str, candidate_id: int, request: Request):
    """Dismiss/reject an AI-matched candidate from this position's match list."""
    user = get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if user.get('role') not in ('admin', 'superadmin') and position.get('hiring_manager_id') != user.get('user_id'):
        raise HTTPException(status_code=403, detail="Not your position")
    pid = position["id"]
    with get_cursor() as cur:
        cur.execute("""
            UPDATE position_candidates
               SET dismissed = TRUE,
                   dismissed_at = NOW(),
                   dismissed_by = %s,
                   stage = 'rejected',
                   stage_changed_at = NOW(),
                   attachment_state = 'rejected',
                   updated_at = NOW()
             WHERE position_id = %s AND candidate_id = %s
        """, (str(user.get("user_id")), pid, candidate_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Candidate not attached to position")
        try:
            cur.execute("""
                INSERT INTO candidate_activity (candidate_id, position_id, user_id, activity_type, details)
                VALUES (%s, %s, %s, 'stage_change', %s)
            """, (candidate_id, pid, user["user_id"],
                  json.dumps({"new_stage": "rejected", "source": "ai_reject"})))
        except Exception:
            pass
    return {"status": "rejected", "candidate_id": candidate_id}


@router.get(
    "/{slug}/ai/events/sign",
    summary="Issue HMAC-signed URL for /ai/events SSE",
    description="Returns a short-lived (5 min TTL) signed URL the frontend can pass to EventSource (which has no header support). Mirrors the /candidates/{id}/file/sign pattern; signature covers slug+user_id+exp.",
)
async def sign_position_ai_events_url(slug: str, request: Request):
    """Issue a short-lived HMAC-signed URL for /ai/events SSE. Bearer auth required."""
    user = get_current_user(request)
    if user.get("role") not in ("recruiter", "hiring_manager", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Requires recruiter+ role")
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    uid = user.get("user_id") or 0
    exp = int(_time.time()) + SSE_SIGN_TTL
    sig = _compute_sse_sig(slug, uid, exp)
    return {
        "url": f"/api/positions/{slug}/ai/events?sig={sig}&exp={exp}&uid={uid}",
        "exp": exp,
        "ttl_s": SSE_SIGN_TTL,
    }


@router.get(
    "/{slug}/ai/events",
    summary="SSE stream of AI auto-scan progress",
    description="Server-sent events stream emitting scan status + counter updates every 1s, closing on done/error or after 5 min idle. Accepts HMAC-signed URL (sig+exp+uid, preferred) or legacy ?token= (deprecated).",
)
async def stream_position_ai_events(
    slug: str,
    request: Request,
    sig: str | None = None,
    exp: int | None = None,
    uid: int | None = None,
    token: str | None = None,
):
    """SSE stream of latest scan progress for a position.

    Polls position_ai_scans every 1s and emits status changes + counter
    updates. Closes when status is done/error or after 5 min idle.

    Auth precedence:
      1. sig + exp + uid HMAC (preferred, short-lived)
      2. ?token= legacy (deprecated, still accepted with warn log)
      3. Bearer header / cookie via get_current_user
    """
    from fastapi.responses import StreamingResponse
    import json as _json

    if sig and exp is not None and uid is not None:
        now = int(_time.time())
        if exp < now:
            raise HTTPException(status_code=401, detail="Signed URL expired")
        expected = _compute_sse_sig(slug, uid, int(exp))
        if not _hmac.compare_digest(expected, sig):
            raise HTTPException(status_code=401, detail="Invalid signature")
        # uid lookup — verify user exists (best-effort)
        try:
            with get_cursor() as cur:
                cur.execute("SELECT id, role FROM users WHERE id = %s", (uid,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=401, detail="Unknown uid")
        except HTTPException:
            raise
        except Exception:
            pass
    elif token:
        logger.warning(f"[ai-sse] deprecated ?token= used by uid={uid}")
        from backend.core.auth import validate_token as _vt
        u = _vt(token)
        if not u:
            raise HTTPException(status_code=401, detail="Invalid token")
    else:
        get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    pid = position["id"]

    async def gen():
        last_payload = None
        idle_ticks = 0
        tick = 0
        max_idle = 300  # 5 min
        while idle_ticks < max_idle:
            if await request.is_disconnected():
                break
            scan = None
            try:
                with get_cursor() as cur:
                    cur.execute(
                        "SELECT id, status, started_at, finished_at, n_scored, "
                        "n_matched, error FROM position_ai_scans "
                        "WHERE position_id=%s ORDER BY created_at DESC LIMIT 1",
                        (pid,),
                    )
                    row = cur.fetchone()
                    if row:
                        cols = [d[0] for d in cur.description]
                        scan = dict(zip(cols, row))
                        for k in ("started_at", "finished_at"):
                            if scan.get(k) is not None:
                                scan[k] = scan[k].isoformat()
            except Exception as e:
                yield f"event: error\ndata: {_json.dumps({'error': str(e)})}\n\n"
                break
            if scan is None:
                yield "event: idle\ndata: {}\n\n"
            else:
                payload = _json.dumps(scan)
                if payload != last_payload:
                    yield f"event: scan\ndata: {payload}\n\n"
                    last_payload = payload
                if scan.get("status") in ("done", "error"):
                    yield "event: end\ndata: {}\n\n"
                    break
            idle_ticks += 1
            tick += 1
            if tick % 25 == 0:
                yield ": ping\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
