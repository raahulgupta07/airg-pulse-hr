"""GET /api/agents — runtime status of every background agent.

Also exposes per-agent admin config (enabled / interval / thresholds) and an
admin-only test-run trigger that fires one cycle of an agent out of schedule.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.core.database import get_cursor
from backend.core.rate_limit import limiter
from backend.agents.registry import (
    snapshot,
    AGENTS_META,
    get_run_once,
    invalidate_enabled_cache,
    invalidate_interval_cache,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


@router.get("/")
async def list_agents(request: Request):
    """Public-to-authed list of agent statuses (any logged-in user can view)."""
    _ = get_current_user(request)
    return {"agents": snapshot()}


@router.get("/config")
async def list_agent_configs(request: Request):
    """All per-agent configs joined with registry metadata."""
    _ = get_current_user(request)
    cfg_by_id: dict[str, dict[str, Any]] = {}
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT agent_id, enabled, interval_seconds, thresholds,
                          updated_at, updated_by_id
                   FROM agent_configs"""
            )
            for r in cur.fetchall():
                cfg_by_id[r[0]] = {
                    "agent_id": r[0],
                    "enabled": bool(r[1]),
                    "interval_seconds": r[2],
                    "thresholds": r[3] or {},
                    "updated_at": r[4].isoformat() if r[4] else None,
                    "updated_by_id": r[5],
                }
    except Exception as e:
        logger.warning("agent_configs read failed: %s", e)

    snap_by_id = {a["id"]: a for a in snapshot()}
    # Union of registry agent ids + any extras present in agent_configs
    all_ids = set(AGENTS_META.keys()) | set(cfg_by_id.keys())
    out = []
    for aid in sorted(all_ids):
        meta = AGENTS_META.get(aid, {"name": aid, "purpose": "", "type": "unknown"})
        runtime = snap_by_id.get(aid, {})
        cfg = cfg_by_id.get(aid, {
            "agent_id": aid, "enabled": True, "interval_seconds": meta.get("interval_s"),
            "thresholds": {}, "updated_at": None, "updated_by_id": None,
        })
        out.append({
            "id": aid,
            "name": meta.get("name", aid),
            "purpose": meta.get("purpose", ""),
            "type": meta.get("type", "unknown"),
            "owner_file": meta.get("owner_file"),
            "default_interval_s": meta.get("interval_s"),
            "supports_test_run": get_run_once(aid) is not None,
            "config": cfg,
            "runtime": {
                "status": runtime.get("status"),
                "last_run_at": runtime.get("last_run_at"),
                "next_run_at": runtime.get("next_run_at"),
                "last_heartbeat_at": runtime.get("last_heartbeat_at"),
                "events_total": runtime.get("events_total", 0),
                "errors_total": runtime.get("errors_total", 0),
                "last_error": runtime.get("last_error"),
                "current_action": runtime.get("current_action"),
            },
        })
    return {"agents": out}


class AgentConfigPatch(BaseModel):
    enabled: Optional[bool] = None
    interval_seconds: Optional[int] = None
    thresholds: Optional[dict] = None


@router.patch("/config/{agent_id}")
async def patch_agent_config(agent_id: str, body: AgentConfigPatch, request: Request):
    """Admin-only UPSERT of an agent's runtime config."""
    user = _require_admin(request)
    if body.interval_seconds is not None and not (60 <= body.interval_seconds <= 86400):
        raise HTTPException(400, "interval_seconds must be between 60 and 86400")
    import json as _json
    thresholds_json = _json.dumps(body.thresholds) if body.thresholds is not None else None

    with get_cursor() as cur:
        # UPSERT — only overwrite supplied fields
        cur.execute(
            """INSERT INTO agent_configs (agent_id, enabled, interval_seconds, thresholds, updated_by_id, updated_at)
               VALUES (%s, COALESCE(%s, TRUE), %s, COALESCE(%s::jsonb, '{}'::jsonb), %s, now())
               ON CONFLICT (agent_id) DO UPDATE SET
                 enabled          = COALESCE(EXCLUDED.enabled, agent_configs.enabled),
                 interval_seconds = COALESCE(%s, agent_configs.interval_seconds),
                 thresholds       = COALESCE(%s::jsonb, agent_configs.thresholds),
                 updated_by_id    = EXCLUDED.updated_by_id,
                 updated_at       = now()
               RETURNING agent_id, enabled, interval_seconds, thresholds, updated_at""",
            (
                agent_id,
                body.enabled,
                body.interval_seconds,
                thresholds_json,
                user.get("id"),
                body.interval_seconds,
                thresholds_json,
            ),
        )
        row = cur.fetchone()

    invalidate_enabled_cache(agent_id)
    invalidate_interval_cache(agent_id)
    return {
        "agent_id": row[0],
        "enabled": bool(row[1]),
        "interval_seconds": row[2],
        "thresholds": row[3] or {},
        "updated_at": row[4].isoformat() if row[4] else None,
    }


@router.post("/{agent_id}/test-run")
@limiter.limit("10/minute")
async def test_run_agent(agent_id: str, request: Request):
    """Admin-only out-of-schedule single-cycle trigger."""
    _require_admin(request)
    if agent_id not in AGENTS_META and agent_id not in {
        "jd-bias","jd-refresh","jd-translator","jd-completeness",
        "brain-trainer","doc-ingestor","qa-suggester","faq-builder",
    }:
        raise HTTPException(404, f"unknown agent {agent_id}")
    fn = get_run_once(agent_id)
    if fn is None:
        raise HTTPException(501, f"test-run not implemented for agent '{agent_id}'")
    try:
        if inspect.iscoroutinefunction(fn):
            result = await asyncio.wait_for(fn(), timeout=120)
        else:
            result = await asyncio.wait_for(asyncio.to_thread(fn), timeout=120)
    except asyncio.TimeoutError:
        raise HTTPException(504, "agent test-run exceeded 120s")
    except Exception as e:
        logger.exception("test-run failed for %s", agent_id)
        raise HTTPException(500, f"test-run failed: {e}")
    return {"agent_id": agent_id, "ok": True, "result": result if isinstance(result, (dict, list, str, int, float, bool)) else None}


@router.get("/{agent_id}")
async def get_agent(agent_id: str, request: Request):
    _ = get_current_user(request)
    if agent_id not in AGENTS_META:
        raise HTTPException(404, f"unknown agent {agent_id}")
    snap = {a["id"]: a for a in snapshot()}
    return snap[agent_id]
