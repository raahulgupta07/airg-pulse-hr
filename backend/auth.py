"""PULSE auth — email/password + JWT (HttpOnly cookie) + X-Dev-Bypass.

This module is the canonical entry point for the cookie-based session flow:
- `hash_password` / `verify_password` — bcrypt
- `create_token` / `decode_token` — PyJWT HS256 with `JWT_SECRET`

It coexists with the legacy operator_id/Bearer system in
`backend/core/auth.py` + `backend/core/jwt_auth.py`. The dependency
`get_current_user` (re-exported from `backend.core.auth` and extended here)
handles cookie → Bearer → DEV_MODE fallback.
"""
from __future__ import annotations

import os
import time
import logging
from typing import Any

import bcrypt
import jwt  # PyJWT

logger = logging.getLogger(__name__)

_DEV_DEFAULT_SECRET = "pulse-dev-secret-DO-NOT-USE-IN-PROD"


def _secret() -> str:
    s = os.getenv("JWT_SECRET")
    if not s:
        logger.warning(
            "JWT_SECRET not set — using insecure dev default. "
            "Set JWT_SECRET in env for production."
        )
        return _DEV_DEFAULT_SECRET
    return s


def hash_password(plain: str) -> str:
    """Bcrypt-hash a plaintext password (cost 12)."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt verify; never raises."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_token(user_id: int, role: str, ttl_hours: int = 12) -> str:
    """JWT HS256 token with sub=user_id, role, exp."""
    exp = int(time.time()) + int(ttl_hours * 3600)
    payload = {"sub": str(user_id), "user_id": int(user_id), "role": role, "exp": exp}
    token = jwt.encode(payload, _secret(), algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode()
    return token


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT. Raises jwt.PyJWTError on failure."""
    payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    return {
        "user_id": int(payload.get("user_id") or payload.get("sub") or 0),
        "role": payload.get("role") or "viewer",
        "exp": payload.get("exp"),
        "sub": payload.get("sub"),
    }
