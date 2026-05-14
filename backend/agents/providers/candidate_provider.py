"""Candidate provider — wraps backend.core.database + backend.routes.matching.

Pure Python functions. Agno tool wrapping happens in agents/hr_agent.py.
All functions are read-only (queries only — no writes).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.core.database import (
    get_candidate,
    get_position_candidates,
    vector_search_candidates,
    get_cursor,
)
from backend.core.config import embed_text
from backend.routes.matching import score_candidate_against_position

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _get_position_by_id(position_id: int) -> dict | None:
    """Fetch a position row by integer id (database.get_position takes slug)."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM positions WHERE id = %s", (position_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))


def _apply_post_filters(rows: list[dict], filters: dict) -> list[dict]:
    """In-Python post-filtering for fields not pushed into SQL."""
    if not filters:
        return rows

    min_exp = filters.get("min_experience") or filters.get("min_experience_years")
    max_exp = filters.get("max_experience") or filters.get("max_experience_years")
    skills_req = filters.get("skills") or []
    location = filters.get("location")
    seniority = filters.get("seniority")

    out = []
    for r in rows:
        years = r.get("total_experience_years") or r.get("experience_years") or 0
        if min_exp is not None and (years or 0) < float(min_exp):
            continue
        if max_exp is not None and (years or 0) > float(max_exp):
            continue
        if skills_req:
            cv_skills = [s.lower() for s in (r.get("skills_technical") or [])]
            if not any(req.lower() in cv_skills for req in skills_req):
                continue
        if location:
            loc = (r.get("location") or "").lower()
            if location.lower() == "remote":
                # accept either explicit "remote" location or no-location-as-remote? be strict
                if "remote" not in loc:
                    continue
            elif location.lower() not in loc:
                continue
        if seniority and (r.get("seniority_level") or "").lower() != seniority.lower():
            continue
        out.append(r)
    return out


def _shape_search_row(r: dict, source: str, score: float | None = None) -> dict:
    """Project a candidate row into the compact tool-return shape."""
    skills = r.get("skills_technical") or []
    return {
        "id": r.get("id") or r.get("candidate_id"),
        "name": r.get("name"),
        "current_role": r.get("current_role"),
        "skills_technical": skills[:5],
        "experience_years": r.get("total_experience_years"),
        "match_score": round(float(score), 3) if score is not None else None,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def query_cvs(
    query: str,
    filters: dict | None = None,
    k: int = 10,
    tenant_id: int | None = None,
) -> list[dict]:
    """Search the central CV repository.

    If `query` is non-empty: semantic search via candidate_embeddings (pgvector).
    Otherwise: filter-only listing falling back to ILIKE.

    `filters` keys (all optional): min_experience / max_experience, skills (list),
    location (string; "remote" matches the literal token), seniority.

    `tenant_id` is currently unused — the repo is single-tenant at the data layer
    (visibility/owner_id columns exist on `candidates` but the existing query
    helpers in core/database.py don't filter by tenant). TODO: thread tenant_id
    through once core/database.py grows tenant-scoped helpers.
    """
    filters = filters or {}
    k = max(1, int(k))
    query_str = (query or "").strip()

    # ---- Semantic path -----------------------------------------------------
    if query_str:
        try:
            # embed_text is async — run sync from this sync function
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Caller is async; this sync entry can't await — fall through.
                    raise RuntimeError("event_loop_running")
                embedding = loop.run_until_complete(embed_text(query_str))
            except RuntimeError:
                embedding = asyncio.run(embed_text(query_str))
        except Exception as e:
            logger.warning(f"query_cvs: embedding failed ({e}); falling back to ILIKE")
            embedding = None

        if embedding:
            # Over-fetch then post-filter in Python so filters can shrink the set
            raw = vector_search_candidates(embedding, limit=max(k * 4, 20))
            filtered = _apply_post_filters(raw, filters)
            return [
                _shape_search_row(r, source="semantic", score=r.get("similarity"))
                for r in filtered[:k]
            ]

        # Fallback: ILIKE on name + skills_technical (array text)
        # TODO: replace with a proper text-search helper in core/database.py
        like = f"%{query_str}%"
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, name, current_role, skills_technical,
                       total_experience_years, seniority_level, location
                FROM candidates
                WHERE status = 'active'
                  AND (name ILIKE %s
                       OR current_role ILIKE %s
                       OR array_to_string(skills_technical, ' ') ILIKE %s)
                ORDER BY quality_score DESC NULLS LAST, created_at DESC
                LIMIT %s
                """,
                (like, like, like, max(k * 4, 20)),
            )
            cols = [desc[0] for desc in cur.description]
            raw = [dict(zip(cols, row)) for row in cur.fetchall()]
        filtered = _apply_post_filters(raw, filters)
        return [_shape_search_row(r, source="filter") for r in filtered[:k]]

    # ---- Filter-only path --------------------------------------------------
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, current_role, skills_technical,
                   total_experience_years, seniority_level, location
            FROM candidates
            WHERE status = 'active'
            ORDER BY quality_score DESC NULLS LAST, created_at DESC
            LIMIT %s
            """,
            (max(k * 4, 50),),
        )
        cols = [desc[0] for desc in cur.description]
        raw = [dict(zip(cols, row)) for row in cur.fetchall()]
    filtered = _apply_post_filters(raw, filters)
    return [_shape_search_row(r, source="filter") for r in filtered[:k]]


def get_candidate_brief(cand_id: int) -> dict:
    """Return a compact, LLM-safe candidate dict (no raw_text / large blobs)."""
    cand = get_candidate(int(cand_id))
    if not cand:
        return {}

    # Compact experience: list of {title, company, years} from each entry
    exp_summary: list[dict] = []
    for e in (cand.get("experience") or [])[:8]:
        if not isinstance(e, dict):
            continue
        exp_summary.append({
            "title": e.get("title") or e.get("role"),
            "company": e.get("company"),
            "start": e.get("start") or e.get("start_date"),
            "end": e.get("end") or e.get("end_date"),
        })

    edu_summary: list[dict] = []
    for ed in (cand.get("education") or [])[:6]:
        if not isinstance(ed, dict):
            continue
        edu_summary.append({
            "degree": ed.get("degree"),
            "field": ed.get("field") or ed.get("major"),
            "institution": ed.get("institution") or ed.get("school"),
            "year": ed.get("year") or ed.get("end") or ed.get("graduation_year"),
        })

    demographics = {
        k: cand.get(k) for k in (
            "dob", "national_id", "gender", "marital_status", "nationality",
            "religion", "height", "weight", "father_name",
        ) if cand.get(k) is not None
    }

    return {
        "id": cand.get("id"),
        "name": cand.get("name"),
        "email": cand.get("email"),
        "phone": cand.get("phone"),
        "location": cand.get("location"),
        "current_role": cand.get("current_role"),
        "current_company": cand.get("current_company"),
        "total_experience_years": cand.get("total_experience_years"),
        "seniority_level": cand.get("seniority_level"),
        "skills_technical": cand.get("skills_technical") or [],
        "skills_soft": cand.get("skills_soft") or [],
        "experience_summary": exp_summary,
        "education_summary": edu_summary,
        "certifications": cand.get("certifications") or [],
        "summary_short": cand.get("summary_short"),
        "demographics": demographics,
    }


def score_cv_vs_position(cand_id: int, position_id: int) -> dict:
    """Score a candidate against a position. Returns the 7 dimensions + composite + explanation."""
    candidate = get_candidate(int(cand_id))
    if not candidate:
        return {"error": "candidate_not_found", "candidate_id": cand_id}

    position = _get_position_by_id(int(position_id))
    if not position:
        return {"error": "position_not_found", "position_id": position_id}

    scores = score_candidate_against_position(candidate, position)

    # Build a short explanation from the matched/missing skills (the existing
    # scorer does not return a free-text explanation field — that's generated
    # asynchronously elsewhere via _generate_match_explanation in routes/matching.py).
    matched = scores.get("skills_matched", []) or []
    missing = scores.get("skills_missing", []) or []
    parts: list[str] = [f"Composite {scores.get('composite')}%."]
    if matched:
        parts.append(f"Matched skills: {', '.join(matched[:6])}.")
    if missing:
        parts.append(f"Missing: {', '.join(missing[:6])}.")
    if scores.get("competency_gaps"):
        parts.append(f"Competency gaps: {len(scores['competency_gaps'])}.")
    explanation = " ".join(parts)

    return {
        "candidate_id": cand_id,
        "position_id": position_id,
        "composite": scores.get("composite"),
        "skills": scores.get("skills"),
        "experience": scores.get("experience"),
        "education": scores.get("education"),
        "certifications": scores.get("certifications"),
        "industry": scores.get("industry"),
        "culture": scores.get("culture"),
        "competency": scores.get("competencies"),
        "skills_matched": matched,
        "skills_missing": missing,
        "explanation": explanation,
    }


def list_candidate_pipeline(position_id: int, stage: str | None = None) -> list[dict]:
    """List candidates in a position's pipeline, optionally filtered by stage."""
    rows = get_position_candidates(int(position_id), stage=stage, limit=200, offset=0)
    out: list[dict] = []
    for r in rows:
        out.append({
            "candidate_id": r.get("candidate_id"),
            "name": r.get("name"),
            "current_role": r.get("current_role"),
            "stage": r.get("stage"),
            "match_score_composite": r.get("match_score_composite"),
            "last_activity": (
                r.get("stage_changed_at")
                or r.get("updated_at")
                or r.get("created_at")
            ),
        })
    return out
