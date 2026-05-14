"""Q&A Suggester agent — every 1 min picks pending qa_suggestion_queue rows,
generates 3 short interview questions for each (candidate_id, position_id) pair
via LITE_MODEL, stores in suggestions JSONB column.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from backend.core.database import get_cursor
from backend.core.config import LITE_MODEL, llm_call, is_ai_available
from backend.agents.registry import heartbeat, cycle_done
from backend.agents.registry import is_enabled, get_interval

logger = logging.getLogger(__name__)

INTERVAL_S = 60
AGENT_ID = "qa-suggester"


def _fetch_pending(limit: int = 10) -> list[tuple[int, int, int]]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, candidate_id, position_id FROM qa_suggestion_queue
               WHERE fulfilled = FALSE
               ORDER BY requested_at LIMIT %s""",
            (limit,),
        )
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def _build_brief(candidate_id: int, position_id: int) -> tuple[str, str]:
    cand_brief = ""
    pos_brief = ""
    with get_cursor() as cur:
        cur.execute(
            """SELECT name, current_role, current_company, total_experience_years,
                      skills, ai_summary
               FROM candidates WHERE id = %s""",
            (candidate_id,),
        )
        r = cur.fetchone()
        if r:
            name, role, company, yrs, skills, summ = r
            cand_brief = (
                f"Name: {name or '-'}\n"
                f"Role: {role or '-'} at {company or '-'}\n"
                f"Experience: {yrs or 0}y\n"
                f"Skills: {', '.join((skills or [])[:15])}\n"
                f"Summary: {(summ or '')[:600]}"
            )
        cur.execute(
            """SELECT title, jd_text, required_skills, seniority_level, department
               FROM positions WHERE id = %s""",
            (position_id,),
        )
        r = cur.fetchone()
        if r:
            title, jd, req_skills, sen, dept = r
            pos_brief = (
                f"Title: {title or '-'}\n"
                f"Department: {dept or '-'} · Seniority: {sen or '-'}\n"
                f"Required skills: {', '.join((req_skills or [])[:15])}\n"
                f"JD excerpt: {(jd or '')[:800]}"
            )
    return cand_brief, pos_brief


def _generate_questions(cand_brief: str, pos_brief: str) -> list[str]:
    if not is_ai_available():
        return [
            "Walk me through your most relevant project for this role.",
            "What gap do you see between your experience and the job requirements?",
            "How would you tackle the first 30 days in this position?",
        ]
    prompt = (
        "You are an expert interviewer. Given the CANDIDATE and POSITION below, "
        "produce EXACTLY 3 short, targeted interview questions that probe the "
        "match-specific gaps and strengths. Return ONLY a valid JSON array of "
        "3 strings — no commentary, no markdown.\n\n"
        f"CANDIDATE:\n{cand_brief}\n\n"
        f"POSITION:\n{pos_brief}\n\n"
        "JSON array:"
    )
    out = llm_call(prompt, model=LITE_MODEL, temperature=0.4, max_tokens=400) or ""
    # Try to parse JSON array out of LLM response
    out = out.strip()
    # Strip code fences
    out = re.sub(r"^```(?:json)?\s*|\s*```$", "", out, flags=re.I | re.M).strip()
    try:
        arr = json.loads(out)
        if isinstance(arr, list):
            qs = [str(x).strip() for x in arr if str(x).strip()][:3]
            if qs:
                return qs
    except Exception:
        pass
    # Fallback: split lines
    lines = [re.sub(r"^[\d\-\.\)\s]+", "", ln).strip() for ln in out.splitlines() if ln.strip()]
    lines = [ln.strip(' "\'') for ln in lines if len(ln) > 8][:3]
    return lines or ["Tell us about your most impactful achievement."]


def _store(qid: int, suggestions: list[str]):
    with get_cursor() as cur:
        cur.execute(
            """UPDATE qa_suggestion_queue
               SET suggestions = %s::jsonb, fulfilled = TRUE
               WHERE id = %s""",
            (json.dumps(suggestions), qid),
        )


async def qa_suggester_loop():
    logger.info(f"[qa-suggester] starting (interval={INTERVAL_S}s)")
    await asyncio.sleep(20)
    while True:
        if not is_enabled(AGENT_ID):
            try:
                heartbeat(AGENT_ID, status="disabled", action="off")
            except Exception:
                pass
            await asyncio.sleep(60)
            continue
        events = 0
        err = None
        try:
            heartbeat(AGENT_ID, status="running", action="scanning qa_suggestion_queue")
            pending = await asyncio.to_thread(_fetch_pending)
            for qid, cid, pid in pending:
                heartbeat(AGENT_ID, status="running", action=f"q&a for c{cid}/p{pid}")
                try:
                    cand, pos = await asyncio.to_thread(_build_brief, cid, pid)
                    qs = await asyncio.to_thread(_generate_questions, cand, pos)
                    await asyncio.to_thread(_store, qid, qs)
                    events += 1
                except Exception as ie:
                    logger.warning(f"[qa-suggester] qid={qid} failed: {ie}")
                    # Still mark fulfilled with empty to prevent re-loop
                    try:
                        await asyncio.to_thread(_store, qid, [])
                    except Exception:
                        pass
            heartbeat(AGENT_ID, status="idle")
        except Exception as e:
            err = str(e)[:200]
            logger.exception(f"[qa-suggester] cycle error: {e}")
        cycle_done(AGENT_ID, events=events, error=err)
        await asyncio.sleep(get_interval(AGENT_ID, INTERVAL_S))
