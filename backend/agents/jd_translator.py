"""JD Translator — translates JDs flagged via `translate_to TEXT[]` column.

Loop every JD_TRANSLATE_INTERVAL_S (default 1800s = 30 min). For each JD with
non-empty `translate_to`, translates `jd_text` into each requested language
using LITE_MODEL and stores the body in `jd_translations`. Idempotent: skips
(jd_id, lang) pairs that exist AND aren't stale (jd.updated_at <= translation.created_at).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from datetime import datetime, timezone

from backend.agents.registry import heartbeat, cycle_done
from backend.agents.registry import is_enabled, get_interval
from backend.core.config import LITE_MODEL, llm_call
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)

AGENT_ID = "jd-translator"
INTERVAL_S = int(os.getenv("JD_TRANSLATE_INTERVAL_S", "1800"))

LANG_NAMES = {
    "my": "Burmese (Myanmar)",
    "th": "Thai",
    "id": "Bahasa Indonesia",
    "vi": "Vietnamese",
    "zh": "Simplified Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ar": "Arabic",
    "hi": "Hindi",
}


def _find_targets(limit: int = 25) -> list[tuple[int, str, list[str], "datetime"]]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, jd_text, translate_to, updated_at
               FROM jd_repository
               WHERE COALESCE(status, 'active') = 'active'
                 AND COALESCE(jd_text, '') <> ''
                 AND translate_to IS NOT NULL
                 AND cardinality(translate_to) > 0
               ORDER BY updated_at DESC
               LIMIT %s""",
            (limit,),
        )
        return [(r[0], r[1], list(r[2] or []), r[3]) for r in cur.fetchall()]


def _existing_translations(jd_id: int) -> dict[str, "datetime"]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT lang, created_at FROM jd_translations WHERE jd_id = %s",
            (jd_id,),
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def _upsert_translation(jd_id: int, lang: str, body: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO jd_translations (jd_id, lang, body, created_at)
               VALUES (%s, %s, %s, NOW())
               ON CONFLICT (jd_id, lang) DO UPDATE
               SET body = EXCLUDED.body, created_at = NOW()""",
            (jd_id, lang, body),
        )


def _translate(jd_text: str, lang: str) -> str | None:
    target = LANG_NAMES.get(lang, lang)
    prompt = (
        f"Translate the following Job Description into {target}. "
        f"Preserve structure (headings, bullets, sections). Output ONLY the translated text "
        f"with no preamble, no markdown fences, no explanations.\n\n"
        f"---\n{jd_text[:8000]}"
    )
    return llm_call(prompt, LITE_MODEL, 0.2, 4000)


async def jd_translator_loop():
    logger.info(f"[agent:{AGENT_ID}] starting (interval={INTERVAL_S}s)")
    await asyncio.sleep(35)
    while True:
        if not is_enabled(AGENT_ID):
            try:
                heartbeat(AGENT_ID, status="disabled", action="off")
            except Exception:
                pass
            await asyncio.sleep(60)
            continue
        cycle_start = _time.time()
        events = 0
        try:
            heartbeat(AGENT_ID, status="running", action="scanning for translation requests")
            targets = await asyncio.to_thread(_find_targets, 25)
            for jd_id, jd_text, langs, jd_updated in targets:
                existing = await asyncio.to_thread(_existing_translations, jd_id)
                for lang in langs:
                    if not lang:
                        continue
                    prev = existing.get(lang)
                    if prev and jd_updated and prev >= jd_updated:
                        continue  # idempotent skip
                    heartbeat(AGENT_ID, status="running", action=f"translating jd {jd_id} → {lang}")
                    try:
                        body = await asyncio.to_thread(_translate, jd_text, lang)
                        if body:
                            await asyncio.to_thread(_upsert_translation, jd_id, lang, body)
                            events += 1
                    except Exception as e:
                        logger.warning(f"[agent:{AGENT_ID}] jd {jd_id} lang {lang} failed: {e}")
                    await asyncio.sleep(0.4)
            duration = round(_time.time() - cycle_start, 2)
            cycle_done(AGENT_ID, events=events)
            heartbeat(
                AGENT_ID,
                status="idle",
                next_run_at=datetime.fromtimestamp(_time.time() + INTERVAL_S, timezone.utc),
            )
            logger.info(f"[agent:{AGENT_ID}] cycle done · {events} translations · {duration}s")
        except Exception as e:
            cycle_done(AGENT_ID, error=str(e))
            logger.warning(f"[agent:{AGENT_ID}] loop error: {e}")
        await asyncio.sleep(get_interval(AGENT_ID, INTERVAL_S))
