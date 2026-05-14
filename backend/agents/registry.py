"""Central registry for all background + on-demand agents.

Each agent reports its lifecycle (idle/running/error/disabled) + last heartbeat
+ events processed counter. Admin UI reads this via GET /api/agents.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

# Optional `run_once` callables registered by individual agents that support
# admin-triggered single-cycle test runs. Keyed by agent_id.
RUN_ONCE: dict[str, Callable] = {}


def register_run_once(agent_id: str, fn: Callable) -> None:
    """Agents call this to expose an out-of-schedule single-cycle entrypoint."""
    RUN_ONCE[agent_id] = fn


def get_run_once(agent_id: str) -> Optional[Callable]:
    return RUN_ONCE.get(agent_id)


# DB-backed enabled gate. Cached for ~10s to avoid hammering pg per loop tick.
_enabled_cache: dict[str, tuple[float, bool]] = {}
_ENABLED_TTL_S = 10.0


def is_enabled(agent_id: str) -> bool:
    """Poll-cached lookup of agent_configs.enabled. Defaults TRUE on any error."""
    import time as _time
    now = _time.time()
    hit = _enabled_cache.get(agent_id)
    if hit and (now - hit[0]) < _ENABLED_TTL_S:
        return hit[1]
    val = True
    try:
        from backend.core.database import get_cursor
        with get_cursor() as cur:
            cur.execute("SELECT enabled FROM agent_configs WHERE agent_id = %s", (agent_id,))
            row = cur.fetchone()
            if row is not None:
                val = bool(row[0])
    except Exception:
        val = True
    _enabled_cache[agent_id] = (now, val)
    return val


def invalidate_enabled_cache(agent_id: str | None = None) -> None:
    if agent_id is None:
        _enabled_cache.clear()
    else:
        _enabled_cache.pop(agent_id, None)


# Cached interval lookup so admin slider in Agent Config UI actually changes cadence.
_interval_cache: dict[str, tuple[float, int]] = {}
_INTERVAL_TTL_S = 10.0


def get_interval(agent_id: str, default_s: int) -> int:
    """Return interval_seconds from agent_configs, falling back to default."""
    import time as _time
    now = _time.time()
    hit = _interval_cache.get(agent_id)
    if hit and (now - hit[0]) < _INTERVAL_TTL_S:
        return hit[1]
    val = int(default_s)
    try:
        from backend.core.database import get_cursor
        with get_cursor() as cur:
            cur.execute("SELECT interval_seconds FROM agent_configs WHERE agent_id = %s", (agent_id,))
            row = cur.fetchone()
            if row is not None and row[0]:
                val = int(row[0])
    except Exception:
        pass
    _interval_cache[agent_id] = (now, val)
    return val


def invalidate_interval_cache(agent_id: str | None = None) -> None:
    if agent_id is None:
        _interval_cache.clear()
    else:
        _interval_cache.pop(agent_id, None)


# Per-agent daily LLM cost cap. Reads agent_configs.thresholds.llm_daily_cap_usd if set.
def get_llm_daily_cap(agent_id: str, default_usd: float = 5.0) -> float:
    try:
        from backend.core.database import get_cursor
        with get_cursor() as cur:
            cur.execute("SELECT thresholds FROM agent_configs WHERE agent_id = %s", (agent_id,))
            row = cur.fetchone()
            if row and row[0] and isinstance(row[0], dict):
                v = row[0].get("llm_daily_cap_usd")
                if v is not None:
                    return float(v)
    except Exception:
        pass
    import os
    return float(os.getenv("AGENT_LLM_DAILY_CAP_USD", default_usd))


def check_agent_cost_cap(agent_id: str) -> tuple[bool, float, float]:
    """Return (within_cap, spent_today, cap). Falls open on any DB error."""
    cap = get_llm_daily_cap(agent_id)
    try:
        from backend.core.database import get_cursor
        with get_cursor() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(cost_usd), 0)
                FROM llm_call_log
                WHERE step = %s AND ts >= CURRENT_DATE
            """, (f"agent:{agent_id}",))
            spent = float(cur.fetchone()[0] or 0)
    except Exception:
        return True, 0.0, cap
    return (spent < cap), spent, cap

# Static metadata (descriptive, doesn't change at runtime)
AGENTS_META: dict[str, dict[str, Any]] = {
    "match": {
        "name": "Match Agent",
        "purpose": "Re-scores CVs against positions when JDs or CVs change",
        "type": "continuous",
        "owner_file": "backend/agents/sync.py",
    },
    "sweeper": {
        "name": "Sweeper Agent",
        "purpose": "Marks stale ai-scans (>10 min) as errored after crash recovery",
        "type": "scheduled",
        "interval_s": 300,
        "owner_file": "backend/main.py:_stale_sweeper_loop",
    },
    "jd-field-poll": {
        "name": "JD Field Agent (poll)",
        "purpose": "Fallback poll: fills missing JD fields (skills, dept, seniority, certs, KF4D)",
        "type": "scheduled",
        "interval_s": 60,
        "owner_file": "backend/agents/jd_background.py",
    },
    "jd-field-realtime": {
        "name": "JD Field Agent (realtime)",
        "purpose": "LISTEN/NOTIFY: enriches JDs within 3-5s of insert/update",
        "type": "event-driven",
        "owner_file": "backend/agents/jd_enrich_listener.py",
    },
    "pipeline": {
        "name": "Pipeline Agent",
        "purpose": "Runs 13-step CV processing pipeline (CLASSIFY → EXTRACT → … → AI_SUMMARY)",
        "type": "continuous",
        "owner_file": "backend/routes/candidates.py:_queue_worker",
    },
    "scan": {
        "name": "Position Scan Agent",
        "purpose": "Triggered scan: scores all CVs vs a position on create / JD update / rescan",
        "type": "triggered",
        "owner_file": "backend/routes/positions.py:auto_scan_for_position",
    },
    "reformat": {
        "name": "JD Reformat Agent",
        "purpose": "Restructures messy JD layout into clean markdown (preserves wording)",
        "type": "triggered",
        "owner_file": "backend/agents/jd_reformat.py",
    },
    "backup": {
        "name": "Backup Agent",
        "purpose": "Daily pg_dump of pulsedb to gzipped archive (14d retention)",
        "type": "scheduled",
        "interval_s": 86400,
        "owner_file": "compose.yaml:backup (sidecar container)",
    },
    "jd-bias": {
        "name": "JD Bias Detector",
        "purpose": "Flags gendered/ageist/ableist phrases in JDs and stores bias_report JSONB",
        "type": "scheduled",
        "interval_s": 1800,
        "owner_file": "backend/agents/jd_bias_detector.py",
    },
    "jd-refresh": {
        "name": "JD Refresh Agent",
        "purpose": "Notifies owners of stale JDs (>60d) whose linked positions are still open",
        "type": "scheduled",
        "interval_s": 21600,
        "owner_file": "backend/agents/jd_refresher.py",
    },
    "jd-translator": {
        "name": "JD Translator",
        "purpose": "Translates JDs into requested languages (translate_to[]) into jd_translations table",
        "type": "scheduled",
        "interval_s": 1800,
        "owner_file": "backend/agents/jd_translator.py",
    },
    "jd-completeness": {
        "name": "JD Completeness Scorer",
        "purpose": "Nightly heuristic 0-100 completeness score per JD; notifies on score<50",
        "type": "scheduled",
        "interval_s": 86400,
        "owner_file": "backend/agents/jd_completeness.py",
    },
    "brain-trainer": {
        "name": "Brain Trainer",
        "purpose": "Logs Copilot questions where assistant returned low-confidence / I-don't-know responses; notifies admins",
        "type": "scheduled",
        "interval_s": 21600,
        "owner_file": "backend/agents/brain_trainer.py",
    },
    "doc-ingestor": {
        "name": "Document Ingestor",
        "purpose": "Parses admin-uploaded HR policy PDF/DOCX/TXT, chunks + embeds into org_brain table",
        "type": "scheduled",
        "interval_s": 300,
        "owner_file": "backend/agents/doc_ingestor.py",
    },
    "qa-suggester": {
        "name": "Q&A Suggester",
        "purpose": "Generates 3 candidate-position interview questions on demand from recruiter drawer opens",
        "type": "scheduled",
        "interval_s": 60,
        "owner_file": "backend/agents/qa_suggester.py",
    },
    "faq-builder": {
        "name": "FAQ Builder",
        "purpose": "Nightly: clusters last 30d Copilot user questions and writes canonical FAQs (cluster size >= 3)",
        "type": "scheduled",
        "interval_s": 86400,
        "owner_file": "backend/agents/faq_builder.py",
    },
}

# Mutable state per agent (heartbeat + counters). Thread-safe via lock.
_lock = threading.RLock()
_state: dict[str, dict[str, Any]] = {
    k: {
        "status": "idle",          # idle | running | error | disabled
        "last_heartbeat_at": None,
        "last_run_at": None,
        "last_activity_at": None,  # set on heartbeat OR cycle_done — used for "recently active" pulse
        "next_run_at": None,
        "events_total": 0,
        "errors_total": 0,
        "current_action": None,
        "last_error": None,
    } for k in AGENTS_META
}


def heartbeat(agent_id: str, *, status: str = "running", action: str | None = None,
              next_run_at: datetime | None = None) -> None:
    """Called by each agent loop each tick."""
    with _lock:
        if agent_id not in _state:
            return
        s = _state[agent_id]
        now = datetime.now(timezone.utc).isoformat()
        s["status"] = status
        s["last_heartbeat_at"] = now
        if status == "running":
            s["current_action"] = action
            s["last_activity_at"] = now  # mark active for "recently busy" pulse window
        elif status == "idle":
            s["current_action"] = None
        if next_run_at:
            s["next_run_at"] = next_run_at.isoformat() if isinstance(next_run_at, datetime) else next_run_at


def cycle_done(agent_id: str, *, events: int = 0, error: str | None = None) -> None:
    """Called when an agent finishes a cycle / job."""
    with _lock:
        if agent_id not in _state:
            return
        s = _state[agent_id]
        now = datetime.now(timezone.utc).isoformat()
        s["last_run_at"] = now
        s["last_activity_at"] = now
        s["events_total"] += int(events or 0)
        if error:
            s["errors_total"] += 1
            s["last_error"] = str(error)[:300]
            s["status"] = "error"
        else:
            s["status"] = "idle"
            s["current_action"] = None


def snapshot() -> list[dict[str, Any]]:
    """Return list of all agents w/ meta + state for admin dashboard."""
    with _lock:
        out = []
        for k, meta in AGENTS_META.items():
            out.append({"id": k, **meta, **_state[k]})
        return out
