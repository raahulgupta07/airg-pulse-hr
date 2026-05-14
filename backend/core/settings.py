"""Persistent settings store.

User-tweakable knobs that must SURVIVE container redeploys. Backed by the
`settings` table (mig 030), JSONB values, scope-tagged, with a 30s in-memory
TTL cache to avoid a DB round-trip per call.

Why this exists:
  - Env vars are baked into the container image / orchestrator config and
    require a redeploy to change. Anything a superadmin should tweak from
    the UI (branding, scoring weights, feature toggles) must live here.

Usage:
    from backend.core.settings import get_setting, set_setting
    name = get_setting("branding.app_name", default="PULSE")
    set_setting("branding.app_name", "ACME", scope="global",
                description="Brand display name")
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

from backend.core.database import get_cursor

logger = logging.getLogger(__name__)

_TTL_S = 30.0
_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}  # key -> (expires_at, value)
_list_cache: dict[Optional[str], tuple[float, list[dict]]] = {}


def _now() -> float:
    return time.time()


def _invalidate(key: Optional[str] = None) -> None:
    with _lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)
        _list_cache.clear()


def get_setting(key: str, default: Any = None) -> Any:
    """Read JSONB value for `key`. Returns `default` if missing.

    Cached in-memory for 30s. Thread-safe.
    """
    now = _now()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]

    try:
        with get_cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
            row = cur.fetchone()
    except Exception as e:
        logger.warning(f"[settings] get_setting({key}) DB error: {e}")
        return default

    value = row[0] if row else default
    # psycopg returns JSONB as already-parsed Python object; guard for str.
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            pass
    with _lock:
        _cache[key] = (now + _TTL_S, value)
    return value


def set_setting(key: str, value: Any, scope: str = "global",
                description: str = "") -> None:
    """UPSERT a setting. Invalidates cache for this key + list cache."""
    payload = json.dumps(value)
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO settings(key, value, scope, description, updated_at)
            VALUES (%s, %s::jsonb, %s, %s, now())
            ON CONFLICT (key) DO UPDATE SET
              value = EXCLUDED.value,
              scope = EXCLUDED.scope,
              description = COALESCE(NULLIF(EXCLUDED.description, ''),
                                     settings.description),
              updated_at = now()
            """,
            (key, payload, scope, description),
        )
    _invalidate(key)


def delete_setting(key: str) -> None:
    """Remove a setting. No-op if absent."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM settings WHERE key = %s", (key,))
    _invalidate(key)


def list_settings(scope: Optional[str] = None) -> list[dict]:
    """List settings, optionally filtered by scope. 30s cache."""
    now = _now()
    with _lock:
        hit = _list_cache.get(scope)
        if hit and hit[0] > now:
            return hit[1]

    with get_cursor() as cur:
        if scope is None:
            cur.execute(
                "SELECT key, value, scope, description, updated_at "
                "FROM settings ORDER BY scope, key"
            )
        else:
            cur.execute(
                "SELECT key, value, scope, description, updated_at "
                "FROM settings WHERE scope = %s ORDER BY key",
                (scope,),
            )
        rows = cur.fetchall()

    out = []
    for k, v, sc, desc, ts in rows:
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                pass
        out.append({
            "key": k,
            "value": v,
            "scope": sc,
            "description": desc,
            "updated_at": ts.isoformat() if ts else None,
        })
    with _lock:
        _list_cache[scope] = (now + _TTL_S, out)
    return out


def seed_default(key: str, value: Any, scope: str = "global",
                 description: str = "") -> bool:
    """Insert a default ONLY if missing. Returns True if inserted.

    Uses ON CONFLICT DO NOTHING so existing user-edited values are preserved
    across redeploys.
    """
    payload = json.dumps(value)
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO settings(key, value, scope, description)
            VALUES (%s, %s::jsonb, %s, %s)
            ON CONFLICT (key) DO NOTHING
            """,
            (key, payload, scope, description),
        )
        inserted = cur.rowcount > 0
    if inserted:
        _invalidate(key)
    return inserted


def seed_defaults() -> None:
    """Seed PULSE default settings on startup. Idempotent."""
    defaults = [
        ("branding.app_name", "PULSE", "branding",
         "Application display name shown in header + login page"),
        ("branding.tagline", "Org Heartbeat — People · Updates · Lifecycle · Sourcing · Engagement",
         "branding", "Subtitle / tagline displayed under app name"),
        # Mirrors backend/core/weights.DEFAULTS (percent-form), normalized to 1.0
        # for the matching engine. Edit via /api/settings/matching.weights.
        ("matching.weights", {
            "skills": 0.30,
            "experience": 0.20,
            "industry": 0.10,
            "education": 0.10,
            "certifications": 0.05,
            "culture": 0.10,
            "competencies": 0.15,
        }, "matching",
         "Default per-dimension scoring weights. Sum to 1.0. "
         "Overridden per-tenant/sector/JD/position via inheritance chain."),
    ]
    inserted = 0
    for key, val, scope, desc in defaults:
        try:
            if seed_default(key, val, scope, desc):
                inserted += 1
        except Exception as e:
            logger.warning(f"[settings] seed_default({key}) failed: {e}")
    if inserted:
        logger.info(f"[settings] seeded {inserted} default(s)")
    else:
        logger.info("[settings] all defaults already present")
