"""EEO / Diversity Tracking — voluntary self-identification data collection and aggregate reporting."""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.core.database import get_cursor
from backend.core.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{candidate_id}")
async def save_eeo_data(candidate_id: int, request: Request):
    """Save voluntary EEO self-identification data for a candidate.
    This is a public endpoint (no auth required) — called after career page apply."""
    body = await request.json()

    gender = body.get("gender", "prefer_not_to_say")
    ethnicity = body.get("ethnicity", "prefer_not_to_say")
    veteran_status = body.get("veteran_status", "prefer_not_to_say")
    disability_status = body.get("disability_status", "prefer_not_to_say")

    with get_cursor() as cur:
        # Verify candidate exists
        cur.execute("SELECT id FROM candidates WHERE id = %s", (candidate_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Candidate not found")

        cur.execute("""
            INSERT INTO eeo_data (candidate_id, gender, ethnicity, veteran_status, disability_status, voluntarily_provided)
            VALUES (%s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (candidate_id) DO UPDATE SET
                gender = EXCLUDED.gender,
                ethnicity = EXCLUDED.ethnicity,
                veteran_status = EXCLUDED.veteran_status,
                disability_status = EXCLUDED.disability_status,
                created_at = NOW()
        """, (candidate_id, gender, ethnicity, veteran_status, disability_status))

    return {"status": "saved", "candidate_id": candidate_id}


def _aggregate_counts(cur, condition: str = "", params: tuple = ()):
    """Build aggregate diversity report from eeo_data — NO individual data exposed."""
    base_query = "FROM eeo_data e"
    if condition:
        base_query += f" {condition}"

    # Total respondents
    cur.execute(f"SELECT COUNT(*) {base_query}", params)
    total = cur.fetchone()[0]

    if total == 0:
        return {
            "total_respondents": 0,
            "gender": {},
            "ethnicity": {},
            "veteran_status": {},
            "disability_status": {},
        }

    # Gender breakdown
    cur.execute(f"SELECT COALESCE(e.gender, 'prefer_not_to_say'), COUNT(*) {base_query} GROUP BY e.gender", params)
    gender = {row[0]: row[1] for row in cur.fetchall()}

    # Ethnicity breakdown
    cur.execute(f"SELECT COALESCE(e.ethnicity, 'prefer_not_to_say'), COUNT(*) {base_query} GROUP BY e.ethnicity", params)
    ethnicity = {row[0]: row[1] for row in cur.fetchall()}

    # Veteran status breakdown
    cur.execute(f"SELECT COALESCE(e.veteran_status, 'prefer_not_to_say'), COUNT(*) {base_query} GROUP BY e.veteran_status", params)
    veteran_status = {row[0]: row[1] for row in cur.fetchall()}

    # Disability status breakdown
    cur.execute(f"SELECT COALESCE(e.disability_status, 'prefer_not_to_say'), COUNT(*) {base_query} GROUP BY e.disability_status", params)
    disability_status = {row[0]: row[1] for row in cur.fetchall()}

    return {
        "total_respondents": total,
        "gender": gender,
        "ethnicity": ethnicity,
        "veteran_status": veteran_status,
        "disability_status": disability_status,
    }


@router.get("/report")
async def eeo_report(request: Request):
    """Aggregate diversity stats across all candidates — NO individual data exposed."""
    get_current_user(request)

    with get_cursor() as cur:
        return _aggregate_counts(cur)


@router.get("/report/position/{slug}")
async def eeo_report_by_position(slug: str, request: Request):
    """Aggregate diversity stats for candidates in a specific position."""
    get_current_user(request)

    with get_cursor() as cur:
        # Verify position exists
        cur.execute("SELECT id FROM positions WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Position not found")
        position_id = row[0]

        condition = "JOIN position_candidates pc ON pc.candidate_id = e.candidate_id WHERE pc.position_id = %s"
        return _aggregate_counts(cur, condition, (position_id,))
