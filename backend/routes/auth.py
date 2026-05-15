"""Auth routes — JWT-based login/register/me/logout/config + legacy users list.

Schema: HS256 JWT with {sub: operator_id, role, exp}. Bcrypt cost 12 for
password hashing. Returns generic INVALID_CREDENTIALS on login fail (no
user-enumeration). Lockout after N consecutive fails (env LOGIN_LOCKOUT_AFTER,
default 5) for M minutes (env LOGIN_LOCKOUT_MIN, default 15).
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from pydantic import BaseModel, Field

from backend.core.database import get_cursor
from backend.core.jwt_auth import create_token, verify_token
from backend.core.rate_limit import limiter
from backend.auth import (
    hash_password as _hash_pw_v2,
    verify_password as _verify_pw_v2,
    create_token as _create_jwt_v2,
    decode_token as _decode_jwt_v2,
)

logger = logging.getLogger(__name__)
router = APIRouter()
# Separate router mounted under /api/users for self-service profile endpoints
# (notification preferences, change-password lives under /api/auth).
users_router = APIRouter()

APP_NAME = "PULSE"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    # Both shapes accepted: legacy operator_id/access_key and new email/password.
    operator_id: str | None = Field(None, max_length=200)
    access_key: str | None = Field(None, max_length=200)
    email: str | None = Field(None, max_length=200)
    password: str | None = Field(None, max_length=200)


class RegisterRequest(BaseModel):
    operator_id: str | None = Field(None, max_length=200)
    access_key: str | None = Field(None, max_length=200)
    email: str | None = Field(None, max_length=200)
    password: str | None = Field(None, max_length=200)
    name: str | None = Field(None, max_length=200)
    role: str = "operator"


class EmailLoginRequest(BaseModel):
    email: str = Field(..., max_length=200)
    password: str = Field(..., min_length=1, max_length=200)


class EmailRegisterRequest(BaseModel):
    email: str = Field(..., max_length=200)
    password: str = Field(..., min_length=8, max_length=200)
    name: str = Field(..., max_length=200)
    role: str = "recruiter"


COOKIE_NAME = "pulse_token"
COOKIE_TTL_HOURS = int(os.getenv("JWT_EXPIRY_H", "12"))


# ---------------------------------------------------------------------------
# Password helpers (bcrypt cost 12 — matches passlib[bcrypt] default)
# ---------------------------------------------------------------------------
def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Bearer auth dependency (JWT)
# ---------------------------------------------------------------------------
def _bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="MISSING_BEARER")
    return auth[7:]


def jwt_user(request: Request) -> dict:
    token = _bearer(request)
    try:
        return verify_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="INVALID_TOKEN")


def require_superadmin(request: Request) -> dict:
    u = jwt_user(request)
    if u.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="SUPERADMIN_REQUIRED")
    return u


# ---------------------------------------------------------------------------
# Lockout policy
# ---------------------------------------------------------------------------
def _lockout_after() -> int:
    return int(os.getenv("LOGIN_LOCKOUT_AFTER", "5"))


def _lockout_min() -> int:
    return int(os.getenv("LOGIN_LOCKOUT_MIN", "15"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/config")
async def auth_config():
    return {
        "allow_register": os.getenv("ALLOW_REGISTER", "false").lower() == "true",
        "app_name": APP_NAME,
    }


def _set_session_cookie(resp: Response, token: str) -> None:
    """Set HttpOnly cookie carrying the JWT session token."""
    secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    resp.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=COOKIE_TTL_HOURS * 3600,
        path="/",
    )


def _clear_session_cookie(resp: Response) -> None:
    resp.delete_cookie(key=COOKIE_NAME, path="/")


@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, response: Response, body: LoginRequest):
    # ----- New email/password path (HttpOnly cookie) -----
    if body.email and body.password:
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, email, display_name, password_hash, role FROM users "
                "WHERE email = %s AND COALESCE(is_active, TRUE) = TRUE",
                (body.email.lower().strip(),),
            )
            urow = cur.fetchone()
        if not urow or not urow[3] or not _verify_pw_v2(body.password, urow[3]):
            raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
        uid, em, name, _ph, role = urow
        try:
            with get_cursor() as cur:
                cur.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (uid,))
        except Exception:
            pass
        tok = _create_jwt_v2(uid, role or "viewer", ttl_hours=COOKIE_TTL_HOURS)
        _set_session_cookie(response, tok)
        return {"user": {"id": uid, "email": em, "name": name, "role": role}}

    # ----- Legacy operator_id path (Bearer token in response body) -----
    if not body.operator_id or not body.access_key:
        raise HTTPException(status_code=400, detail="MISSING_CREDENTIALS")
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, operator_id, pass_hash, role, failed_login_count, locked_until "
            "FROM users WHERE operator_id = %s",
            (body.operator_id,),
        )
        row = cur.fetchone()

    # Generic 401 on missing user (no enumeration)
    if not row:
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")

    uid, op_id, pass_hash, role, fail_count, locked_until = row
    fail_count = fail_count or 0

    # Check active lockout
    if locked_until is not None:
        now = datetime.now(timezone.utc)
        lu = locked_until if locked_until.tzinfo else locked_until.replace(tzinfo=timezone.utc)
        if lu > now:
            retry = int((lu - now).total_seconds())
            raise HTTPException(
                status_code=429,
                detail={"detail": "ACCOUNT_LOCKED", "retry_after": retry},
            )

    if not pass_hash or not verify_pw(body.access_key, pass_hash):
        new_count = fail_count + 1
        lock_clause = ""
        params: tuple = (new_count, uid)
        if new_count >= _lockout_after():
            lock_clause = f", locked_until = now() + interval '{_lockout_min()} minutes'"
        with get_cursor() as cur:
            cur.execute(
                f"UPDATE users SET failed_login_count = %s {lock_clause} WHERE id = %s",
                params,
            )
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")

    # Success — reset counters, update last_login_at
    with get_cursor() as cur:
        cur.execute(
            "UPDATE users SET failed_login_count = 0, locked_until = NULL, "
            "last_login_at = now() WHERE id = %s",
            (uid,),
        )

    token, exp = create_token(op_id, role)
    return {
        "token": token,
        "exp": exp,
        "user": {"operator_id": op_id, "role": role},
    }


def _current_user_from_request(request: Request) -> dict:
    """Resolve current user from cookie (new) or Bearer (legacy)."""
    cookie_tok = request.cookies.get(COOKIE_NAME)
    if cookie_tok:
        try:
            claims = _decode_jwt_v2(cookie_tok)
            uid = claims.get("user_id") or 0
            role = claims.get("role") or "viewer"
            with get_cursor() as cur:
                cur.execute(
                    "SELECT id, email, display_name, role FROM users WHERE id = %s",
                    (uid,),
                )
                row = cur.fetchone()
            if row:
                return {"id": row[0], "email": row[1], "name": row[2], "role": row[3] or role}
            return {"id": uid, "role": role}
        except Exception:
            raise HTTPException(status_code=401, detail="INVALID_TOKEN")
    # Fallback to legacy Bearer
    u = jwt_user(request)
    return {"operator_id": u["sub"], "role": u["role"]}


@router.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, body: RegisterRequest):
    if os.getenv("ALLOW_REGISTER", "false").lower() != "true":
        # Email-register may still be allowed when caller is admin/superadmin
        # (per spec: admin/superadmin can create users even when self-register is off).
        if body.email and body.password:
            caller = None
            try:
                caller = _current_user_from_request(request)
            except Exception:
                pass
            caller_role = (caller or {}).get("role", "")
            if caller_role not in ("admin", "superadmin"):
                raise HTTPException(status_code=403, detail="REGISTRATION_DISABLED")
        else:
            raise HTTPException(status_code=403, detail="REGISTRATION_DISABLED")

    # ----- New email/password path -----
    if body.email and body.password:
        if len(body.password) < 8:
            raise HTTPException(status_code=400, detail="PASSWORD_TOO_SHORT")
        # Only admin+ can assign elevated (non-default) roles
        requested_role = (body.role or "recruiter").lower()
        if requested_role not in ("recruiter", "viewer", "hiring_manager"):
            caller = None
            try:
                caller = _current_user_from_request(request)
            except Exception:
                pass
            caller_role = (caller or {}).get("role", "")
            if caller_role not in ("admin", "superadmin"):
                logger.warning(
                    "rbac_denied user_id=%s role=%s path=%s requires=admin (role-assign=%s)",
                    (caller or {}).get("id"), caller_role, request.url.path, requested_role,
                )
                raise HTTPException(status_code=403, detail="requires admin+ to assign this role")
            if requested_role == "superadmin" and caller_role != "superadmin":
                raise HTTPException(status_code=403, detail="superadmin role requires superadmin caller")
        pw_hash = _hash_pw_v2(body.password)
        try:
            with get_cursor() as cur:
                cur.execute(
                    "INSERT INTO users (email, display_name, password_hash, role) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (
                        body.email.lower().strip(),
                        body.name or body.email,
                        pw_hash,
                        body.role or "recruiter",
                    ),
                )
                uid = cur.fetchone()[0]
        except Exception as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                raise HTTPException(status_code=409, detail="EMAIL_EXISTS")
            logger.exception("register failed")
            raise HTTPException(status_code=500, detail="REGISTRATION_FAILED")
        return {
            "id": uid,
            "email": body.email,
            "name": body.name,
            "role": body.role or "recruiter",
        }

    # ----- Legacy operator_id path -----
    if not body.operator_id or not body.access_key:
        raise HTTPException(status_code=400, detail="MISSING_CREDENTIALS")
    if body.role and body.role != "operator":
        require_superadmin(request)
    pw_hash = hash_pw(body.access_key)
    try:
        with get_cursor() as cur:
            cur.execute(
                "INSERT INTO users (operator_id, pass_hash, role) VALUES (%s, %s, %s) "
                "RETURNING id",
                (body.operator_id, pw_hash, body.role or "operator"),
            )
            uid = cur.fetchone()[0]
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="OPERATOR_EXISTS")
        raise HTTPException(status_code=500, detail="REGISTRATION_FAILED")

    return {"id": uid, "operator_id": body.operator_id, "role": body.role or "operator"}


@router.get("/me")
async def me(request: Request):
    # Prefer cookie (new flow); fall back to legacy Bearer.
    cookie_tok = request.cookies.get(COOKIE_NAME)
    if cookie_tok:
        try:
            claims = _decode_jwt_v2(cookie_tok)
        except Exception:
            raise HTTPException(status_code=401, detail="INVALID_TOKEN")
        uid = claims.get("user_id") or 0
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, email, display_name, role FROM users WHERE id = %s",
                (uid,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="USER_NOT_FOUND")
        return {"user": {"id": row[0], "email": row[1], "name": row[2], "role": row[3]}}
    # Legacy Bearer path — preserved for existing M2 frontend
    u = jwt_user(request)
    return {"operator_id": u["sub"], "role": u["role"]}


@router.post("/logout")
async def logout(response: Response):
    _clear_session_cookie(response)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Bootstrap superadmin from env (called from main.py startup)
# ---------------------------------------------------------------------------
def bootstrap_superadmin() -> None:
    # Defaults so first boot always has a working admin login.
    # Override via env: SUPERADMIN_ID / SUPERADMIN_PASS_HASH / SUPERADMIN_PASS
    sid = (os.getenv("SUPERADMIN_ID") or "pulse_admin").strip()
    pass_hash = os.getenv("SUPERADMIN_PASS_HASH")
    if not pass_hash:
        plain = os.getenv("SUPERADMIN_PASS") or "admin"
        pass_hash = hash_pw(plain)
        if plain == "admin":
            logger.warning(
                "Using default superadmin password 'admin' — change SUPERADMIN_PASS in .env before production."
            )
        else:
            logger.warning("Plaintext SUPERADMIN_PASS hashed at startup (set SUPERADMIN_PASS_HASH for prod).")
    try:
        # `email` + `display_name` are legacy NOT NULL columns from the
        # pre-M2 users table; bootstrap synthesizes them from operator_id
        # so the same schema serves both legacy DEV users and operator_id auth.
        synth_email = sid if "@" in sid else f"{sid}@pulse.local"
        try:
            from backend.core.ids import gen_public_id
            pub_id = gen_public_id("users")
        except Exception:
            import secrets as _s
            pub_id = f"usr_{_s.token_hex(13)}"
        with get_cursor() as cur:
            cur.execute(
                "INSERT INTO users (operator_id, email, display_name, pass_hash, role, public_id) "
                "VALUES (%s, %s, %s, %s, 'superadmin', %s) "
                "ON CONFLICT (operator_id) DO UPDATE SET pass_hash = EXCLUDED.pass_hash, "
                "role = 'superadmin', failed_login_count = 0, locked_until = NULL",
                (sid, synth_email, sid, pass_hash, pub_id),
            )
        logger.info(f"Superadmin loaded from env: {sid}")
    except Exception as e:
        logger.error(f"bootstrap_superadmin failed: {e}")


# ---------------------------------------------------------------------------
# Legacy compatibility — list users / lookup (used by frontend mentions)
# ---------------------------------------------------------------------------
from fastapi import Query as _Query


# ---------------------------------------------------------------------------
# Notification preferences (per-user, free-form JSON dict)
# ---------------------------------------------------------------------------
def _resolve_uid(request: Request) -> int:
    """Resolve current user's numeric id from cookie or Bearer token.

    Mirrors `_current_user_from_request` but coerces to a numeric users.id
    (raising 401 if it can't), which is what notification + password endpoints
    need to UPDATE the row.
    """
    # Cookie path → user_id is on the JWT claims directly.
    cookie_tok = request.cookies.get(COOKIE_NAME)
    if cookie_tok:
        try:
            claims = _decode_jwt_v2(cookie_tok)
            uid = int(claims.get("user_id") or 0)
            if uid:
                return uid
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")
    # Bearer path (legacy operator_id JWT) — resolve via DB.
    u = jwt_user(request)
    op_id = u.get("sub")
    if not op_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    with get_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE operator_id = %s", (op_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    return int(row[0])


@users_router.get("/me/notifications")
async def get_my_notification_prefs(request: Request):
    """Return current user's notification preferences (defaults to {})."""
    uid = _resolve_uid(request)
    with get_cursor() as cur:
        cur.execute(
            "SELECT COALESCE(notification_prefs, '{}'::jsonb) FROM users WHERE id = %s",
            (uid,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    prefs = row[0]
    if isinstance(prefs, str):
        try:
            import json as _json
            prefs = _json.loads(prefs)
        except Exception:
            prefs = {}
    return {"prefs": prefs or {}}


@users_router.post("/me/notifications")
async def set_my_notification_prefs(request: Request):
    """Replace current user's notification preferences with the request body."""
    uid = _resolve_uid(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    import json as _json
    with get_cursor() as cur:
        cur.execute(
            "UPDATE users SET notification_prefs = %s::jsonb WHERE id = %s RETURNING id",
            (_json.dumps(body), uid),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "prefs": body}


# ---------------------------------------------------------------------------
# Change password (self-service)
# ---------------------------------------------------------------------------
class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=1, max_length=200)


@router.post("/change-password")
@limiter.limit("5/minute")
async def change_password(request: Request, body: ChangePasswordRequest):
    """Change current user's password.

    - 401 if current password is wrong
    - 400 if new password is invalid (too short / equals current)
    - 200 {ok: true} on success
    """
    uid = _resolve_uid(request)

    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must differ from current password")

    with get_cursor() as cur:
        cur.execute(
            "SELECT password_hash, pass_hash FROM users WHERE id = %s",
            (uid,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    pw_hash_v2, pw_hash_legacy = row

    # Try v2 hash first (email/password flow), then legacy operator_id hash.
    ok = False
    if pw_hash_v2 and _verify_pw_v2(body.current_password, pw_hash_v2):
        ok = True
    elif pw_hash_legacy and verify_pw(body.current_password, pw_hash_legacy):
        ok = True
    if not ok:
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_v2 = _hash_pw_v2(body.new_password)
    new_legacy = hash_pw(body.new_password)
    with get_cursor() as cur:
        # Update whichever column the user actually has set, plus the other if
        # it was set before — keeps both auth paths in sync.
        sets = []
        params: list = []
        if pw_hash_v2 is not None:
            sets.append("password_hash = %s")
            params.append(new_v2)
        if pw_hash_legacy is not None:
            sets.append("pass_hash = %s")
            params.append(new_legacy)
        if not sets:
            # User had neither set (shouldn't happen post-login) — set v2.
            sets.append("password_hash = %s")
            params.append(new_v2)
        params.append(uid)
        cur.execute(
            f"UPDATE users SET {', '.join(sets)}, failed_login_count = 0, "
            f"locked_until = NULL WHERE id = %s",
            params,
        )

    return {"ok": True}


@router.get("/users")
async def list_users(request: Request):
    jwt_user(request)
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, operator_id, role FROM users ORDER BY operator_id"
        )
        rows = cur.fetchall()
    return {"users": [{"id": r[0], "operator_id": r[1], "role": r[2]} for r in rows]}


@router.get("/users/lookup")
async def users_lookup(request: Request, q: str = _Query("", max_length=80), limit: int = _Query(10, le=50)):
    jwt_user(request)
    with get_cursor() as cur:
        if q:
            cur.execute(
                "SELECT id, operator_id, role FROM users WHERE operator_id ILIKE %s "
                "ORDER BY operator_id LIMIT %s",
                (f"%{q}%", limit),
            )
        else:
            cur.execute(
                "SELECT id, operator_id, role FROM users ORDER BY operator_id LIMIT %s",
                (limit,),
            )
        rows = cur.fetchall()
    return {"users": [{"id": r[0], "operator_id": r[1], "role": r[2]} for r in rows]}
