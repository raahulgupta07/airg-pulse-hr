"""JD Completeness Scorer — nightly heuristic 0-100 score per active JD.

Loop every JD_COMPLETENESS_INTERVAL_S (default 86400s = 24h). Iterates ALL
active JDs and writes `completeness_score` (0-100) based on field presence
heuristics. Emits a `jd_incomplete` notification when score < 50 (deduped 7d).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from datetime import datetime, timezone

from backend.agents.registry import heartbeat, cycle_done
from backend.agents.registry import is_enabled, get_interval
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)

AGENT_ID = "jd-completeness"
INTERVAL_S = int(os.getenv("JD_COMPLETENESS_INTERVAL_S", "86400"))
LOW_THRESHOLD = int(os.getenv("JD_COMPLETENESS_LOW", "50"))


def _score_row(row: dict) -> int:
    score = 0
    if (row.get("title") or "").strip():
        score += 20
    if (row.get("min_experience_years") or 0) and int(row["min_experience_years"]) > 0:
        score += 15
    skills = row.get("required_skills") or []
    if isinstance(skills, list) and len(skills) >= 3:
        score += 20
    if (row.get("seniority_level") or "").strip():
        score += 15
    if (row.get("department") or "").strip():
        score += 10
    jd_text = row.get("jd_text") or ""
    if len(jd_text) > 500:
        score += 10
    if (row.get("location") or "").strip() or (row.get("employment_type") or "").strip():
        # location column may not exist on all schemas; fall back to employment_type as proxy
        score += 10
    return min(100, score)


def _has_location_column() -> bool:
    with get_cursor() as cur:
        cur.execute(
            """SELECT 1 FROM information_schema.columns
               WHERE table_name='jd_repository' AND column_name='location'"""
        )
        return cur.fetchone() is not None


def _fetch_all(has_location: bool) -> list[dict]:
    loc_col = ", location" if has_location else ", NULL::text AS location"
    with get_cursor() as cur:
        cur.execute(
            f"""SELECT id, title, department, seniority_level, employment_type,
                       jd_text, required_skills, min_experience_years, created_by
                       {loc_col}
                FROM jd_repository
                WHERE COALESCE(status, 'active') = 'active'"""
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _store_score(jd_id: int, score: int) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE jd_repository SET completeness_score = %s WHERE id = %s",
            (score, jd_id),
        )


def _notify_incomplete(jd_id: int, title: str | None, score: int, created_by: int | None) -> None:
    with get_cursor() as cur:
        cur.execute(
            """SELECT 1 FROM notifications
               WHERE type='jd_incomplete' AND link=%s
                 AND created_at > NOW() - INTERVAL '7 days'
               LIMIT 1""",
            (f"/jds/{jd_id}",),
        )
        if cur.fetchone():
            return
        name = title or f"JD #{jd_id}"
        cur.execute(
            """INSERT INTO notifications (user_id, type, title, message, link)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                created_by or 1,
                "jd_incomplete",
                f"Incomplete JD: {name}",
                f"{name} scored {score}/100 on completeness. Add missing fields "
                f"(skills, seniority, experience, department) to improve match quality.",
                f"/jds/{jd_id}",
            ),
        )


async def jd_completeness_loop():
    logger.info(f"[agent:{AGENT_ID}] starting (interval={INTERVAL_S}s · low={LOW_THRESHOLD})")
    await asyncio.sleep(40)
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
            heartbeat(AGENT_ID, status="running", action="scoring all active JDs")
            has_location = await asyncio.to_thread(_has_location_column)
            rows = await asyncio.to_thread(_fetch_all, has_location)
            for row in rows:
                try:
                    score = _score_row(row)
                    await asyncio.to_thread(_store_score, row["id"], score)
                    if score < LOW_THRESHOLD:
                        await asyncio.to_thread(
                            _notify_incomplete, row["id"], row.get("title"), score, row.get("created_by")
                        )
                        events += 1
                except Exception as e:
                    logger.warning(f"[agent:{AGENT_ID}] jd {row.get('id')} failed: {e}")
            duration = round(_time.time() - cycle_start, 2)
            cycle_done(AGENT_ID, events=events)
            heartbeat(
                AGENT_ID,
                status="idle",
                next_run_at=datetime.fromtimestamp(_time.time() + INTERVAL_S, timezone.utc),
            )
            logger.info(f"[agent:{AGENT_ID}] cycle done · {len(rows)} scored · {events} flagged low · {duration}s")
        except Exception as e:
            cycle_done(AGENT_ID, error=str(e))
            logger.warning(f"[agent:{AGENT_ID}] loop error: {e}")
        await asyncio.sleep(get_interval(AGENT_ID, INTERVAL_S))
