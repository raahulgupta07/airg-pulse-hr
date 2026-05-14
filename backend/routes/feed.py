"""Unified activity feed — aggregates notifications, JD background agent state,
AI scan lifecycle, and AI matches into a single stream + REST snapshot.

Event contract:
  {
    "type": "notification"|"jd_agent"|"ai_scan"|"ai_match",
    "id": "string",          # unique key e.g. "notif:42"
    "kind": "new_match"|"scan_done"|"jd_agent_status"|"notification"|...,
    "title": "string",
    "subtitle": "string|null",
    "ts": "ISO 8601",
    "read": false,
    "action_url": "string|null"
  }
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _iso(dt) -> str:
    if dt is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(dt, str):
        return dt
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def _ts_key(ev: dict) -> str:
    return ev.get("ts") or ""


def _fetch_notifications(user_id: int, limit: int) -> list[dict]:
    out: list[dict] = []
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT id, type, title, message, link, is_read, created_at
                   FROM notifications
                   WHERE user_id = %s
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (user_id, limit),
            )
            for r in cur.fetchall():
                nid, ntype, title, message, link, is_read, created_at = r
                out.append({
                    "type": "notification",
                    "id": f"notif:{nid}",
                    "raw_id": int(nid),
                    "kind": ntype or "notification",
                    "title": title or "Notification",
                    "subtitle": message or None,
                    "ts": _iso(created_at),
                    "read": bool(is_read),
                    "action_url": link or None,
                })
    except Exception as e:
        logger.warning(f"feed: notifications fetch failed: {e}")
    return out


def _fetch_ai_scans(limit: int) -> list[dict]:
    out: list[dict] = []
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT s.id, s.position_id, s.status, s.started_at, s.finished_at,
                          s.n_scored, s.n_matched, s.error, s.created_at,
                          p.slug, p.title
                   FROM position_ai_scans s
                   LEFT JOIN positions p ON p.id = s.position_id
                   WHERE COALESCE(s.finished_at, s.started_at, s.created_at)
                         > now() - interval '24 hours'
                   ORDER BY COALESCE(s.finished_at, s.started_at, s.created_at) DESC
                   LIMIT %s""",
                (limit,),
            )
            for r in cur.fetchall():
                sid, pid, status, started_at, finished_at, n_scored, n_matched, err, created_at, slug, title = r
                ts_val = finished_at or started_at or created_at
                ns = n_scored or 0
                nm = n_matched or 0
                pos_name = title or f"position #{pid}"
                if status == "done":
                    kind = "scan_done"
                    title_line = f"AI scored {ns} CV{'s' if ns != 1 else ''} for {pos_name}"
                    if nm == 0 and ns > 0:
                        sub = f"None passed match threshold. Open position to see top-scored CVs and lower the bar if needed."
                    elif nm == 0:
                        sub = f"CV repo is empty. Upload CVs to start matching."
                    elif nm == 1:
                        sub = f"{nm} CV qualified — view in Candidates tab"
                    else:
                        sub = f"{nm} CVs qualified ({nm}/{ns} scored above threshold) — view in Candidates tab"
                elif status == "running":
                    kind = "scan_started"
                    title_line = f"AI scanning {pos_name}"
                    sub = f"Processed {ns} CVs so far. Live updates in Candidates → AI Match tab."
                elif status == "error":
                    kind = "scan_error"
                    title_line = f"AI scan failed for {pos_name}"
                    sub = f"Reason: {(err or 'unknown error')[:160]}. Click Rescan to retry."
                else:
                    kind = "scan_started"
                    title_line = f"AI scan queued for {pos_name}"
                    sub = "Waiting for worker. Will start within a few seconds."
                out.append({
                    "type": "ai_scan",
                    "id": f"scan:{sid}",
                    "raw_id": int(sid),
                    "kind": kind,
                    "title": title_line,
                    "subtitle": sub,
                    "ts": _iso(ts_val),
                    "read": True,
                    "action_url": f"/positions/{slug}" if slug else None,
                })
    except Exception as e:
        logger.warning(f"feed: ai_scans fetch failed: {e}")
    return out


def _fetch_ai_matches(limit: int) -> list[dict]:
    out: list[dict] = []
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT pc.id, pc.position_id, pc.candidate_id,
                          pc.match_score_composite, pc.created_at, pc.match_source,
                          c.name AS cand_name, p.title AS pos_title, p.slug AS pos_slug
                   FROM position_candidates pc
                   LEFT JOIN candidates c ON c.id = pc.candidate_id
                   LEFT JOIN positions p ON p.id = pc.position_id
                   WHERE pc.created_at > now() - interval '24 hours'
                     AND pc.match_source LIKE 'auto_scan%%'
                   ORDER BY pc.created_at DESC
                   LIMIT %s""",
                (limit,),
            )
            for r in cur.fetchall():
                pcid, pid, cid, score, created_at, src, cname, ptitle, pslug = r
                score_str = f"{float(score):.0f}" if score is not None else "?"
                pos_name = ptitle or f"position #{pid}"
                cand_name = cname or f"candidate #{cid}"
                src_label = "auto-matched on position create" if src == "auto_scan_on_create" else \
                            "auto-matched after JD update" if src == "auto_scan_on_jd_update" else \
                            "auto-matched on rescan" if src == "auto_scan_rescan" else \
                            "auto-matched"
                out.append({
                    "type": "ai_match",
                    "id": f"match:pc:{pcid}",
                    "raw_id": int(pcid),
                    "kind": "new_match",
                    "title": f"New match: {cand_name} for {pos_name}",
                    "subtitle": f"Match score {score_str}% · {src_label}. Click to review profile.",
                    "ts": _iso(created_at),
                    "read": True,
                    "action_url": f"/positions/{pslug}" if pslug else None,
                })
    except Exception as e:
        logger.warning(f"feed: ai_matches fetch failed: {e}")
    return out


def _fetch_jd_agent_event() -> list[dict]:
    """Single synthetic event capturing current JD background agent state."""
    try:
        from backend.agents import jd_background as jb
        st = dict(jb.STATE) if isinstance(jb.STATE, dict) else {}
        ts = st.get("last_run_at") or st.get("next_run_at") or datetime.now(timezone.utc).isoformat()
        status = st.get("status") or "idle"
        interval = st.get("interval_s") or 60
        last = st.get("last_cycle_summary") or {}

        if status == "scanning":
            title_line = "JD agent is scanning"
            sub_line = f"Auto-filling missing fields (skills, dept, seniority) on JDs across the repo."
        elif status == "sleeping":
            title_line = "JD agent · idle"
            done = (last.get("kf4d_done") or 0) + (last.get("skills_done") or 0)
            if done > 0:
                sub_line = f"Last cycle filled {done} field set(s). Next scan in ~{interval}s."
            else:
                sub_line = f"All JDs already complete. Next scan in ~{interval}s."
        elif status == "idle":
            title_line = "JD agent · ready"
            sub_line = f"Watching for new JDs. Auto-extracts skills, dept, seniority, certs."
        else:
            title_line = f"JD agent · {status}"
            sub_line = st.get("current_action") or None
        return [{
            "type": "jd_agent",
            "id": "jd_agent:state",
            "raw_id": 0,
            "kind": "jd_agent_status",
            "title": title_line,
            "subtitle": sub_line,
            "ts": _iso(ts),
            "read": True,
            "action_url": None,
        }]
    except Exception as e:
        logger.warning(f"feed: jd_agent state read failed: {e}")
        return []


def _build_snapshot(user_id: int, limit: int) -> dict:
    events: list[dict] = []
    events.extend(_fetch_notifications(user_id, limit))
    events.extend(_fetch_ai_scans(limit))
    events.extend(_fetch_ai_matches(limit))
    events.extend(_fetch_jd_agent_event())

    events.sort(key=_ts_key, reverse=True)
    events = events[:limit]

    by_type = {"notification": 0, "jd_agent": 0, "ai_scan": 0, "ai_match": 0}
    unread = 0
    for ev in events:
        by_type[ev["type"]] = by_type.get(ev["type"], 0) + 1
        if ev["type"] == "notification" and not ev.get("read"):
            unread += 1

    # Strip internal raw_id from output
    cleaned = [{k: v for k, v in ev.items() if k != "raw_id"} for ev in events]
    return {"events": cleaned, "unread_count": unread, "by_type": by_type}


# ---------------------------------------------------------------------------
# REST snapshot
# ---------------------------------------------------------------------------
@router.get("/feed")
async def get_feed(request: Request, limit: int = Query(50, ge=1, le=200)):
    user = get_current_user(request)
    return _build_snapshot(user["user_id"], limit)


# ---------------------------------------------------------------------------
# Mark-read
# ---------------------------------------------------------------------------
class MarkReadBody(BaseModel):
    ids: list[str]


@router.post("/feed/mark-read")
async def mark_read(body: MarkReadBody, request: Request):
    user = get_current_user(request)
    user_id = user["user_id"]
    notif_ids: list[int] = []
    for raw in body.ids or []:
        s = str(raw)
        if s.startswith("notif:"):
            s = s.split(":", 1)[1]
        try:
            notif_ids.append(int(s))
        except ValueError:
            continue
    if not notif_ids:
        return {"updated": 0}
    with get_cursor() as cur:
        cur.execute(
            "UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND id = ANY(%s)",
            (user_id, notif_ids),
        )
        updated = cur.rowcount or 0
    return {"updated": updated}


@router.post("/feed/mark-all-read")
async def mark_all_read(request: Request):
    user = get_current_user(request)
    with get_cursor() as cur:
        cur.execute(
            "UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE",
            (user["user_id"],),
        )
        updated = cur.rowcount or 0
    return {"updated": updated}


# ---------------------------------------------------------------------------
# SSE stream — poll DB every 2s, emit deltas
# ---------------------------------------------------------------------------
def _max_ids() -> dict:
    out = {"notif": 0, "scan": 0, "match": 0}
    try:
        with get_cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(id),0) FROM notifications")
            out["notif"] = int(cur.fetchone()[0] or 0)
            cur.execute("SELECT COALESCE(MAX(id),0) FROM position_ai_scans")
            out["scan"] = int(cur.fetchone()[0] or 0)
            cur.execute(
                "SELECT COALESCE(MAX(id),0) FROM position_candidates WHERE match_source LIKE 'auto_scan%%'"
            )
            out["match"] = int(cur.fetchone()[0] or 0)
    except Exception as e:
        logger.warning(f"feed: max_ids failed: {e}")
    return out


def _fetch_new_notifications_after(user_id: int, since_id: int) -> list[dict]:
    out: list[dict] = []
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT id, type, title, message, link, is_read, created_at
                   FROM notifications
                   WHERE user_id = %s AND id > %s
                   ORDER BY id ASC LIMIT 100""",
                (user_id, since_id),
            )
            for r in cur.fetchall():
                nid, ntype, title, message, link, is_read, created_at = r
                out.append({
                    "type": "notification",
                    "id": f"notif:{nid}",
                    "kind": ntype or "notification",
                    "title": title or "Notification",
                    "subtitle": message or None,
                    "ts": _iso(created_at),
                    "read": bool(is_read),
                    "action_url": link or None,
                    "_raw_id": int(nid),
                })
    except Exception as e:
        logger.warning(f"feed: notif delta failed: {e}")
    return out


def _fetch_new_scans_after(since_id: int) -> list[dict]:
    out: list[dict] = []
    try:
        with get_cursor() as cur:
            # Include status changes via finished_at — but to keep polling simple,
            # emit when row id > since (new scan) OR when finished_at recently set.
            cur.execute(
                """SELECT s.id, s.position_id, s.status, s.started_at, s.finished_at,
                          s.n_scored, s.n_matched, s.error, s.created_at,
                          p.slug, p.title
                   FROM position_ai_scans s
                   LEFT JOIN positions p ON p.id = s.position_id
                   WHERE s.id > %s
                      OR s.finished_at > now() - interval '5 seconds'
                   ORDER BY s.id ASC LIMIT 100""",
                (since_id,),
            )
            for r in cur.fetchall():
                sid, pid, status, started_at, finished_at, n_scored, n_matched, err, created_at, slug, title = r
                ts_val = finished_at or started_at or created_at
                kind = {"done": "scan_done", "running": "scan_started",
                        "error": "scan_error"}.get(status, "scan_started")
                sub = (f"{n_scored or 0} scored · {n_matched or 0} matched"
                       if status == "done"
                       else (err or "")[:200] if status == "error"
                       else f"{n_scored or 0} scored so far")
                out.append({
                    "type": "ai_scan",
                    "id": f"scan:{sid}:{status}",
                    "kind": kind,
                    "title": f"AI scan · {title or ('position #' + str(pid))}",
                    "subtitle": sub,
                    "ts": _iso(ts_val),
                    "read": True,
                    "action_url": f"/positions/{slug}" if slug else None,
                    "_raw_id": int(sid),
                })
    except Exception as e:
        logger.warning(f"feed: scan delta failed: {e}")
    return out


def _fetch_new_matches_after(since_id: int) -> list[dict]:
    out: list[dict] = []
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT pc.id, pc.position_id, pc.candidate_id,
                          pc.match_score_composite, pc.created_at, pc.match_source,
                          c.name, p.title, p.slug
                   FROM position_candidates pc
                   LEFT JOIN candidates c ON c.id = pc.candidate_id
                   LEFT JOIN positions p ON p.id = pc.position_id
                   WHERE pc.id > %s AND pc.match_source LIKE 'auto_scan%%'
                   ORDER BY pc.id ASC LIMIT 100""",
                (since_id,),
            )
            for r in cur.fetchall():
                pcid, pid, cid, score, created_at, src, cname, ptitle, pslug = r
                score_str = f"{float(score):.0f}" if score is not None else "?"
                out.append({
                    "type": "ai_match",
                    "id": f"match:pc:{pcid}",
                    "kind": "new_match",
                    "title": f"{cname or ('candidate #' + str(cid))} → {ptitle or ('position #' + str(pid))}",
                    "subtitle": f"score {score_str} · {src or 'auto_scan'}",
                    "ts": _iso(created_at),
                    "read": True,
                    "action_url": f"/positions/{pslug}" if pslug else None,
                    "_raw_id": int(pcid),
                })
    except Exception as e:
        logger.warning(f"feed: match delta failed: {e}")
    return out


@router.get("/feed/events")
async def feed_events(request: Request):
    """SSE stream — polls DB every 2s and emits new feed events.
    Sends `: ping` every 25s; closes on client disconnect or 30min idle.
    """
    user = get_current_user(request)
    user_id = user["user_id"]

    async def gen():
        # Initial snapshot: send most recent 20 events first
        snap = await asyncio.to_thread(_build_snapshot, user_id, 20)
        for ev in reversed(snap["events"]):
            yield f"event: feed\ndata: {json.dumps(ev, default=str)}\n\n"

        seen = await asyncio.to_thread(_max_ids)
        last_jd_status: str | None = None
        last_emit = time.time()
        last_ping = time.time()
        started = time.time()
        max_idle_s = 30 * 60

        while True:
            if await request.is_disconnected():
                break
            if time.time() - started > max_idle_s:
                break

            try:
                # Notifications
                new_notifs = await asyncio.to_thread(
                    _fetch_new_notifications_after, user_id, seen["notif"]
                )
                for ev in new_notifs:
                    rid = ev.pop("_raw_id", 0)
                    if rid > seen["notif"]:
                        seen["notif"] = rid
                    yield f"event: feed\ndata: {json.dumps(ev, default=str)}\n\n"
                    last_emit = time.time()

                # AI scans
                new_scans = await asyncio.to_thread(_fetch_new_scans_after, seen["scan"])
                for ev in new_scans:
                    rid = ev.pop("_raw_id", 0)
                    if rid > seen["scan"]:
                        seen["scan"] = rid
                    yield f"event: feed\ndata: {json.dumps(ev, default=str)}\n\n"
                    last_emit = time.time()

                # AI matches
                new_matches = await asyncio.to_thread(_fetch_new_matches_after, seen["match"])
                for ev in new_matches:
                    rid = ev.pop("_raw_id", 0)
                    if rid > seen["match"]:
                        seen["match"] = rid
                    yield f"event: feed\ndata: {json.dumps(ev, default=str)}\n\n"
                    last_emit = time.time()

                # JD agent state — emit on transition
                jd_evs = _fetch_jd_agent_event()
                if jd_evs:
                    cur_status = jd_evs[0]["title"]
                    if cur_status != last_jd_status:
                        last_jd_status = cur_status
                        yield f"event: feed\ndata: {json.dumps(jd_evs[0], default=str)}\n\n"
                        last_emit = time.time()
            except Exception as e:
                logger.warning(f"feed: poll cycle error: {e}")

            # Ping every 25s
            if time.time() - last_ping >= 25:
                yield ": ping\n\n"
                last_ping = time.time()

            await asyncio.sleep(2)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
