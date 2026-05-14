"""Real-time JD enrichment listener — Postgres LISTEN/NOTIFY.

Replaces 5-min polling for the primary path. The legacy `jd_background_loop`
in `jd_background.py` remains as a safety-net fallback (catches missed
notifications, e.g. if listener was down when NOTIFY fired).

Architecture:
    Postgres trigger (mig 043) → NOTIFY 'jd_enrich_needed' <jd_id>
        → asyncpg-style listener loop on dedicated psycopg connection
        → asyncio.Queue → bounded consumer (Semaphore(2)) → _extract_requirements
        → UPDATE jd_repository (only empty fields)
        → INSERT notifications row (PULSE FEED)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
from datetime import datetime, timezone

import psycopg

from backend.core.database import (
    DATABASE_URL,
    get_cursor,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public state — exposed via /api/jd-background/status
# ---------------------------------------------------------------------------
LISTENER_STATE: dict = {
    "listener_connected": False,
    "queue_depth": 0,
    "processed_count": 0,
    "error_count": 0,
    "last_enrich_at": None,
    "last_jd_id": None,
    "last_fields": None,
    "started_at": None,
}

CONCURRENCY = int(os.getenv("JD_ENRICH_CONCURRENCY", "2"))
RECONNECT_BACKOFF_S = int(os.getenv("JD_ENRICH_RECONNECT_S", "5"))
NOTIFY_TIMEOUT_S = int(os.getenv("JD_ENRICH_NOTIFY_TIMEOUT_S", "30"))

_queue: asyncio.Queue[int] | None = None
_seen_in_flight: set[int] = set()  # dedupe ids currently being processed / queued
_sem: asyncio.Semaphore | None = None


# ---------------------------------------------------------------------------
# Worker — applies enrichment to ONE jd_id (only fills empty fields)
# ---------------------------------------------------------------------------
async def _enrich_one(jd_id: int) -> None:
    """Extract + fill missing fields for a single JD. Mirrors poll-loop logic."""
    global LISTENER_STATE
    try:
        # Fetch current row state
        def _read_row():
            with get_cursor() as cur:
                cur.execute(
                    """SELECT jd_text, department, seniority_level,
                              min_experience_years, required_skills, nice_to_have_skills,
                              required_certifications, created_by, title
                       FROM jd_repository WHERE id = %s""",
                    (jd_id,),
                )
                return cur.fetchone()

        row = await asyncio.to_thread(_read_row)
        if not row:
            logger.info(f"[jd-listener] jd {jd_id} not found (deleted?), skip")
            return
        (jd_text, dept, sen, yrs, req_sk, nth_sk, certs, created_by, title) = row
        if not jd_text or len(jd_text) <= 50:
            return

        # Need-to-do check (re-verify; another worker may have just filled)
        needs = (
            (not dept) or (not sen) or (yrs is None or yrs == 0)
            or (not req_sk) or (not nth_sk)
        )
        if not needs:
            logger.info(f"[jd-listener] jd {jd_id} already complete, skip")
            return

        # LLM extract
        from backend.routes.jd_repo import _extract_requirements
        req = await _extract_requirements(jd_text)
        req = req or {}

        skills = list(req.get("required_skills") or [])
        nth = list(req.get("nice_to_have") or [])
        dep_v = req.get("department")
        sen_v = req.get("seniority_level")
        cert = list(req.get("certifications") or [])
        years = req.get("min_experience_years")
        if years is None:
            years = req.get("years_experience")

        fields_set: list[str] = []

        def _apply():
            with get_cursor() as cur:
                if skills:
                    cur.execute(
                        "UPDATE jd_repository SET required_skills=%s, updated_at=NOW() "
                        "WHERE id=%s AND (required_skills IS NULL OR cardinality(required_skills)=0)",
                        (skills, jd_id),
                    )
                    if cur.rowcount:
                        fields_set.append(f"required_skills({len(skills)})")
                if nth:
                    cur.execute(
                        "UPDATE jd_repository SET nice_to_have_skills=%s, updated_at=NOW() "
                        "WHERE id=%s AND (nice_to_have_skills IS NULL OR cardinality(nice_to_have_skills)=0)",
                        (nth, jd_id),
                    )
                    if cur.rowcount:
                        fields_set.append(f"nice_to_have({len(nth)})")
                if dep_v:
                    cur.execute(
                        "UPDATE jd_repository SET department=%s, updated_at=NOW() "
                        "WHERE id=%s AND COALESCE(department,'')=''",
                        (dep_v, jd_id),
                    )
                    if cur.rowcount:
                        fields_set.append(f"department={dep_v}")
                if sen_v:
                    cur.execute(
                        "UPDATE jd_repository SET seniority_level=%s, updated_at=NOW() "
                        "WHERE id=%s AND COALESCE(seniority_level,'')=''",
                        (sen_v, jd_id),
                    )
                    if cur.rowcount:
                        fields_set.append(f"seniority={sen_v}")
                if cert:
                    cur.execute(
                        "UPDATE jd_repository SET required_certifications=%s, updated_at=NOW() "
                        "WHERE id=%s AND (required_certifications IS NULL OR cardinality(required_certifications)=0)",
                        (cert, jd_id),
                    )
                    if cur.rowcount:
                        fields_set.append(f"certs({len(cert)})")
                if years is not None:
                    try:
                        years_i = int(years)
                    except (TypeError, ValueError):
                        years_i = None
                    if years_i is not None:
                        cur.execute(
                            "UPDATE jd_repository SET min_experience_years=%s, updated_at=NOW() "
                            "WHERE id=%s AND (min_experience_years IS NULL OR min_experience_years=0)",
                            (years_i, jd_id),
                        )
                        if cur.rowcount:
                            fields_set.append(f"min_exp={years_i}y")

        await asyncio.to_thread(_apply)

        LISTENER_STATE["processed_count"] += 1
        LISTENER_STATE["last_enrich_at"] = datetime.now(timezone.utc).isoformat()
        LISTENER_STATE["last_jd_id"] = jd_id
        LISTENER_STATE["last_fields"] = fields_set

        # Mirror to JD background EVENTS feed for terminal/badge
        try:
            from backend.agents.jd_background import _emit
            if fields_set:
                _emit(
                    "rt_enrich",
                    f"⚡ jd_{jd_id:03d} · realtime · {' · '.join(fields_set)}",
                    "success",
                )
            else:
                _emit("rt_noop", f"· jd_{jd_id:03d} · realtime · no fields needed", "info")
        except Exception:
            pass

        # PULSE FEED — emit a notification row so the unified feed picks it up
        if fields_set:
            try:
                # Plain-English field names + counts
                FIELD_LABELS = {
                    "required_skills": "skills",
                    "nice_to_have_skills": "nice-to-have skills",
                    "department": "department",
                    "seniority_level": "seniority",
                    "min_experience_years": "min experience",
                    "education_level": "education level",
                    "industry_keywords": "industry tags",
                    "required_certifications": "certifications",
                }
                # fields_set entries can be "field" or "field(N)" — keep N for context
                friendly_parts = []
                for raw in fields_set:
                    base = raw.split("(")[0]
                    suffix = raw[len(base):]  # "(15)" or ""
                    label = FIELD_LABELS.get(base, base.replace("_", " "))
                    friendly_parts.append(f"{label}{suffix}")
                pretty = ", ".join(friendly_parts)
                jd_name = title or f"JD #{jd_id}"
                msg = f"AI auto-filled {pretty} for {jd_name}. No action needed — fields are now available for matching."
                ttl = f"AI enriched JD: {jd_name}"

                def _notif():
                    with get_cursor() as cur:
                        cur.execute(
                            """INSERT INTO notifications (user_id, type, title, message, link)
                               VALUES (%s, %s, %s, %s, %s)""",
                            (
                                created_by or 1,  # fallback to admin user 1
                                "jd_enriched",
                                ttl,
                                msg,
                                f"/jds/{jd_id}",
                            ),
                        )

                await asyncio.to_thread(_notif)
            except Exception as e:
                logger.warning(f"[jd-listener] feed notify failed for jd {jd_id}: {e}")

        logger.info(
            f"[jd-listener] enriched jd {jd_id} · "
            f"fields={fields_set or 'none'}"
        )
    except Exception as e:
        LISTENER_STATE["error_count"] += 1
        logger.warning(f"[jd-listener] enrich failed for jd {jd_id}: {e}")


# ---------------------------------------------------------------------------
# Consumer — pulls from queue, enforces concurrency cap
# ---------------------------------------------------------------------------
async def _consumer_loop():
    global _queue, _sem, LISTENER_STATE
    assert _queue is not None and _sem is not None
    while True:
        jd_id = await _queue.get()
        LISTENER_STATE["queue_depth"] = _queue.qsize()
        async with _sem:
            try:
                await _enrich_one(jd_id)
            finally:
                _seen_in_flight.discard(jd_id)
                _queue.task_done()


# ---------------------------------------------------------------------------
# Listener — opens dedicated connection, LISTEN, dispatches to queue
# ---------------------------------------------------------------------------
async def _listen_session():
    """Open connection + LISTEN + read notifies forever (single session)."""
    global _queue, LISTENER_STATE
    assert _queue is not None

    # AsyncConnection in autocommit so LISTEN works
    async with await psycopg.AsyncConnection.connect(
        DATABASE_URL, autocommit=True
    ) as aconn:
        async with aconn.cursor() as cur:
            await cur.execute("LISTEN jd_enrich_needed")
        LISTENER_STATE["listener_connected"] = True
        logger.info("[jd-listener] LISTEN jd_enrich_needed connected")

        # psycopg3 AsyncConnection.notifies() async-iterates notifications
        gen = aconn.notifies()
        async for notify in gen:
            try:
                jd_id = int(notify.payload)
            except (ValueError, TypeError):
                continue
            if jd_id in _seen_in_flight:
                continue
            _seen_in_flight.add(jd_id)
            await _queue.put(jd_id)
            LISTENER_STATE["queue_depth"] = _queue.qsize()


async def jd_enrich_listener_loop():
    """Outer reconnect loop. Run forever; survives DB hiccups."""
    global _queue, _sem, LISTENER_STATE
    _queue = asyncio.Queue(maxsize=10000)
    _sem = asyncio.Semaphore(CONCURRENCY)
    LISTENER_STATE["started_at"] = datetime.now(timezone.utc).isoformat()

    # Spawn fixed consumer pool
    for _ in range(CONCURRENCY):
        asyncio.create_task(_consumer_loop())

    logger.info(
        f"[jd-listener] starting · concurrency={CONCURRENCY} · "
        f"backoff={RECONNECT_BACKOFF_S}s"
    )

    while True:
        try:
            await _listen_session()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            LISTENER_STATE["listener_connected"] = False
            logger.warning(
                f"[jd-listener] connection lost: {e!r} — "
                f"reconnect in {RECONNECT_BACKOFF_S}s"
            )
            await asyncio.sleep(RECONNECT_BACKOFF_S)
        finally:
            LISTENER_STATE["listener_connected"] = False


# ---------------------------------------------------------------------------
# Status helper — surfaced via existing /api/jd-background/status endpoint
# ---------------------------------------------------------------------------
def get_listener_stats() -> dict:
    return {
        "listener_connected": LISTENER_STATE["listener_connected"],
        "queue_depth": _queue.qsize() if _queue is not None else 0,
        "processed_count": LISTENER_STATE["processed_count"],
        "error_count": LISTENER_STATE["error_count"],
        "last_enrich_at": LISTENER_STATE["last_enrich_at"],
        "last_jd_id": LISTENER_STATE["last_jd_id"],
        "last_fields": LISTENER_STATE["last_fields"],
        "started_at": LISTENER_STATE["started_at"],
        "concurrency_cap": CONCURRENCY,
    }
