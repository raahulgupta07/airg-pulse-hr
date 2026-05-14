"""Auto-sync agent — handlers for position/CV/weights changes.

Triggered jobs (use existing job_queue):
  auto_scan_position        — A: position created → scan repo
  auto_match_candidate      — B: CV processed → match against open positions
  auto_rescore_position     — C: position weights changed → rescore attached
  auto_rescore_jd_chain     — C-fanout: JD changed → rescore positions using it
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from backend.core.database import get_cursor
from backend.core.job_queue import enqueue, get_pending_job, complete_job, fail_job

logger = logging.getLogger(__name__)


def _flag(key: str, default: bool = True) -> bool:
    try:
        with get_cursor() as cur:
            cur.execute("SELECT value FROM system_flags WHERE key = %s", (key,))
            row = cur.fetchone()
        if not row: return default
        v = row[0]
        if isinstance(v, bool): return v
        return bool(v)
    except Exception:
        return default


def _threshold() -> int:
    try:
        with get_cursor() as cur:
            cur.execute("SELECT value FROM system_flags WHERE key = 'auto_scan_threshold'")
            row = cur.fetchone()
        if row:
            v = row[0]
            return int(v) if not isinstance(v, dict) else int(v.get("value") or 60)
    except Exception:
        pass
    return 60


def enqueue_dedup(kind: str, payload: dict) -> int | None:
    """Insert if no pending/running job of same (kind, payload) in last 60s."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT id FROM job_queue
            WHERE job_type = %s AND payload = %s::jsonb
              AND status IN ('pending','running')
              AND created_at > NOW() - INTERVAL '60 seconds'
            LIMIT 1
        """, (kind, json.dumps(payload)))
        if cur.fetchone():
            return None
    return enqueue(kind, payload)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def handle_auto_scan_position(payload: dict):
    if not _flag("auto_scan_on_position_create", True):
        return
    pos_id = payload.get("position_id")
    if not pos_id: return
    from backend.routes.matching import score_candidate_against_position
    threshold = _threshold()
    with get_cursor() as cur:
        cur.execute("SELECT * FROM positions WHERE id = %s", (pos_id,))
        row = cur.fetchone()
        if not row: return
        cols = [d[0] for d in cur.description]
        position = dict(zip(cols, row))
        cur.execute("""
            SELECT * FROM candidates
             WHERE status = 'active' AND is_processed = TRUE
        """)
        cand_cols = [d[0] for d in cur.description]
        candidates = [dict(zip(cand_cols, r)) for r in cur.fetchall()]

    matched = 0
    for c in candidates:
        try:
            scores = score_candidate_against_position(c, position)
        except Exception as e:
            logger.warning(f"score failed for cand {c.get('id')}: {e}")
            continue
        if (scores.get("composite") or 0) < threshold:
            continue
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO position_candidates
                  (position_id, candidate_id, stage, ai_recommended, auto_added,
                   match_score_composite, match_score_skills, match_score_experience,
                   match_score_education, match_score_certifications, match_score_industry,
                   skills_matched, skills_missing, added_by)
                VALUES (%s, %s, 'uploaded', TRUE, TRUE, %s, %s, %s, %s, %s, %s, %s, %s, 'auto_scan')
                ON CONFLICT (position_id, candidate_id) DO UPDATE SET
                  match_score_composite = EXCLUDED.match_score_composite,
                  match_score_skills    = EXCLUDED.match_score_skills,
                  match_score_experience= EXCLUDED.match_score_experience,
                  ai_recommended        = TRUE,
                  updated_at            = NOW()
            """, (
                pos_id, c["id"], scores["composite"], scores["skills"], scores["experience"],
                scores["education"], scores["certifications"], scores["industry"],
                scores.get("skills_matched", []), scores.get("skills_missing", []),
            ))
        matched += 1

    # Notify hiring manager
    if matched and position.get("hiring_manager_id"):
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO notifications (user_id, type, title, message, link)
                VALUES (%s, 'auto_match', 'AI auto-scan complete', %s, %s)
            """, (
                position["hiring_manager_id"],
                f"{matched} candidate(s) auto-recommended for {position.get('title')}",
                f"/positions/{position.get('slug')}",
            ))
    logger.info(f"auto_scan_position {pos_id}: {matched} matched")


async def handle_auto_match_candidate(payload: dict):
    if not _flag("auto_match_on_cv_upload", True):
        return
    cand_id = payload.get("candidate_id")
    if not cand_id: return
    from backend.routes.matching import score_candidate_against_position
    threshold = _threshold()
    with get_cursor() as cur:
        cur.execute("SELECT * FROM candidates WHERE id = %s", (cand_id,))
        row = cur.fetchone()
        if not row: return
        cols = [d[0] for d in cur.description]
        candidate = dict(zip(cols, row))
        cur.execute("SELECT * FROM positions WHERE status = 'active'")
        pcols = [d[0] for d in cur.description]
        positions = [dict(zip(pcols, r)) for r in cur.fetchall()]

    matches = 0
    for p in positions:
        try:
            scores = score_candidate_against_position(candidate, p)
        except Exception:
            continue
        if (scores.get("composite") or 0) < threshold:
            continue
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO position_candidates
                  (position_id, candidate_id, stage, ai_recommended, auto_added,
                   match_score_composite, match_score_skills, match_score_experience,
                   match_score_education, match_score_certifications, match_score_industry,
                   skills_matched, skills_missing, added_by)
                VALUES (%s, %s, 'uploaded', TRUE, TRUE, %s, %s, %s, %s, %s, %s, %s, %s, 'auto_match')
                ON CONFLICT (position_id, candidate_id) DO UPDATE SET
                  match_score_composite = EXCLUDED.match_score_composite,
                  ai_recommended        = TRUE,
                  updated_at            = NOW()
            """, (
                p["id"], cand_id, scores["composite"], scores["skills"], scores["experience"],
                scores["education"], scores["certifications"], scores["industry"],
                scores.get("skills_matched", []), scores.get("skills_missing", []),
            ))
            if p.get("hiring_manager_id"):
                cur.execute("""
                    INSERT INTO notifications (user_id, type, title, message, link)
                    VALUES (%s, 'auto_match', 'New AI match', %s, %s)
                """, (
                    p["hiring_manager_id"],
                    f"{candidate.get('name')} matched {p.get('title')} at {int(scores['composite'])}%",
                    f"/positions/{p.get('slug')}",
                ))
        matches += 1
    logger.info(f"auto_match_candidate {cand_id}: {matches} positions matched")


async def handle_auto_rescore_position(payload: dict):
    if not _flag("auto_rescore_on_weight_change", True):
        return
    pos_id = payload.get("position_id")
    if not pos_id: return
    from backend.routes.matching import score_candidate_against_position
    with get_cursor() as cur:
        cur.execute("SELECT * FROM positions WHERE id = %s", (pos_id,))
        row = cur.fetchone()
        if not row: return
        cols = [d[0] for d in cur.description]
        position = dict(zip(cols, row))
        cur.execute("""
            SELECT c.*, pc.id AS pc_id FROM position_candidates pc
            JOIN candidates c ON c.id = pc.candidate_id
            WHERE pc.position_id = %s AND COALESCE(pc.dismissed, FALSE) = FALSE
        """, (pos_id,))
        cc = [d[0] for d in cur.description]
        rows = [dict(zip(cc, r)) for r in cur.fetchall()]

    rescored = 0
    for c in rows:
        try:
            s = score_candidate_against_position(c, position)
        except Exception:
            continue
        with get_cursor() as cur:
            cur.execute("""
                UPDATE position_candidates SET
                  match_score_composite=%s, match_score_skills=%s, match_score_experience=%s,
                  match_score_education=%s, match_score_certifications=%s, match_score_industry=%s,
                  skills_matched=%s, skills_missing=%s, updated_at=NOW()
                WHERE id = %s
            """, (
                s["composite"], s["skills"], s["experience"],
                s["education"], s["certifications"], s["industry"],
                s.get("skills_matched", []), s.get("skills_missing", []),
                c["pc_id"],
            ))
        rescored += 1
    logger.info(f"auto_rescore_position {pos_id}: {rescored} candidates")


async def handle_auto_rescore_jd_chain(payload: dict):
    jd_id = payload.get("jd_id")
    if not jd_id: return
    with get_cursor() as cur:
        cur.execute("""
            SELECT id FROM positions
            WHERE weights_source_jd_id = %s
              AND COALESCE(weights_overridden, FALSE) = FALSE
              AND status = 'active'
        """, (jd_id,))
        ids = [r[0] for r in cur.fetchall()]
    for pid in ids:
        enqueue_dedup("auto_rescore_position", {"position_id": pid})
    logger.info(f"auto_rescore_jd_chain {jd_id}: fanned out to {len(ids)} positions")


async def handle_auto_predict_lth(payload: dict):
    """Compute likelihood-to-hire for every active (non-dismissed) position_candidate."""
    from backend.routes.analytics_v2 import compute_lth
    from datetime import datetime
    updated = 0
    with get_cursor() as cur:
        cur.execute("""
            SELECT pc.id, pc.candidate_id, pc.position_id, pc.match_score_composite,
                   pc.stage, pc.created_at, pc.stage_changed_at,
                   NULL::numeric AS avg_scorecard
              FROM position_candidates pc
             WHERE COALESCE(pc.dismissed, FALSE) = FALSE
               AND pc.stage NOT IN ('hired','rejected')
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    for pc in rows:
        try:
            with get_cursor() as cur:
                cur.execute(
                    "SELECT flag_type FROM candidate_flags WHERE candidate_id=%s AND position_id=%s",
                    (pc["candidate_id"], pc["position_id"]),
                )
                flags = [{"flag_type": r[0]} for r in cur.fetchall()]
            ref = pc.get("stage_changed_at") or pc.get("created_at")
            age = 0
            if ref:
                try:
                    ref_naive = ref.replace(tzinfo=None) if getattr(ref, "tzinfo", None) else ref
                    age = (datetime.utcnow() - ref_naive).days
                except Exception:
                    age = 0
            pc["stage_age_days"] = age
            prob, _feat = compute_lth(pc, flags)
            with get_cursor() as cur:
                cur.execute(
                    "UPDATE position_candidates SET likelihood_to_hire=%s, lth_updated_at=NOW() WHERE id=%s",
                    (prob, pc["id"]),
                )
            updated += 1
        except Exception as e:
            logger.warning(f"lth predict failed for pc {pc.get('id')}: {e}")
            continue
    logger.info(f"auto_predict_lth: updated {updated} position_candidates")


async def handle_auto_forecast_position(payload: dict):
    """Compute forecast_days_to_fill (median of comparable past hires) per active position."""
    updated = 0
    with get_cursor() as cur:
        cur.execute("""
            SELECT id, department, title, seniority_level, forecast_updated_at
              FROM positions
             WHERE status = 'active'
               AND (forecast_updated_at IS NULL
                    OR forecast_updated_at < NOW() - INTERVAL '7 days')
        """ if False else """
            SELECT id, department, title, NULL AS seniority_level, forecast_updated_at
              FROM positions
             WHERE status = 'active'
               AND (forecast_updated_at IS NULL
                    OR forecast_updated_at < NOW() - INTERVAL '7 days')
        """)
        positions = cur.fetchall()

    for pos_id, dept, title, _sen, _ts in positions:
        try:
            with get_cursor() as cur:
                cur.execute("""
                    SELECT EXTRACT(EPOCH FROM (MIN(pc.stage_changed_at) - p.created_at))/86400 AS days
                      FROM positions p
                      JOIN position_candidates pc ON pc.position_id = p.id
                     WHERE pc.stage = 'hired'
                       AND p.id <> %s
                       AND COALESCE(p.department,'') = COALESCE(%s,'')
                  GROUP BY p.id
                """, (pos_id, dept))
                days = sorted([float(r[0]) for r in cur.fetchall() if r[0] is not None])

            if not days:
                continue
            mid = len(days) // 2
            median = days[mid] if len(days) % 2 else (days[mid - 1] + days[mid]) / 2
            confidence = 0.9 if len(days) >= 5 else (0.6 if len(days) >= 3 else 0.3)

            with get_cursor() as cur:
                cur.execute(
                    """UPDATE positions
                          SET forecast_days_to_fill=%s,
                              forecast_confidence=%s,
                              forecast_updated_at=NOW()
                        WHERE id=%s""",
                    (round(median, 2), confidence, pos_id),
                )
            updated += 1
        except Exception as e:
            logger.warning(f"forecast failed for position {pos_id}: {e}")
            continue
    logger.info(f"auto_forecast_position: updated {updated} positions")


HANDLERS = {
    "auto_scan_position":      handle_auto_scan_position,
    "auto_match_candidate":    handle_auto_match_candidate,
    "auto_rescore_position":   handle_auto_rescore_position,
    "auto_rescore_jd_chain":   handle_auto_rescore_jd_chain,
    "auto_predict_lth":        handle_auto_predict_lth,
    "auto_forecast_position":  handle_auto_forecast_position,
}


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------
_predictive_state = {"poll_count": 0, "last_run_ts": 0.0}


async def worker_loop(poll_interval: float = 2.0):
    import time as _time
    logger.info("[sync-worker] starting")
    while True:
        # Periodic predictive enqueue: every ~3600 polls (~2h), if last run > 24h ago.
        try:
            _predictive_state["poll_count"] += 1
            if _predictive_state["poll_count"] % 3600 == 0:
                now_ts = _time.time()
                if now_ts - _predictive_state["last_run_ts"] > 86400:
                    enqueue_dedup("auto_predict_lth", {})
                    enqueue_dedup("auto_forecast_position", {})
                    _predictive_state["last_run_ts"] = now_ts
                    logger.info("[sync-worker] predictive nightly jobs enqueued")
        except Exception:
            pass
        try:
            job = get_pending_job()
        except Exception as e:
            logger.error(f"[sync-worker] poll error: {e}")
            await asyncio.sleep(poll_interval); continue

        if not job:
            await asyncio.sleep(poll_interval); continue

        kind = job.get("job_type")
        payload = job.get("payload") or {}
        if isinstance(payload, str):
            try: payload = json.loads(payload)
            except Exception: payload = {}

        handler = HANDLERS.get(kind)
        if not handler:
            # not ours — leave for other workers
            with get_cursor() as cur:
                cur.execute("UPDATE job_queue SET status='pending' WHERE id=%s AND status='running'", (job["id"],))
            await asyncio.sleep(poll_interval); continue

        try:
            await handler(payload)
            complete_job(job["id"])
        except Exception as e:
            logger.exception(f"[sync-worker] handler {kind} failed")
            fail_job(job["id"], str(e))
