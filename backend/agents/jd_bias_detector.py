"""JD Bias Detector — flags gendered/ageist/ableist language in JDs.

Loop every JD_BIAS_INTERVAL_S (default 1800s = 30 min). For JDs created or
updated since the last successful scan, asks LITE_MODEL to classify and stores
the JSON result in `jd_repository.bias_report`. When `flagged=true`, emits a
PULSE FEED notification (`type='jd_bias'`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
from datetime import datetime, timezone

from backend.agents.registry import heartbeat, cycle_done
from backend.agents.registry import is_enabled, get_interval
from backend.core.config import LITE_MODEL, llm_call
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)

AGENT_ID = "jd-bias"
INTERVAL_S = int(os.getenv("JD_BIAS_INTERVAL_S", "1800"))

PROMPT = (
    "You are a hiring-bias auditor. Inspect this Job Description for gendered, "
    "ageist, or ableist language. Return STRICT JSON only:\n"
    '{"flagged": bool, "issues": [{"phrase": str, "type": "gender|age|ability|other", "suggestion": str}]}\n'
    "Empty issues array means no bias detected. No prose, no markdown.\n\n"
    "JD:\n"
)


def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        # try to slice braces
        try:
            i, j = s.find("{"), s.rfind("}")
            if i >= 0 and j > i:
                return json.loads(s[i:j + 1])
        except Exception:
            return None
    return None


def _find_targets(limit: int = 25) -> list[tuple[int, str, str | None, int | None]]:
    """JDs whose bias_report is missing OR stale (jd updated after last scan)."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, jd_text, title, created_by
               FROM jd_repository
               WHERE COALESCE(status, 'active') = 'active'
                 AND COALESCE(jd_text, '') <> ''
                 AND (
                     bias_report IS NULL
                     OR (bias_report->>'_scanned_at') IS NULL
                     OR (bias_report->>'_scanned_at')::timestamptz < updated_at
                 )
               ORDER BY updated_at DESC
               LIMIT %s""",
            (limit,),
        )
        return [(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]


def _store(jd_id: int, report: dict) -> None:
    report = dict(report or {})
    report["_scanned_at"] = datetime.now(timezone.utc).isoformat()
    with get_cursor() as cur:
        cur.execute(
            "UPDATE jd_repository SET bias_report = %s WHERE id = %s",
            (json.dumps(report), jd_id),
        )


def _notify(jd_id: int, title: str | None, created_by: int | None, n_issues: int) -> None:
    name = title or f"JD #{jd_id}"
    msg = f"AI flagged {n_issues} potentially biased phrase(s) in {name}. Review the JD for gendered/ageist/ableist language."
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO notifications (user_id, type, title, message, link)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                created_by or 1,
                "jd_bias",
                f"Bias flagged: {name}",
                msg,
                f"/jds/{jd_id}",
            ),
        )


async def jd_bias_loop():
    logger.info(f"[agent:{AGENT_ID}] starting (interval={INTERVAL_S}s)")
    await asyncio.sleep(25)
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
            heartbeat(AGENT_ID, status="running", action="scanning JDs for bias")
            targets = await asyncio.to_thread(_find_targets, 25)
            for jd_id, jd_text, title, created_by in targets:
                heartbeat(AGENT_ID, status="running", action=f"scanning jd {jd_id}")
                try:
                    raw = await asyncio.to_thread(
                        llm_call, PROMPT + (jd_text or "")[:6000], LITE_MODEL, 0.1, 800
                    )
                    parsed = _parse_json(raw or "") or {"flagged": False, "issues": []}
                    flagged = bool(parsed.get("flagged"))
                    issues = list(parsed.get("issues") or [])
                    parsed["flagged"] = flagged
                    parsed["issues"] = issues
                    await asyncio.to_thread(_store, jd_id, parsed)
                    if flagged and issues:
                        await asyncio.to_thread(_notify, jd_id, title, created_by, len(issues))
                        events += 1
                except Exception as e:
                    logger.warning(f"[agent:{AGENT_ID}] jd {jd_id} failed: {e}")
                await asyncio.sleep(0.4)
            duration = round(_time.time() - cycle_start, 2)
            cycle_done(AGENT_ID, events=events)
            heartbeat(
                AGENT_ID,
                status="idle",
                next_run_at=datetime.fromtimestamp(_time.time() + INTERVAL_S, timezone.utc),
            )
            logger.info(f"[agent:{AGENT_ID}] cycle done · {len(targets)} scanned · {events} flagged · {duration}s")
        except Exception as e:
            cycle_done(AGENT_ID, error=str(e))
            logger.warning(f"[agent:{AGENT_ID}] loop error: {e}")
        await asyncio.sleep(get_interval(AGENT_ID, INTERVAL_S))
