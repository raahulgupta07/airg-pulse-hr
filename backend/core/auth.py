"""Authentication — token-based auth with bcrypt + RBAC."""
from __future__ import annotations

import os
import re
import time
import secrets
import logging
import threading
from functools import wraps

import bcrypt
from fastapi import Request, HTTPException

from backend.core.database import get_cursor

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_SECONDS = 7 * 24 * 3600  # 7 days

# In-memory token cache (token -> {user_id, email, role, expiry})
_token_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: int, email: str) -> str:
    """Create a new auth token and store in DB + cache."""
    token = secrets.token_hex(32)
    expiry = int(time.time()) + TOKEN_EXPIRY_SECONDS

    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO auth_tokens (token, user_id, email, expiry) VALUES (%s, %s, %s, %s)",
            (token, user_id, email, expiry),
        )

    # Fetch role for cache
    with get_cursor() as cur:
        cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        role = row[0] if row else "viewer"

    with _cache_lock:
        _token_cache[token] = {
            "user_id": user_id,
            "email": email,
            "role": role,
            "expiry": expiry,
        }

    # Update last_login
    with get_cursor() as cur:
        cur.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user_id,))

    return token


def validate_token(token: str) -> dict | None:
    """Validate token from cache or DB. Returns user info or None.

    Task 8 (approach a — safe): try JWT (HS256, sub=operator_id, role) first;
    fall back to legacy hex-token DB lookup. New JWT-issued sessions are thus
    accepted by every existing route that uses get_current_user / require_role
    without changing those call sites.
    """
    # --- JWT path (new) ---
    try:
        from backend.core.jwt_auth import verify_token as _jwt_verify
        claims = _jwt_verify(token)
        # Resolve numeric user_id from operator_id if present in DB; else 0.
        op_id = claims.get("sub")
        role = claims.get("role") or "operator"
        user_id = 0
        try:
            with get_cursor() as cur:
                cur.execute("SELECT id FROM users WHERE operator_id = %s", (op_id,))
                r = cur.fetchone()
                if r:
                    user_id = r[0]
        except Exception:
            pass
        return {"user_id": user_id, "email": op_id, "role": role, "expiry": claims.get("exp", 0)}
    except Exception:
        pass  # not a JWT — fall through to legacy

    now = int(time.time())

    # Check cache first
    with _cache_lock:
        if token in _token_cache:
            info = _token_cache[token]
            if info["expiry"] > now:
                return info
            else:
                del _token_cache[token]
                return None

    # Check DB
    with get_cursor() as cur:
        cur.execute(
            "SELECT user_id, email, expiry FROM auth_tokens WHERE token = %s",
            (token,),
        )
        row = cur.fetchone()

    if not row or row[2] <= now:
        return None

    user_id, email, expiry = row

    # Fetch role
    with get_cursor() as cur:
        cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        role_row = cur.fetchone()
        role = role_row[0] if role_row else "viewer"

    info = {"user_id": user_id, "email": email, "role": role, "expiry": expiry}
    with _cache_lock:
        _token_cache[token] = info
    return info


def invalidate_token(token: str):
    """Remove a token (logout)."""
    with _cache_lock:
        _token_cache.pop(token, None)
    with get_cursor() as cur:
        cur.execute("DELETE FROM auth_tokens WHERE token = %s", (token,))


def get_current_user(request: Request) -> dict:
    """Extract and validate user from cookie, Bearer header, or DEV_MODE bypass.

    Resolution order:
      1. DEV_MODE=true AND header `X-Dev-Bypass: 1` → return synthetic admin (test path)
      2. `pulse_token` cookie → JWT decode → DB lookup
      3. `Authorization: Bearer <token>` header → JWT (new) or legacy hex token
      4. 401
    """
    dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"
    if dev_mode and request.headers.get("X-Dev-Bypass") == "1":
        return {"user_id": 1, "email": "dev@hire.local", "role": "admin"}

    # 1) HttpOnly cookie (new email/password flow)
    cookie_token = request.cookies.get("pulse_token")
    if cookie_token:
        try:
            from backend.auth import decode_token as _decode
            claims = _decode(cookie_token)
            uid = claims.get("user_id") or 0
            role = claims.get("role") or "viewer"
            email = None
            if uid:
                try:
                    with get_cursor() as cur:
                        cur.execute(
                            "SELECT email, display_name, role FROM users WHERE id = %s",
                            (uid,),
                        )
                        row = cur.fetchone()
                        if row:
                            email, _name, db_role = row
                            role = db_role or role
                except Exception:
                    pass
            return {"user_id": uid, "email": email, "role": role}
        except Exception:
            # Invalid cookie — fall through to Bearer or 401
            pass

    # 2) Bearer header (legacy + operator_id JWT)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        user = validate_token(token)
        if user:
            return user
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # 3) Query token (SSE / EventSource — no header support)
    qp_token = request.query_params.get("token")
    if qp_token:
        user = validate_token(qp_token)
        if user:
            return user
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    raise HTTPException(status_code=401, detail="Missing authorization")


def require_role(*roles):
    """Dependency that checks user has one of the specified roles."""
    def checker(request: Request):
        user = get_current_user(request)
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(roles)}")
        return user
    return checker


def validate_email(email: str) -> bool:
    return bool(re.match(r'^[\w.+-]+@[\w-]+\.[\w.-]+$', email))


def validate_password(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not any(c.isupper() for c in password):
        return "Password must contain at least one uppercase letter"
    if not any(c.isdigit() for c in password):
        return "Password must contain at least one number"
    return None


def register_user(email: str, display_name: str, password: str, role: str = "recruiter") -> dict:
    """Register a new user."""
    if not validate_email(email):
        raise ValueError("Invalid email address")
    pw_error = validate_password(password)
    if pw_error:
        raise ValueError(pw_error)
    pw_hash = hash_password(password)
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO users (email, display_name, password_hash, role)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (email, display_name, pw_hash, role),
        )
        user_id = cur.fetchone()[0]
    return {"user_id": user_id, "email": email, "display_name": display_name, "role": role}


def login_user(email: str, password: str) -> dict | None:
    """Authenticate user and return token + user info."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, email, display_name, password_hash, role FROM users WHERE email = %s AND is_active = TRUE",
            (email,),
        )
        row = cur.fetchone()

    if not row:
        return None

    user_id, db_email, display_name, pw_hash, role = row

    if not verify_password(password, pw_hash):
        return None

    token = create_token(user_id, db_email)
    return {
        "token": token,
        "user_id": user_id,
        "email": db_email,
        "display_name": display_name,
        "role": role,
    }
