"""JWT helpers (HS256) for the HIRE auth subsystem.

Used by backend/routes/auth.py and the legacy `validate_token` shim in
backend/core/auth.py (Task 8 — accept both JWTs and legacy tokens).
"""
from __future__ import annotations

import os
import secrets as _secrets
import time
import logging
from pathlib import Path
from typing import Any

import jwt  # PyJWT

logger = logging.getLogger(__name__)

# Auto-generated secret persisted across restarts so tokens survive container recreate.
# Used only when JWT_SECRET env not set (dev / zero-config deploy).
_AUTOGEN_PATHS = [
    Path("/data/.jwt_secret"),       # preferred — persisted across restarts
    Path("/var/lib/pulse/.jwt_secret"),
    Path("/tmp/.pulse_jwt_secret"),  # fallback — survives within container lifetime
]


def _autogen_secret() -> str:
    # Try each candidate path: read if exists + valid, else write new.
    for p in _AUTOGEN_PATHS:
        try:
            if p.exists():
                val = p.read_text().strip()
                if len(val) >= 32:
                    return val
        except Exception:
            continue
    # No existing secret found — generate + try to persist.
    val = _secrets.token_hex(32)
    for p in _AUTOGEN_PATHS:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(val)
            try:
                p.chmod(0o600)
            except Exception:
                pass
            logger.warning(
                "JWT_SECRET not set — generated random secret persisted to %s. "
                "Set JWT_SECRET in .env for multi-instance / production deploys.",
                p,
            )
            return val
        except Exception:
            continue
    # All paths failed — in-memory only (tokens won't survive restart, but app runs).
    logger.warning("JWT_SECRET auto-gen could not persist to disk — using in-memory secret (tokens lost on restart).")
    return val


# Cache so each call returns same value within process lifetime
_CACHED_SECRET: str | None = None


_BOGUS_SECRETS = {
    "", "change-me", "changeme", "secret", "your-jwt-secret",
    "your-secret-here", "replace-me", "todo", "xxx", "none", "null",
}


def _looks_valid(s: str) -> bool:
    """Reject placeholders, short strings, obvious dev values."""
    if not s:
        return False
    s_low = s.strip().lower()
    if s_low in _BOGUS_SECRETS:
        return False
    if len(s) < 32:
        return False
    # Reject if all-same-char or repeated pattern (e.g. "aaaaa..." or "abcabcabc")
    if len(set(s)) < 6:
        return False
    return True


def _secret() -> str:
    global _CACHED_SECRET
    if _CACHED_SECRET:
        return _CACHED_SECRET
    s = os.getenv("JWT_SECRET", "").strip()
    if not _looks_valid(s):
        if s:
            logger.warning(
                "JWT_SECRET present but invalid (placeholder / too short / low entropy). "
                "Falling back to auto-generated persistent secret."
            )
        s = _autogen_secret()
    _CACHED_SECRET = s
    return s


def reset_cache() -> None:
    """Test hook — drop cached secret so next _secret() call re-reads env."""
    global _CACHED_SECRET
    _CACHED_SECRET = None


def _expiry_seconds() -> int:
    return int(float(os.getenv("JWT_EXPIRY_H", "8")) * 3600)


def create_token(sub: str, role: str) -> tuple[str, int]:
    """Return (jwt, exp_unix)."""
    exp = int(time.time()) + _expiry_seconds()
    payload = {"sub": str(sub), "role": role, "exp": exp}
    token = jwt.encode(payload, _secret(), algorithm="HS256")
    # PyJWT >=2 returns str
    if isinstance(token, bytes):
        token = token.decode()
    return token, exp


def verify_token(token: str) -> dict[str, Any]:
    """Decode + verify; raises jwt.PyJWTError on failure."""
    payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    return {"sub": payload.get("sub"), "role": payload.get("role"), "exp": payload.get("exp")}
