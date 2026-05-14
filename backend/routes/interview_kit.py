"""Interview Kit routes — generic + tailored question banks per position."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.core.database import get_cursor, get_position, get_candidate
from backend.core.permissions import require_role, has_min_role
from backend.core.rate_limit import limiter
from backend.agents.interview_kit_gen import (
    generate_generic, generate_tailored,
    AUDIENCES, STAGES,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class GenerateRequest(BaseModel):
    candidate_id: Optional[int] = None
    audience: str = "HR_BP"
    stage: str = "SCREEN"
    count: int = 8


class UpdateQuestionRequest(BaseModel):
    question: Optional[str] = None
    look_for: Optional[list[str]] = None
    red_flags: Optional[list[str]] = None
    category: Optional[str] = None
    audience: Optional[str] = None
    stage: Optional[str] = None


def _row_to_dict(cur, row) -> dict:
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


@router.get("/positions/{slug}/interview-kit")
async def list_kit(
    slug: str,
    request: Request,
    candidate_id: Optional[int] = Query(None),
    audience: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    pos = get_position(slug)
    if not pos:
        raise HTTPException(404, "Position not found")

    where = ["position_id = %s"]
    params: list = [pos["id"]]
    if candidate_id is not None:
        where.append("(candidate_id = %s OR candidate_id IS NULL)")
        params.append(candidate_id)
    else:
        where.append("candidate_id IS NULL")
    if audience:
        where.append("audience = %s")
        params.append(audience.upper())
    if stage:
        where.append("stage = %s")
        params.append(stage.upper())

    sql = f"""
        SELECT id, position_id, candidate_id, audience, category, stage,
               question, look_for, red_flags, source, used, used_at,
               created_by, created_at, updated_at
        FROM interview_questions
        WHERE {' AND '.join(where)}
        ORDER BY (candidate_id IS NOT NULL) DESC,
                 CASE category
                   WHEN 'GAP_PROBE' THEN 1 WHEN 'STRENGTH_VERIFY' THEN 2
                   WHEN 'BEHAVIORAL' THEN 3 WHEN 'TECHNICAL' THEN 4
                   WHEN 'ROLE_SPECIFIC' THEN 5 WHEN 'CULTURE' THEN 6 ELSE 9
                 END,
                 created_at DESC
    """
    with get_cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = [_row_to_dict(cur, r) for r in cur.fetchall()]

    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)

    return {
        "position": {"id": pos["id"], "slug": pos["slug"], "title": pos.get("title")},
        "candidate_id": candidate_id,
        "filters": {"audience": audience, "stage": stage},
        "count": len(rows),
        "questions": rows,
        "by_category": by_cat,
    }


@router.post(
    "/positions/{slug}/interview-kit/generate",
    dependencies=[Depends(require_role("recruiter"))],
)
@limiter.limit("10/minute")
async def generate_kit(
    slug: str,
    body: GenerateRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    pos = get_position(slug)
    if not pos:
        raise HTTPException(404, "Position not found")

    audience = (body.audience or "HR_BP").upper()
    stage = (body.stage or "SCREEN").upper()
    if audience not in AUDIENCES:
        raise HTTPException(400, f"audience must be one of {sorted(AUDIENCES)}")
    if stage not in STAGES:
        raise HTTPException(400, f"stage must be one of {sorted(STAGES)}")
    count = max(2, min(20, int(body.count or 8)))

    title = pos.get("title") or "Role"
    jd_text = pos.get("jd_text") or ""

    candidate_id = body.candidate_id
    questions: list[dict]
    source: str
    if candidate_id:
        cand = get_candidate(candidate_id)
        if not cand:
            raise HTTPException(404, "Candidate not found")
        with get_cursor() as cur:
            cur.execute("""
                SELECT match_score_composite, match_explanation,
                       skills_matched, skills_missing,
                       match_score_skills, match_score_experience,
                       match_score_education, match_score_certifications,
                       match_score_industry, match_score_culture
                FROM position_candidates
                WHERE position_id = %s AND candidate_id = %s
                LIMIT 1
            """, (pos["id"], candidate_id))
            r = cur.fetchone()
            match = _row_to_dict(cur, r) if r else {}
        questions = generate_tailored(title, jd_text, cand, match, audience, stage, count)
        source = "ai_tailored"
    else:
        questions = generate_generic(title, jd_text, audience, stage, count)
        source = "ai_generic"

    if not questions:
        raise HTTPException(502, "LLM returned no usable questions")

    inserted: list[dict] = []
    with get_cursor() as cur:
        for q in questions:
            cur.execute("""
                INSERT INTO interview_questions
                  (position_id, candidate_id, audience, category, stage,
                   question, look_for, red_flags, source, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, position_id, candidate_id, audience, category, stage,
                          question, look_for, red_flags, source, used, used_at,
                          created_by, created_at, updated_at
            """, (
                pos["id"], candidate_id, audience, q.get("category", "BEHAVIORAL"),
                stage, q["question"], q.get("look_for", []), q.get("red_flags", []),
                source, user.get("id"),
            ))
            inserted.append(_row_to_dict(cur, cur.fetchone()))

    logger.info(
        f"interview_kit.generated position={pos['id']} candidate={candidate_id} "
        f"audience={audience} stage={stage} n={len(inserted)} source={source}"
    )
    return {"generated": len(inserted), "questions": inserted}


def _auto_generate_kit_for_position(position_id: int, audience: str = "HR_BP", stage: str = "SCREEN", count: int = 8) -> int:
    """Internal: generate generic interview kit for a position (idempotent).

    Skips if a kit already exists for the (position, audience=*, stage=*, candidate_id=NULL).
    Returns number of questions inserted (0 if skipped).
    """
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT 1 FROM interview_questions
                   WHERE position_id=%s AND candidate_id IS NULL LIMIT 1""",
                (position_id,),
            )
            if cur.fetchone():
                return 0  # already has generic kit
            cur.execute("SELECT id, title, jd_text FROM positions WHERE id=%s", (position_id,))
            row = cur.fetchone()
            if not row: return 0
            _pid, title, jd_text = row
        if not jd_text or len(jd_text) < 100:
            return 0  # no JD = nothing to generate from
        questions = generate_generic(title or "Role", jd_text, audience, stage, count)
        if not questions:
            return 0
        with get_cursor() as cur:
            for q in questions:
                cur.execute("""
                    INSERT INTO interview_questions
                      (position_id, candidate_id, audience, category, stage,
                       question, look_for, red_flags, source, created_by)
                    VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, NULL)
                """, (
                    position_id, audience, q.get("category", "BEHAVIORAL"),
                    stage, q["question"], q.get("look_for", []), q.get("red_flags", []),
                    "ai_generic_auto",
                ))
        logger.info(f"[interview-kit-auto] generated {len(questions)} questions for position={position_id}")
        return len(questions)
    except Exception as e:
        logger.warning(f"[interview-kit-auto] failed for position={position_id}: {e}")
        return 0


@router.patch(
    "/interview-kit/{qid}",
    dependencies=[Depends(require_role("recruiter"))],
)
async def update_question(
    qid: int,
    body: UpdateQuestionRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    sets: list[str] = []
    vals: list = []
    if body.question is not None:
        sets.append("question = %s"); vals.append(body.question)
    if body.look_for is not None:
        sets.append("look_for = %s"); vals.append(body.look_for)
    if body.red_flags is not None:
        sets.append("red_flags = %s"); vals.append(body.red_flags)
    if body.category is not None:
        sets.append("category = %s"); vals.append(body.category.upper())
    if body.audience is not None:
        if body.audience.upper() not in AUDIENCES:
            raise HTTPException(400, "bad audience")
        sets.append("audience = %s"); vals.append(body.audience.upper())
    if body.stage is not None:
        if body.stage.upper() not in STAGES:
            raise HTTPException(400, "bad stage")
        sets.append("stage = %s"); vals.append(body.stage.upper())
    if not sets:
        raise HTTPException(400, "no fields to update")
    sets.append("updated_at = NOW()")
    vals.append(qid)

    with get_cursor() as cur:
        cur.execute(
            f"UPDATE interview_questions SET {', '.join(sets)} WHERE id = %s "
            f"RETURNING id, position_id, candidate_id, audience, category, stage, "
            f"question, look_for, red_flags, source, used, used_at, created_by, "
            f"created_at, updated_at",
            tuple(vals),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Question not found")
        return _row_to_dict(cur, row)


@router.delete(
    "/interview-kit/{qid}",
    dependencies=[Depends(require_role("recruiter"))],
)
async def delete_question(qid: int, request: Request, user: dict = Depends(get_current_user)):
    with get_cursor() as cur:
        cur.execute("DELETE FROM interview_questions WHERE id = %s RETURNING id", (qid,))
        if not cur.fetchone():
            raise HTTPException(404, "Question not found")
    return {"deleted": qid}


@router.post(
    "/interview-kit/{qid}/used",
    dependencies=[Depends(require_role("recruiter"))],
)
async def mark_used(qid: int, request: Request, user: dict = Depends(get_current_user)):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE interview_questions SET used = TRUE, used_at = NOW() "
            "WHERE id = %s RETURNING id, used, used_at",
            (qid,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Question not found")
        return {"id": row[0], "used": row[1], "used_at": row[2]}


@router.get("/positions/{slug}/interview-kit/export.md")
async def export_kit_markdown(
    slug: str,
    request: Request,
    candidate_id: Optional[int] = Query(None),
    audience: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """Plain-markdown export — copy/paste friendly. PDF can be wrapped client-side."""
    pos = get_position(slug)
    if not pos:
        raise HTTPException(404, "Position not found")

    where = ["position_id = %s"]
    params: list = [pos["id"]]
    if candidate_id is not None:
        where.append("(candidate_id = %s OR candidate_id IS NULL)")
        params.append(candidate_id)
    else:
        where.append("candidate_id IS NULL")
    if audience:
        where.append("audience = %s"); params.append(audience.upper())
    if stage:
        where.append("stage = %s"); params.append(stage.upper())

    with get_cursor() as cur:
        cur.execute(
            f"SELECT category, question, look_for, red_flags, audience, stage "
            f"FROM interview_questions WHERE {' AND '.join(where)} "
            f"ORDER BY category, created_at",
            tuple(params),
        )
        rows = cur.fetchall()

    cand_name = ""
    if candidate_id:
        c = get_candidate(candidate_id)
        if c:
            cand_name = c.get("name") or f"Candidate {candidate_id}"

    lines = [
        f"# Interview Kit — {pos.get('title') or slug}",
        f"_Audience: {audience or 'ALL'} · Stage: {stage or 'ALL'}_"
        + (f" · Tailored for: **{cand_name}**" if cand_name else ""),
        "",
    ]
    by_cat: dict[str, list] = {}
    for cat, q, lf, rf, aud, st in rows:
        by_cat.setdefault(cat, []).append((q, lf or [], rf or [], aud, st))
    for cat, items in by_cat.items():
        lines.append(f"## {cat}  ·  {len(items)} questions")
        lines.append("")
        for i, (q, lf, rf, aud, st) in enumerate(items, 1):
            lines.append(f"**Q{i}.** {q}")
            if lf:
                lines.append(f"- **Look for:** {' · '.join(lf)}")
            if rf:
                lines.append(f"- **Red flags:** {' · '.join(rf)}")
            lines.append("")

    body_text = "\n".join(lines)
    fname = f"interview-kit-{slug}.md"
    return Response(
        content=body_text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
