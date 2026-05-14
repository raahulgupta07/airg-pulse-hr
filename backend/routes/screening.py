"""Screening questions — per-position screening with knockout support."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse

from backend.core.auth import get_current_user
from backend.core.database import get_cursor
from backend.core.permissions import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_position_id(cur, slug: str) -> int:
    """Resolve position slug to id."""
    cur.execute("SELECT id FROM positions WHERE slug = %s", (slug,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Position not found")
    return row[0]


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------
@router.get("/positions/{slug}/screening")
async def list_screening_questions(slug: str, request: Request):
    """List screening questions for a position."""
    get_current_user(request)
    with get_cursor() as cur:
        position_id = _get_position_id(cur, slug)
        cur.execute("""
            SELECT * FROM screening_questions
            WHERE position_id = %s
            ORDER BY sort_order ASC, id ASC
        """, (position_id,))
        cols = [desc[0] for desc in cur.description]
        questions = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"questions": questions, "position_id": position_id}


@router.post("/positions/{slug}/screening", dependencies=[Depends(require_role("hiring_manager"))])
async def add_screening_question(slug: str, request: Request):
    """Add a screening question to a position."""
    user = get_current_user(request)
    body = await request.json()

    question_text = body.get("question")
    if not question_text:
        raise HTTPException(status_code=400, detail="question is required")

    with get_cursor() as cur:
        position_id = _get_position_id(cur, slug)

        # Get next sort order
        cur.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM screening_questions WHERE position_id = %s",
            (position_id,),
        )
        next_order = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO screening_questions (
                position_id, question, question_type, options,
                is_required, is_knockout, knockout_answer, sort_order,
                created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            position_id, question_text,
            body.get("question_type", "text"),
            json.dumps(body.get("options")) if body.get("options") else None,
            body.get("is_required", True),
            body.get("is_knockout", False),
            body.get("knockout_answer"),
            next_order,
            user["user_id"],
        ))
        question_id = cur.fetchone()[0]

    return {"id": question_id, "status": "created"}


@router.delete("/screening/{question_id}", dependencies=[Depends(require_role("hiring_manager"))])
async def delete_screening_question(question_id: int, request: Request):
    """Delete a screening question."""
    get_current_user(request)
    with get_cursor() as cur:
        cur.execute("DELETE FROM screening_questions WHERE id = %s RETURNING id", (question_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Question not found")
    return {"status": "deleted", "id": question_id}


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------
@router.post("/positions/{slug}/screening/answer", dependencies=[Depends(require_role("recruiter"))])
async def submit_screening_answers(slug: str, request: Request):
    """Submit screening answers for a candidate."""
    user = get_current_user(request)
    body = await request.json()

    candidate_id = body.get("candidate_id")
    answers = body.get("answers", [])
    if not candidate_id or not answers:
        raise HTTPException(status_code=400, detail="candidate_id and answers are required")

    with get_cursor() as cur:
        position_id = _get_position_id(cur, slug)

        for ans in answers:
            cur.execute("""
                INSERT INTO screening_answers (
                    position_id, candidate_id, question_id, answer, submitted_by
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (position_id, candidate_id, question_id) DO UPDATE
                SET answer = EXCLUDED.answer, updated_at = NOW()
            """, (
                position_id, candidate_id,
                ans["question_id"], ans["answer"],
                user["user_id"],
            ))

    return {"status": "submitted", "count": len(answers)}


@router.get("/positions/{slug}/screening/results")
async def get_screening_results(slug: str, request: Request):
    """Get all candidate screening answers with pass/fail evaluation."""
    get_current_user(request)

    with get_cursor() as cur:
        position_id = _get_position_id(cur, slug)

        # Get knockout questions
        cur.execute("""
            SELECT id, knockout_answer FROM screening_questions
            WHERE position_id = %s AND is_knockout = TRUE
        """, (position_id,))
        knockouts = {row[0]: row[1] for row in cur.fetchall()}

        # Get all answers grouped by candidate
        cur.execute("""
            SELECT sa.candidate_id, c.name AS candidate_name,
                   sa.question_id, sq.question, sa.answer,
                   sq.is_knockout, sq.knockout_answer
            FROM screening_answers sa
            JOIN candidates c ON c.id = sa.candidate_id
            JOIN screening_questions sq ON sq.id = sa.question_id
            WHERE sa.position_id = %s
            ORDER BY sa.candidate_id, sq.sort_order
        """, (position_id,))
        cols = [desc[0] for desc in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Group by candidate and evaluate pass/fail
    candidates = {}
    for row in rows:
        cid = row["candidate_id"]
        if cid not in candidates:
            candidates[cid] = {
                "candidate_id": cid,
                "candidate_name": row["candidate_name"],
                "answers": [],
                "passed": True,
            }
        answer_entry = {
            "question_id": row["question_id"],
            "question": row["question"],
            "answer": row["answer"],
            "is_knockout": row["is_knockout"],
        }
        # Check knockout
        if row["is_knockout"] and row["knockout_answer"]:
            if str(row["answer"]).strip().lower() != str(row["knockout_answer"]).strip().lower():
                answer_entry["knockout_failed"] = True
                candidates[cid]["passed"] = False
            else:
                answer_entry["knockout_failed"] = False
        candidates[cid]["answers"].append(answer_entry)

    return {"results": list(candidates.values()), "position_id": position_id}
