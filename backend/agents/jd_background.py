"""JD background worker — periodically fills MISSING fields on uploaded JDs.
Does NOT rewrite or enhance existing content. Only adds: required_skills, KF4D competencies.
Run every JD_BG_INTERVAL_S seconds (default 300 = 5 minutes).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Query
from backend.core.auth import get_current_user
from backend.core.database import get_cursor

router = APIRouter()


@router.get("/status")
async def jd_bg_status(request: Request, since_id: int = Query(0), event_limit: int = Query(50, le=200)):
    """Live status + recent event feed for the JD background agent."""
    get_current_user(request)
    new_events = [e for e in EVENTS if e["id"] > since_id][-event_limit:]
    max_id = EVENTS[-1]["id"] if EVENTS else since_id
    listener: dict = {}
    try:
        from backend.agents.jd_enrich_listener import get_listener_stats
        listener = get_listener_stats()
    except Exception:
        listener = {"listener_connected": False, "queue_depth": 0, "processed_count": 0}
    return {
        "state": STATE,
        "events": new_events,
        "max_id": max_id,
        "interval_s": JD_BG_INTERVAL_S,
        "batch_size": JD_BG_BATCH,
        "listener": listener,
    }

logger = logging.getLogger(__name__)

JD_BG_INTERVAL_S = int(os.getenv("JD_BG_INTERVAL_S", "60"))
JD_BG_BATCH = int(os.getenv("JD_BG_BATCH", "10"))

# Public state for the /jd-background/status endpoint
STATE: dict = {
    "status": "idle",            # idle | scanning | sleeping
    "current_action": None,      # e.g. "extracting KF4D for jd 14"
    "last_run_at": None,
    "next_run_at": None,
    "last_cycle_summary": None,  # {"kf4d_done": N, "skills_done": N, "duration_s": X}
    "total_runs": 0,
    "total_jds_processed": 0,
}
EVENTS: list[dict] = []   # ring buffer of recent activity
_event_seq = 0


def _emit(kind: str, msg: str, level: str = "info"):
    global _event_seq
    _event_seq += 1
    EVENTS.append({
        "id": _event_seq,
        "kind": kind,
        "msg": msg,
        "level": level,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    if len(EVENTS) > 200:
        del EVENTS[:100]


def _find_jds_missing_competencies(limit: int) -> list[int]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT j.id FROM jd_repository j
               LEFT JOIN jd_competencies jc ON jc.jd_id = j.id
               WHERE COALESCE(j.status, 'active') = 'active'
                 AND COALESCE(j.jd_text, '') <> ''
               GROUP BY j.id
               HAVING COUNT(jc.id) = 0
               ORDER BY j.created_at DESC
               LIMIT %s""",
            (limit,),
        )
        return [r[0] for r in cur.fetchall()]


def _find_jds_missing_skills(limit: int) -> list[int]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT id FROM jd_repository
               WHERE COALESCE(status, 'active') = 'active'
                 AND COALESCE(jd_text, '') <> ''
                 AND (required_skills IS NULL OR required_skills = '{}' OR cardinality(required_skills) = 0)
               ORDER BY created_at DESC
               LIMIT %s""",
            (limit,),
        )
        return [r[0] for r in cur.fetchall()]


async def jd_background_loop():
    """Background loop — runs every JD_BG_INTERVAL_S."""
    logger.info(f"[jd-bg] starting (interval={JD_BG_INTERVAL_S}s, batch={JD_BG_BATCH})")
    STATE["status"] = "starting"
    _emit("startup", f"JD Agent online · scan every {JD_BG_INTERVAL_S}s · batch {JD_BG_BATCH}")
    await asyncio.sleep(20)
    while True:
        # Admin-controlled enable gate (cached ~10s, default TRUE on error)
        try:
            from backend.agents.registry import is_enabled as _is_enabled
            if not _is_enabled("jd-field-poll"):
                STATE["status"] = "disabled"
                STATE["current_action"] = "disabled via admin"
                await asyncio.sleep(JD_BG_INTERVAL_S)
                continue
        except Exception:
            pass
        cycle_start = _time.time()
        kf4d_done = 0
        skills_done = 0
        try:
            from backend.routes.jd_repo import _internal_extract_jd_competencies, _extract_requirements
            STATE["status"] = "scanning"
            STATE["current_action"] = "scanning for incomplete JDs"
            _emit("scan", "🔍 Scanning JD repository for missing fields")

            comp_targets = await asyncio.to_thread(_find_jds_missing_competencies, JD_BG_BATCH)
            skill_targets = await asyncio.to_thread(_find_jds_missing_skills, JD_BG_BATCH)
            total_to_do = len(comp_targets) + len(skill_targets)
            if total_to_do == 0:
                _emit("clean", "✓ All JDs complete — nothing to do")
            else:
                _emit("found", f"📋 {len(comp_targets)} need KF4D · {len(skill_targets)} need skills")

            for jd_id in comp_targets:
                STATE["current_action"] = f"extracting KF4D for jd {jd_id}"
                _emit("kf4d", f"🧬 jd_{jd_id:03d} → tagging KF4D competencies…")
                try:
                    r = await asyncio.to_thread(_internal_extract_jd_competencies, jd_id)
                    n = r.get("created", 0) + r.get("updated", 0)
                    kf4d_done += 1
                    STATE["total_jds_processed"] += 1
                    _emit("kf4d_done", f"✓ jd_{jd_id:03d} · {n} competencies tagged", "success")
                except Exception as e:
                    _emit("kf4d_err", f"✗ jd_{jd_id:03d} · {str(e)[:80]}", "error")
                await asyncio.sleep(0.3)

            for jd_id in skill_targets:
                STATE["current_action"] = f"extracting skills for jd {jd_id}"
                _emit("skills", f"🔧 jd_{jd_id:03d} → pulling required skills…")
                try:
                    with get_cursor() as cur:
                        cur.execute("SELECT jd_text FROM jd_repository WHERE id = %s", (jd_id,))
                        row = cur.fetchone()
                    if not row or not row[0]:
                        continue
                    text = row[0]
                    req = await asyncio.to_thread(_extract_requirements, text)
                    skills = list((req or {}).get("required_skills") or [])
                    dept = (req or {}).get("department")
                    seniority = (req or {}).get("seniority_level")
                    cert = list((req or {}).get("certifications") or [])
                    years = (req or {}).get("years_experience")
                    fields_set = []
                    with get_cursor() as cur:
                        if skills:
                            cur.execute("UPDATE jd_repository SET required_skills=%s, updated_at=NOW() WHERE id=%s AND (required_skills IS NULL OR cardinality(required_skills)=0)", (skills, jd_id))
                            if cur.rowcount: fields_set.append(f"{len(skills)} skills")
                        if dept:
                            cur.execute("UPDATE jd_repository SET department=%s, updated_at=NOW() WHERE id=%s AND COALESCE(department,'')=''", (dept, jd_id))
                            if cur.rowcount: fields_set.append(f"dept={dept}")
                        if seniority:
                            cur.execute("UPDATE jd_repository SET seniority_level=%s, updated_at=NOW() WHERE id=%s AND COALESCE(seniority_level,'')=''", (seniority, jd_id))
                            if cur.rowcount: fields_set.append(f"seniority={seniority}")
                        if cert:
                            cur.execute("UPDATE jd_repository SET certifications=%s, updated_at=NOW() WHERE id=%s AND (certifications IS NULL OR cardinality(certifications)=0)", (cert, jd_id))
                            if cur.rowcount: fields_set.append(f"{len(cert)} certs")
                        if years is not None:
                            cur.execute("UPDATE jd_repository SET min_experience_years=%s, updated_at=NOW() WHERE id=%s AND (min_experience_years IS NULL OR min_experience_years=0)", (years, jd_id))
                            if cur.rowcount: fields_set.append(f"min_exp={years}y")
                    skills_done += 1
                    STATE["total_jds_processed"] += 1
                    summary = " · ".join(fields_set) if fields_set else "no fields needed update"
                    _emit("skills_done", f"✓ jd_{jd_id:03d} · {summary}", "success")
                except Exception as e:
                    _emit("skills_err", f"✗ jd_{jd_id:03d} · {str(e)[:80]}", "error")
                await asyncio.sleep(0.3)

            duration = round(_time.time() - cycle_start, 2)
            STATE["last_run_at"] = datetime.now(timezone.utc).isoformat()
            STATE["next_run_at"] = datetime.fromtimestamp(_time.time() + JD_BG_INTERVAL_S, timezone.utc).isoformat()
            STATE["last_cycle_summary"] = {
                "kf4d_done": kf4d_done, "skills_done": skills_done, "duration_s": duration,
            }
            STATE["total_runs"] += 1
            _emit("cycle_end", f"💤 Cycle done · {kf4d_done + skills_done} JDs enriched · {duration}s · next in {JD_BG_INTERVAL_S}s")
            STATE["status"] = "sleeping"
            STATE["current_action"] = f"sleeping {JD_BG_INTERVAL_S}s"
        except Exception as e:
            STATE["status"] = "error"
            _emit("loop_err", f"Loop error: {e}", "error")
        await asyncio.sleep(JD_BG_INTERVAL_S)


# ── Test-run hook (admin out-of-schedule trigger) ──────────────────────────
async def run_once() -> dict:
    """Single-cycle trigger for admin test-run.
    Processes one batch of incomplete JDs (KF4D + skills) and returns counts.
    """
    from backend.routes.jd_repo import _internal_extract_jd_competencies, _extract_requirements
    kf4d_done = 0
    skills_done = 0
    comp_targets = await asyncio.to_thread(_find_jds_missing_competencies, JD_BG_BATCH)
    skill_targets = await asyncio.to_thread(_find_jds_missing_skills, JD_BG_BATCH)
    for jd_id in comp_targets:
        try:
            await asyncio.to_thread(_internal_extract_jd_competencies, jd_id)
            kf4d_done += 1
        except Exception:
            pass
    for jd_id in skill_targets:
        try:
            with get_cursor() as cur:
                cur.execute("SELECT jd_text FROM jd_repository WHERE id=%s", (jd_id,))
                row = cur.fetchone()
            if not row or not row[0]:
                continue
            await asyncio.to_thread(_extract_requirements, row[0])
            skills_done += 1
        except Exception:
            pass
    _emit("test_run", f"⚡ admin test-run · {kf4d_done} KF4D · {skills_done} skills", "success")
    return {
        "kf4d_done": kf4d_done,
        "skills_done": skills_done,
        "comp_targets": len(comp_targets),
        "skill_targets": len(skill_targets),
    }


try:
    from backend.agents.registry import register_run_once as _reg_run_once
    _reg_run_once("jd-field-poll", run_once)
except Exception:
    pass
