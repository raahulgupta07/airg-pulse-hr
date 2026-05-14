"""Candidate extras — notes, activity, positions, AI summary."""
from __future__ import annotations

import re
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse

from backend.core.auth import get_current_user
from backend.core.permissions import require_role
from backend.core.database import get_cursor, get_candidate
from backend.core.config import llm_call, CHAT_MODEL, LITE_MODEL
from backend.core.ids import resolve_id_sync
from backend.core.rate_limit import limiter
from backend.routes.notifications import create_notification


def _resolve_cid(candidate_id) -> Optional[int]:
    """Resolve int|str (digits or public_id like cv_...) -> internal int id, or None."""
    return resolve_id_sync("candidates", candidate_id)


def _resolve_or_404(candidate_id) -> int:
    cid = _resolve_cid(candidate_id)
    if cid is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return cid

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------
@router.get("/{candidate_id}/notes")
async def list_notes(candidate_id: str, request: Request):
    """List notes for a candidate."""
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    with get_cursor() as cur:
        cur.execute("""
            SELECT n.*, u.display_name AS author_name
            FROM candidate_notes n
            LEFT JOIN users u ON u.id = n.created_by
            WHERE n.candidate_id = %s
            ORDER BY n.created_at DESC
        """, (candidate_id,))
        cols = [desc[0] for desc in cur.description]
        notes = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"notes": notes}


@router.post("/{candidate_id}/notes", dependencies=[Depends(require_role("recruiter"))])
async def add_note(candidate_id: str, request: Request):
    """Add a note to a candidate."""
    user = get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    body = await request.json()
    content = body.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    note_type = body.get("note_type", "general")
    position_id = body.get("position_id")

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO candidate_notes (candidate_id, content, note_type, position_id, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, created_at
        """, (candidate_id, content, note_type, position_id, user["user_id"]))
        row = cur.fetchone()
        note_id = row[0]

        # Parse @mentions and create notifications
        mentions = re.findall(r"@(\w+)", content)
        if mentions:
            # Look up candidate name for notification
            cur.execute("SELECT name FROM candidates WHERE id = %s", (candidate_id,))
            cand_row = cur.fetchone()
            candidate_name = cand_row[0] if cand_row else f"Candidate #{candidate_id}"

            for mention in set(mentions):
                cur.execute(
                    "SELECT id FROM users WHERE display_name ILIKE %s AND is_active = TRUE",
                    (mention,),
                )
                mentioned_user = cur.fetchone()
                if mentioned_user:
                    try:
                        create_notification(
                            user_id=mentioned_user[0],
                            type="mention",
                            title=f"You were mentioned in a note on {candidate_name}",
                            message=content[:200],
                            link=f"/candidates/{candidate_id}",
                        )
                    except Exception as e:
                        logger.warning(f"Failed to create mention notification: {e}")

    return {"id": note_id, "created_at": row[1], "status": "created"}


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------
@router.get("/{candidate_id}/activity")
async def list_activity(candidate_id: str, request: Request):
    """Activity timeline for a candidate."""
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    with get_cursor() as cur:
        cur.execute("""
            SELECT a.*, u.display_name AS actor_name
            FROM candidate_activity a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE a.candidate_id = %s
            ORDER BY a.created_at DESC
        """, (candidate_id,))
        cols = [desc[0] for desc in cur.description]
        activity = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"activity": activity}


# ---------------------------------------------------------------------------
# Positions linked to candidate
# ---------------------------------------------------------------------------
@router.get("/{candidate_id}/positions")
async def list_candidate_positions(candidate_id: str, request: Request):
    """List positions this candidate is linked to with scores."""
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    with get_cursor() as cur:
        cur.execute("""
            SELECT pc.*, p.title, p.slug, p.department, p.status AS position_status
            FROM position_candidates pc
            JOIN positions p ON p.id = pc.position_id
            WHERE pc.candidate_id = %s
            ORDER BY pc.created_at DESC
        """, (candidate_id,))
        cols = [desc[0] for desc in cur.description]
        positions = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"positions": positions}


# ---------------------------------------------------------------------------
# AI Recommendations — positions where this candidate was AI-matched
# ---------------------------------------------------------------------------
@router.get("/{candidate_id}/ai-recommendations")
async def list_candidate_ai_recommendations(candidate_id: str, request: Request):
    """Return positions where this candidate was AI-matched (auto_scan or ai_promoted), top 50."""
    get_current_user(request)
    cid = _resolve_or_404(candidate_id)
    with get_cursor() as cur:
        cur.execute("""
            SELECT pc.*,
                   p.slug AS position_slug,
                   p.title AS position_title
            FROM position_candidates pc
            JOIN positions p ON p.id = pc.position_id
            WHERE pc.candidate_id = %s
              AND pc.match_source IN ('auto_scan_on_create','auto_scan_on_jd_update','auto_scan_rescan','ai_promoted')
              AND COALESCE(pc.dismissed, FALSE) = FALSE
            ORDER BY pc.match_score_composite DESC NULLS LAST
            LIMIT 50
        """, (cid,))
        cols = [desc[0] for desc in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    # Surface position_id explicitly (already in pc.*) — ensure present
    for r in rows:
        if "position_id" not in r:
            r["position_id"] = r.get("position_id")
    return rows


# ---------------------------------------------------------------------------
# Duplicates (proxy to duplicates module)
# ---------------------------------------------------------------------------
@router.get("/{candidate_id}/duplicates")
async def candidate_duplicates(candidate_id: str, request: Request):
    """Find potential duplicates for a candidate. Proxies to duplicates module."""
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    from backend.routes.duplicates import _find_duplicates_for
    results = _find_duplicates_for(candidate_id)
    seen = set()
    all_dupes = []
    for match_type in ("email", "phone", "name"):
        for d in results[match_type]:
            if d["id"] not in seen:
                seen.add(d["id"])
                all_dupes.append({**d, "match_type": match_type})
    return {"candidate_id": candidate_id, "duplicates": all_dupes, "details": results}


# ---------------------------------------------------------------------------
# Custom Tags
# ---------------------------------------------------------------------------
@router.get("/{candidate_id}/tags")
async def list_candidate_tags(candidate_id: str, request: Request):
    """List custom tags for a candidate."""
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    with get_cursor() as cur:
        cur.execute("""
            SELECT id, tag, color, created_at
            FROM candidate_tags
            WHERE candidate_id = %s
            ORDER BY created_at ASC
        """, (candidate_id,))
        cols = [desc[0] for desc in cur.description]
        tags = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"tags": tags}


@router.post("/{candidate_id}/tags", dependencies=[Depends(require_role("recruiter"))])
async def add_candidate_tag(candidate_id: str, request: Request):
    """Add a custom tag to a candidate."""
    user = get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    body = await request.json()
    tag = body.get("tag", "").strip()
    color = body.get("color", "#383832")

    if not tag:
        raise HTTPException(status_code=400, detail="tag is required")

    with get_cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO candidate_tags (candidate_id, tag, color, created_by)
                VALUES (%s, %s, %s, %s)
                RETURNING id, created_at
            """, (candidate_id, tag, color, user.get("user_id")))
            row = cur.fetchone()
            return {"id": row[0], "tag": tag, "color": color, "created_at": row[1]}
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                raise HTTPException(status_code=409, detail="Tag already exists for this candidate")
            raise


@router.delete("/{candidate_id}/tags/{tag}", dependencies=[Depends(require_role("recruiter"))])
async def remove_candidate_tag(candidate_id: str, tag: str, request: Request):
    """Remove a custom tag from a candidate."""
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    with get_cursor() as cur:
        cur.execute(
            "DELETE FROM candidate_tags WHERE candidate_id = %s AND tag = %s",
            (candidate_id, tag),
        )
    return {"message": f"Tag '{tag}' removed"}


# ---------------------------------------------------------------------------
# All unique tags (for autocomplete)
# ---------------------------------------------------------------------------
@router.get("/tags/all")
async def list_all_tags(request: Request):
    """List all unique tags used across candidates (for autocomplete)."""
    get_current_user(request)
    with get_cursor() as cur:
        cur.execute("""
            SELECT tag, color, COUNT(*) AS usage_count
            FROM candidate_tags
            GROUP BY tag, color
            ORDER BY usage_count DESC
        """)
        cols = [desc[0] for desc in cur.description]
        tags = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"tags": tags}


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------
@router.get("/{candidate_id}/referral")
async def get_referral(candidate_id: str, request: Request):
    """Get referral info for a candidate."""
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    with get_cursor() as cur:
        cur.execute("""
            SELECT r.*, p.title AS position_title, p.slug AS position_slug
            FROM referrals r
            LEFT JOIN positions p ON p.id = r.position_id
            WHERE r.candidate_id = %s
            ORDER BY r.created_at DESC
        """, (candidate_id,))
        cols = [desc[0] for desc in cur.description]
        referrals = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"referrals": referrals}


@router.post("/{candidate_id}/referral", dependencies=[Depends(require_role("recruiter"))])
async def add_referral(candidate_id: str, request: Request):
    """Add a referral for a candidate."""
    user = get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    body = await request.json()
    referrer_name = body.get("referrer_name")
    if not referrer_name:
        raise HTTPException(status_code=400, detail="referrer_name is required")

    referrer_email = body.get("referrer_email")
    position_id = body.get("position_id")
    notes = body.get("notes")

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO referrals (candidate_id, referrer_name, referrer_email, referrer_user_id, position_id, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """, (candidate_id, referrer_name, referrer_email, user.get("user_id"), position_id, notes))
        row = cur.fetchone()
    return {"id": row[0], "created_at": row[1], "message": "Referral added"}


# ---------------------------------------------------------------------------
# AI Candidate Summary (One-Click Brief)
# ---------------------------------------------------------------------------
@router.get("/{candidate_id}/ai-summary")
@limiter.limit("30/minute")
async def ai_candidate_summary(candidate_id: str, request: Request, refresh: bool = False):
    """Return cached AI executive brief, regenerate only if missing or refresh=true."""
    get_current_user(request)

    candidate_id = _resolve_or_404(candidate_id)
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not refresh and candidate.get("ai_summary"):
        return {
            "candidate_id": candidate_id,
            "candidate_name": candidate.get("name"),
            "ai_summary": candidate["ai_summary"],
            "cached": True,
            "generated_at": candidate.get("ai_summary_generated_at"),
        }

    # Parse JSONB fields
    for field in ("experience", "education", "certifications", "projects"):
        val = candidate.get(field)
        if isinstance(val, str):
            try:
                candidate[field] = json.loads(val)
            except json.JSONDecodeError:
                candidate[field] = []

    # Gather all candidate data: notes, position matches
    scorecards = []
    with get_cursor() as cur:
        # Notes
        cur.execute("""
            SELECT content, note_type, created_at FROM candidate_notes
            WHERE candidate_id = %s ORDER BY created_at DESC LIMIT 10
        """, (candidate_id,))
        notes_cols = [desc[0] for desc in cur.description]
        notes = [dict(zip(notes_cols, row)) for row in cur.fetchall()]

        # Position matches
        cur.execute("""
            SELECT p.title, pc.match_score_composite, pc.stage, pc.skills_matched, pc.skills_missing
            FROM position_candidates pc
            JOIN positions p ON p.id = pc.position_id
            WHERE pc.candidate_id = %s
            ORDER BY pc.match_score_composite DESC NULLS LAST LIMIT 5
        """, (candidate_id,))
        pm_cols = [desc[0] for desc in cur.description]
        position_matches = [dict(zip(pm_cols, row)) for row in cur.fetchall()]

    # Build prompt
    notes_text = "\n".join(f"- [{n.get('note_type', 'general')}] {n.get('content', '')[:200]}" for n in notes) if notes else "No notes."
    scorecards_text = "No scorecards yet."
    matches_text = "\n".join(
        f"- {m.get('title', 'N/A')}: {m.get('match_score_composite', 'N/A')}% match, Stage: {m.get('stage', 'N/A')}"
        for m in position_matches
    ) if position_matches else "No position matches."

    experience_text = ""
    for exp in (candidate.get("experience") or [])[:5]:
        if isinstance(exp, dict):
            experience_text += f"- {exp.get('role', '')} at {exp.get('company', '')} ({exp.get('start_date', '')} - {exp.get('end_date', '')})\n"

    prompt = f"""Generate a 200-word executive summary for this candidate. Cover: strengths, concerns, fit assessment, and recommendation.

CANDIDATE: {candidate.get('name', 'Unknown')}
CURRENT ROLE: {candidate.get('current_role', 'N/A')} at {candidate.get('current_company', 'N/A')}
EXPERIENCE: {candidate.get('total_experience_years', 0)} years | Seniority: {candidate.get('seniority_level', 'N/A')}
SKILLS: {', '.join(candidate.get('skills_technical', [])[:15])}
TOOLS: {', '.join(candidate.get('tools', [])[:10])}
EDUCATION: {json.dumps(candidate.get('education', [])[:3])}
QUALITY SCORE: {candidate.get('quality_score', 'N/A')}/100

WORK HISTORY:
{experience_text or 'Not available'}

NOTES:
{notes_text}

POSITION MATCHES:
{matches_text}

SHORT SUMMARY FROM CV: {candidate.get('summary_short', 'N/A')}

Write a concise, professional executive brief. Use clear sections: Strengths, Concerns, Fit Assessment, Recommendation."""

    summary = llm_call(prompt, model=CHAT_MODEL, temperature=0.3, max_tokens=1000)
    if not summary:
        raise HTTPException(status_code=500, detail="Failed to generate AI summary")

    try:
        with get_cursor() as cur:
            cur.execute(
                "UPDATE candidates SET ai_summary=%s, ai_summary_generated_at=NOW() WHERE id=%s",
                (summary, candidate_id),
            )
    except Exception:
        pass

    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate.get("name"),
        "ai_summary": summary,
        "cached": False,
        "data_sources": {
            "notes_count": len(notes),
            "scorecards_count": len(scorecards),
            "position_matches_count": len(position_matches),
        },
    }


# ---------------------------------------------------------------------------
# Assignments — which positions a candidate is attached to
# ---------------------------------------------------------------------------
@router.get("/{candidate_id}/assignments")
async def list_assignments(
    candidate_id: str,
    request: Request,
    exclude_position_id: Optional[int] = None,
    include_dismissed: bool = False,
):
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    conds = ["pc.candidate_id = %s"]
    params: list = [candidate_id]
    if exclude_position_id:
        conds.append("pc.position_id <> %s"); params.append(exclude_position_id)
    if not include_dismissed:
        conds.append("COALESCE(pc.dismissed, FALSE) = FALSE")
    where = "WHERE " + " AND ".join(conds)
    with get_cursor() as cur:
        cur.execute(f"""
            SELECT pc.position_id, p.slug, p.title, pc.stage,
                   pc.match_score_composite,
                   pc.created_at AS added_at,
                   pc.added_by AS recruiter_name,
                   p.status AS position_status
            FROM position_candidates pc
            JOIN positions p ON p.id = pc.position_id
            {where}
            ORDER BY pc.created_at DESC
        """, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    active_stages = {"offered"}
    for r in rows:
        r["is_active_interview"] = r.get("stage") in active_stages
        if r.get("added_at"):
            r["added_at"] = r["added_at"].isoformat()
    return {"assignments": rows, "total": len(rows)}


# ---------------------------------------------------------------------------
# Candidate Competencies
# ---------------------------------------------------------------------------
@router.get("/{candidate_id}/competencies")
async def list_candidate_competencies(candidate_id: str, request: Request):
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    with get_cursor() as cur:
        cur.execute("""
            SELECT cc.id, cc.competency_id, c.key, c.label, c.category,
                   cc.level, cc.source, cc.source_id, cc.evidence, cc.confidence,
                   cc.rated_by, cc.rated_at
            FROM candidate_competencies cc
            JOIN competencies c ON c.id = cc.competency_id
            WHERE cc.candidate_id = %s
            ORDER BY cc.competency_id, cc.rated_at DESC
        """, (candidate_id,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"competencies": rows, "total": len(rows)}


def _internal_autoextract_competencies(candidate_id: int) -> dict:
    """Auto-extract competency scores from candidate.raw_text. Defensive — never raises."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT raw_text, experience FROM candidates WHERE id = %s", (candidate_id,))
            row = cur.fetchone()
            if not row:
                return {"extracted": [], "scored": 0, "error": "candidate not found"}
            raw_text = row[0] or ""
            experience = row[1]
            cur.execute("""
                SELECT c.id, c.key, c.label
                FROM competencies c
                JOIN competency_frameworks f ON f.id = c.framework_id
                WHERE c.active = TRUE AND f.is_default = TRUE
            """)
            lib = [(r[0], r[1], r[2]) for r in cur.fetchall()]

        if not lib or not raw_text.strip():
            return {"extracted": [], "scored": 0}

        key_to_id = {k: cid for cid, k, _l in lib}
        keys_only = [k for _id, k, _l in lib]

        exp_brief = ""
        try:
            if isinstance(experience, str):
                experience = json.loads(experience)
            if isinstance(experience, list):
                for e in experience[:5]:
                    if isinstance(e, dict):
                        exp_brief += f"- {e.get('role','')} @ {e.get('company','')}\n"
        except Exception:
            pass

        prompt = f"""You are scoring a candidate on these competencies: {json.dumps(keys_only)}.
Read CV bullets. For each comp WHERE there's evidence, return:
{{"key":"...", "level":4.2, "confidence":0.85, "evidence":"exact quote"}}
Skip if no signal. Use 1-5 scale (decimals OK).
Return ONLY a JSON array.

Experience summary:
{exp_brief}

CV text:
{raw_text[:6000]}
"""
        extracted: list = []
        try:
            result = llm_call(prompt, model=LITE_MODEL, temperature=0.1, max_tokens=1500)
            if result:
                m = re.search(r'\[[\s\S]*\]', result)
                if m:
                    extracted = json.loads(m.group()) or []
        except Exception as e:
            logger.warning(f"competency extract LLM failed for candidate {candidate_id}: {e}")
            extracted = []

        scored = 0
        with get_cursor() as cur:
            for item in extracted:
                if not isinstance(item, dict):
                    continue
                key = item.get("key")
                cid = key_to_id.get(key)
                if not cid:
                    continue
                try:
                    lvl = float(item.get("level") or 0)
                except Exception:
                    continue
                if lvl <= 0:
                    continue
                lvl = max(1.0, min(5.0, lvl))
                try:
                    conf = float(item.get("confidence") or 0.5)
                except Exception:
                    conf = 0.5
                evidence = (item.get("evidence") or "")[:600]
                cur.execute("""
                    INSERT INTO candidate_competencies (candidate_id, competency_id, level, source, source_id, evidence, confidence, rated_at)
                    VALUES (%s, %s, %s, 'cv-extract', NULL, %s, %s, NOW())
                    ON CONFLICT (candidate_id, competency_id, source, source_id) DO UPDATE SET
                        level = EXCLUDED.level,
                        evidence = EXCLUDED.evidence,
                        confidence = EXCLUDED.confidence,
                        rated_at = NOW()
                """, (candidate_id, cid, lvl, evidence, conf))
                scored += 1
        return {"extracted": extracted, "scored": scored}
    except Exception as e:
        logger.warning(f"_internal_autoextract_competencies failed: {e}")
        return {"extracted": [], "scored": 0, "error": str(e)}


@router.post("/{candidate_id}/competencies/auto-extract", dependencies=[Depends(require_role("recruiter"))])
async def auto_extract_candidate_competencies(candidate_id: str, request: Request):
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    return {"candidate_id": candidate_id, **_internal_autoextract_competencies(candidate_id)}


@router.put("/{candidate_id}/competencies/{competency_id}", dependencies=[Depends(require_role("recruiter"))])
async def rate_candidate_competency(candidate_id: str, competency_id: int, request: Request):
    user = get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    body = await request.json()
    try:
        lvl = float(body.get("level"))
    except Exception:
        raise HTTPException(400, "level (1-5) required")
    lvl = max(1.0, min(5.0, lvl))
    evidence = (body.get("evidence") or "")[:600]
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO candidate_competencies (candidate_id, competency_id, level, source, source_id, evidence, rated_by, rated_at)
            VALUES (%s, %s, %s, 'manual', NULL, %s, %s, NOW())
            ON CONFLICT (candidate_id, competency_id, source, source_id) DO UPDATE SET
                level = EXCLUDED.level,
                evidence = EXCLUDED.evidence,
                rated_by = EXCLUDED.rated_by,
                rated_at = NOW()
            RETURNING id
        """, (candidate_id, competency_id, lvl, evidence, user.get("user_id")))
        rid = cur.fetchone()[0]
    return {"id": rid, "candidate_id": candidate_id, "competency_id": competency_id, "level": lvl, "source": "manual"}


@router.delete("/{candidate_id}/competencies/{competency_id}", dependencies=[Depends(require_role("recruiter"))])
async def delete_candidate_competency(candidate_id: str, competency_id: int, request: Request):
    get_current_user(request)
    candidate_id = _resolve_or_404(candidate_id)
    try:
        body = await request.json()
    except Exception:
        body = {}
    source = (body or {}).get("source")
    with get_cursor() as cur:
        if source:
            cur.execute("DELETE FROM candidate_competencies WHERE candidate_id = %s AND competency_id = %s AND source = %s",
                        (candidate_id, competency_id, source))
        else:
            cur.execute("DELETE FROM candidate_competencies WHERE candidate_id = %s AND competency_id = %s",
                        (candidate_id, competency_id))
    return {"deleted": True, "candidate_id": candidate_id, "competency_id": competency_id, "source": source}
