"""Position provider — wraps backend.core.database + backend.routes.positions.

Read-only queries. Tool wrapping in agents/hr_agent.py.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.core.database import (
    get_position,
    list_positions,
    get_pipeline_counts,
    get_position_candidates,
)

logger = logging.getLogger(__name__)

# Pipeline stages we always surface (zero-fill if absent).
_PIPELINE_STAGES = ("sourced", "screening", "offer", "hired", "rejected")


def query_positions(filter: Optional[dict] = None) -> list[dict]:
    """List positions with optional filters.

    filter keys:
      - status: 'open' | 'closed'
      - department: case-insensitive substring match
      - min_match_score: only positions whose avg_match >= this value
    """
    filter = filter or {}
    status = filter.get("status")
    department = filter.get("department")
    min_match_score = filter.get("min_match_score")

    rows = list_positions(status=status)

    out: list[dict] = []
    for r in rows:
        if department:
            dep = (r.get("department") or "")
            if department.lower() not in dep.lower():
                continue
        avg_match = r.get("avg_match")
        if min_match_score is not None:
            try:
                if avg_match is None or float(avg_match) < float(min_match_score):
                    continue
            except (TypeError, ValueError):
                continue

        out.append({
            "id": r.get("id"),
            "slug": r.get("slug"),
            "title": r.get("title"),
            "department": r.get("department"),
            "status": r.get("status"),
            "cv_count": r.get("cv_count") or 0,
            "avg_match": float(avg_match) if avg_match is not None else None,
            "created_at": r.get("created_at"),
        })
    return out


def get_position_brief(slug: str) -> dict:
    """Compact, agent-friendly position summary by slug.

    Returns {} if not found.
    """
    p = get_position(slug)
    if not p:
        return {}

    jd_text = p.get("jd_text") or ""
    return {
        "id": p.get("id"),
        "slug": p.get("slug"),
        "title": p.get("title"),
        "department": p.get("department"),
        "required_skills": p.get("required_skills") or [],
        "min_experience_years": p.get("min_experience_years"),
        "weights": {
            "skills": p.get("weight_skills"),
            "experience": p.get("weight_experience"),
            "education": p.get("weight_education"),
            "certifications": p.get("weight_certifications"),
            "industry": p.get("weight_industry"),
            "culture": p.get("weight_culture"),
            "competencies": p.get("weight_competencies"),
        },
        "status": p.get("status"),
        "jd_summary": jd_text[:500],
    }


def get_pipeline(position_id: int) -> dict:
    """Pipeline stage counts for a position (zero-filled across known stages)."""
    counts = get_pipeline_counts(position_id) or {}
    out = {stage: int(counts.get(stage, 0)) for stage in _PIPELINE_STAGES}
    out["total"] = sum(int(v) for v in counts.values())
    return out


def get_position_top_candidates(position_id: int, k: int = 5) -> list[dict]:
    """Top-k candidates for a position, ranked by match_score_composite."""
    rows = get_position_candidates(position_id, limit=k)
    out: list[dict] = []
    for r in rows:
        skills = r.get("skills_technical") or []
        out.append({
            "name": r.get("name"),
            "match_score_composite": r.get("match_score_composite"),
            "current_role": r.get("current_role"),
            "top_3_skills": list(skills)[:3],
        })
    return out
