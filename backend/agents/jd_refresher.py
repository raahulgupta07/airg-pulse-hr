"""JD Refresh Agent — flags stale JDs whose linked positions are still open.

Loop every 6h. Finds JDs with `updated_at < NOW() - INTERVAL 'JD_REFRESH_DAYS days'`
AND linked to a position whose `lifecycle_stage NOT IN ('filled','archived')`.
Inserts one notification (`type='jd_stale'`) per JD per cycle (dedupes against
recent notifications by message link).
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

AGENT_ID = "jd-refresh"
INTERVAL_S = int(os.getenv("JD_REFRESH_INTERVAL_S", str(6 * 3600)))
THRESHOLD_DAYS = int(os.getenv("JD_REFRESH_DAYS", "60"))


def _find_stale_jds() -> list[tuple[int, str, int | None]]:
    """JDs whose linked open positions are stale and have no recent jd_stale notif."""
    with get_cursor() as cur:
        cur.execute(
            f"""SELECT DISTINCT j.id, j.title, j.created_by
                FROM jd_repository j
                JOIN positions p ON p.weights_source_jd_id = j.id
                WHERE COALESCE(j.status, 'active') = 'active'
                  AND j.updated_at < NOW() - INTERVAL '{THRESHOLD_DAYS} days'
                  AND COALESCE(p.lifecycle_stage, 'sourcing') NOT IN ('filled', 'archived')
                  AND NOT EXISTS (
                      SELECT 1 FROM notifications n
                      WHERE n.type = 'jd_stale'
                        AND n.link = '/jds/' || j.id::text
                        AND n.created_at > NOW() - INTERVAL '7 days'
                  )
                ORDER BY j.id"""
        )
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def _insert_notif(jd_id: int, title: str | None, created_by: int | None) -> None:
    name = title or f"JD #{jd_id}"
    msg = (
        f"{name} hasn't been updated in {THRESHOLD_DAYS}+ days but linked positions "
        f"are still open. Consider refreshing requirements, salary band, and skills."
    )
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO notifications (user_id, type, title, message, link)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                created_by or 1,
                "jd_stale",
                f"Stale JD: {name}",
                msg,
                f"/jds/{jd_id}",
            ),
        )


async def jd_refresh_loop():
    logger.info(f"[agent:{AGENT_ID}] starting (interval={INTERVAL_S}s · threshold={THRESHOLD_DAYS}d)")
    await asyncio.sleep(30)
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
            heartbeat(AGENT_ID, status="running", action="scanning for stale JDs")
            targets = await asyncio.to_thread(_find_stale_jds)
            for jd_id, title, created_by in targets:
                try:
                    await asyncio.to_thread(_insert_notif, jd_id, title, created_by)
                    events += 1
                except Exception as e:
                    logger.warning(f"[agent:{AGENT_ID}] notify failed for jd {jd_id}: {e}")
            duration = round(_time.time() - cycle_start, 2)
            cycle_done(AGENT_ID, events=events)
            heartbeat(
                AGENT_ID,
                status="idle",
                next_run_at=datetime.fromtimestamp(_time.time() + INTERVAL_S, timezone.utc),
            )
            logger.info(f"[agent:{AGENT_ID}] cycle done · {events} stale flagged · {duration}s")
        except Exception as e:
            cycle_done(AGENT_ID, error=str(e))
            logger.warning(f"[agent:{AGENT_ID}] loop error: {e}")
        await asyncio.sleep(get_interval(AGENT_ID, INTERVAL_S))
