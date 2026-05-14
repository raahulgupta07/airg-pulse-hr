"""Retention helpers — read/write `app_settings.expiry_defaults`.

Schema (mig 056): ``{"cv_days": 90, "jd_days": 90}``.

Used by candidate + JD INSERT paths to stamp ``expires_at = NOW() + N days``.
Pure visual signal — nothing in the system blocks edits or excludes expired
rows from search/AI scan. See admin Retention panel for write UI.
"""
from __future__ import annotations

import json
import logging
from typing import Literal

from backend.core.database import get_cursor

logger = logging.getLogger(__name__)

DEFAULTS = {"cv_days": 90, "jd_days": 90}
_KEY = "expiry_defaults"
_VALID_KINDS = ("cv", "jd")


def _read_raw() -> dict:
    try:
        with get_cursor() as cur:
            cur.execute("SELECT value FROM app_settings WHERE key = %s", (_KEY,))
            row = cur.fetchone()
    except Exception as e:  # table missing during early boot
        logger.debug(f"[expiry] read failed: {e}")
        return dict(DEFAULTS)
    if not row:
        return dict(DEFAULTS)
    val = row[0]
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            val = {}
    out = dict(DEFAULTS)
    if isinstance(val, dict):
        for k in ("cv_days", "jd_days"):
            v = val.get(k)
            if isinstance(v, (int, float)) and v > 0:
                out[k] = int(v)
    return out


def get_default_expiry_days(kind: Literal["cv", "jd"]) -> int:
    """Return configured retention in days for the given kind, or 90 fallback."""
    if kind not in _VALID_KINDS:
        return 90
    cfg = _read_raw()
    return int(cfg.get(f"{kind}_days") or 90)


def get_retention_settings() -> dict:
    """Return the full {cv_days, jd_days} settings dict."""
    return _read_raw()


def set_retention_settings(cv_days: int, jd_days: int, user_id: int | None = None) -> dict:
    """Persist new retention defaults. Caller is expected to have admin/recruiter+ role."""
    cv = max(1, min(int(cv_days or 90), 3650))
    jd = max(1, min(int(jd_days or 90), 3650))
    payload = {"cv_days": cv, "jd_days": jd}
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO app_settings (key, value, updated_by, updated_at)
               VALUES (%s, %s::jsonb, %s, NOW())
               ON CONFLICT (key) DO UPDATE
                 SET value = EXCLUDED.value,
                     updated_at = NOW(),
                     updated_by = EXCLUDED.updated_by""",
            (_KEY, json.dumps(payload), user_id),
        )
    return payload
