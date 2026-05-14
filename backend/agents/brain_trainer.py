"""Brain Trainer agent — scans Copilot Q&A history every 6h for low-confidence
or "I don't know" assistant responses, logs them to brain_unanswered table,
and notifies admins via PULSE FEED.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from backend.core.database import get_cursor
from backend.core.config import LITE_MODEL, llm_call, is_ai_available
from backend.agents.registry import heartbeat, cycle_done
from backend.agents.registry import is_enabled, get_interval

logger = logging.getLogger(__name__)

INTERVAL_S = 6 * 60 * 60  # 6h
AGENT_ID = "brain-trainer"

# Regex patterns for fast pre-filter before LLM classifier
_LOW_CONF_PATTERNS = [
    re.compile(r"\bi\s+don'?t\s+know\b", re.I),
    re.compile(r"\bi\s+do\s+not\s+know\b", re.I),
    re.compile(r"\bnot\s+sure\b", re.I),
    re.compile(r"\bunable\s+to\s+(answer|find|determine|locate)\b", re.I),
    re.compile(r"\bno\s+(information|data|results?)\s+(found|available)\b", re.I),
    re.compile(r"\bi\s+(can'?t|cannot)\s+(find|answer|help)\b", re.I),
    re.compile(r"\bsorry,?\s+i\s+(don'?t|can'?t|cannot)\b", re.I),
    re.compile(r"\bcouldn'?t\s+find\b", re.I),
    re.compile(r"\bno\s+matching\b", re.I),
]


def _is_low_confidence(text: str) -> bool:
    """Fast regex pre-filter."""
    if not text or not text.strip():
        return True  # empty is low-conf
    if len(text.strip()) < 20:
        return True  # too short to be useful
    for p in _LOW_CONF_PATTERNS:
        if p.search(text):
            return True
    return False


def _llm_confirm_low_conf(question: str, answer: str) -> bool:
    """LLM second-pass classifier (LITE_MODEL, ~$0.0003)."""
    if not is_ai_available():
        return True  # fall through to pattern-only signal
    prompt = (
        "You are a QA classifier. Given a user's question and the assistant's reply, "
        "decide if the assistant FAILED to give a substantive answer (i.e. said it "
        "doesn't know, gave a fallback / canned 'cannot help', or returned irrelevant text). "
        "Respond with EXACTLY one word: YES (failed) or NO (answered substantively).\n\n"
        f"QUESTION: {question[:500]}\n\n"
        f"ANSWER: {answer[:1000]}\n\n"
        "Verdict (YES / NO):"
    )
    try:
        out = llm_call(prompt, model=LITE_MODEL, temperature=0.0, max_tokens=8)
        if not out:
            return True
        return out.strip().upper().startswith("YES")
    except Exception as e:
        logger.warning(f"[brain-trainer] llm classify failed: {e}")
        return True


def _get_last_run_at() -> datetime | None:
    with get_cursor() as cur:
        cur.execute("SELECT MAX(asked_at) FROM brain_unanswered")
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def _scan_chat_messages_since(since: datetime | None) -> list[tuple[int, int, str, str]]:
    """Returns list of (assistant_msg_id, session_id, user_question, assistant_answer)."""
    with get_cursor() as cur:
        # Find assistant messages in time window, paired with prior user question in same session
        if since:
            cur.execute(
                """SELECT a.id, a.session_id, a.content AS assistant_content, a.created_at
                   FROM chat_messages a
                   WHERE a.role = 'assistant' AND a.created_at > %s
                   ORDER BY a.created_at DESC
                   LIMIT 500""",
                (since,),
            )
        else:
            cur.execute(
                """SELECT a.id, a.session_id, a.content AS assistant_content, a.created_at
                   FROM chat_messages a
                   WHERE a.role = 'assistant'
                   ORDER BY a.created_at DESC
                   LIMIT 200""",
            )
        rows = cur.fetchall()

        out = []
        for aid, sid, ans_text, _created in rows:
            # Find immediately preceding user msg
            cur.execute(
                """SELECT content FROM chat_messages
                   WHERE session_id = %s AND role = 'user' AND id < %s
                   ORDER BY id DESC LIMIT 1""",
                (sid, aid),
            )
            urow = cur.fetchone()
            if not urow:
                continue
            out.append((aid, sid, urow[0], ans_text or ""))
        return out


def _already_logged(question: str, session_id: int) -> bool:
    with get_cursor() as cur:
        cur.execute(
            """SELECT 1 FROM brain_unanswered
               WHERE session_id = %s AND question = %s LIMIT 1""",
            (session_id, question),
        )
        return cur.fetchone() is not None


def _insert_unanswered(question: str, session_id: int) -> int | None:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO brain_unanswered (question, session_id)
               VALUES (%s, %s) RETURNING id""",
            (question, session_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _notify_admins(unanswered_id: int, question: str):
    try:
        with get_cursor() as cur:
            cur.execute("SELECT id FROM users WHERE role IN ('admin','superadmin')")
            admins = [r[0] for r in cur.fetchall()]
            for uid in admins:
                cur.execute(
                    """INSERT INTO notifications (user_id, type, title, message, link)
                       VALUES (%s, 'brain_unanswered', %s, %s, %s)""",
                    (
                        uid,
                        "Copilot couldn't answer a question",
                        question[:240],
                        f"/admin?tab=brain&unanswered_id={unanswered_id}",
                    ),
                )
    except Exception as e:
        logger.warning(f"[brain-trainer] notify admins failed: {e}")


async def brain_trainer_loop():
    logger.info(f"[brain-trainer] starting (interval={INTERVAL_S}s)")
    await asyncio.sleep(30)
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
            heartbeat(AGENT_ID, status="running", action="scanning chat_messages")
            since = await asyncio.to_thread(_get_last_run_at)
            rows = await asyncio.to_thread(_scan_chat_messages_since, since)

            for aid, sid, q, a in rows:
                if not _is_low_confidence(a):
                    continue
                if await asyncio.to_thread(_already_logged, q, sid):
                    continue
                # LLM confirm only when regex matched (cheap second-pass)
                confirmed = await asyncio.to_thread(_llm_confirm_low_conf, q, a)
                if not confirmed:
                    continue
                new_id = await asyncio.to_thread(_insert_unanswered, q, sid)
                if new_id:
                    await asyncio.to_thread(_notify_admins, new_id, q)
                    events += 1
            heartbeat(AGENT_ID, status="idle")
        except Exception as e:
            err = str(e)[:200]
            logger.exception(f"[brain-trainer] cycle error: {e}")
        cycle_done(AGENT_ID, events=events, error=err)
        await asyncio.sleep(get_interval(AGENT_ID, INTERVAL_S))
