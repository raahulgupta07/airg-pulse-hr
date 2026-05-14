"""JWT helpers (HS256) for the HIRE auth subsystem.

Used by backend/routes/auth.py and the legacy `validate_token` shim in
backend/core/auth.py (Task 8 — accept both JWTs and legacy tokens).
"""
from __future__ import annotations

import os
import time
import logging
from typing import Any

import jwt  # PyJWT

logger = logging.getLogger(__name__)


def _secret() -> str:
    s = os.getenv("JWT_SECRET")
    if not s:
        raise RuntimeError("JWT_SECRET env var is required")
    return s


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
