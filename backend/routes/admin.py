"""Admin console — users, roles, audit, insights, system flags."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from backend.core.auth import (
    get_current_user,
    hash_password,
    validate_email,
    validate_password,
)
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter()
public_router = APIRouter()


@public_router.get("/features")
async def public_features():
    """Public read-only feature flag map. Used by frontend nav."""
    with get_cursor() as cur:
        cur.execute("SELECT key, value FROM system_flags WHERE key LIKE 'feature_%'")
        return {r[0]: bool(r[1]) for r in cur.fetchall()}


def require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class UserInvite(BaseModel):
    email: str
    display_name: str
    role: str = "recruiter"
    password: Optional[str] = None
    department: Optional[str] = None


class UserPatch(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/users")
async def list_users(
    request: Request,
    q: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    require_admin(request)
    conds, params = [], []
    if q:
        conds.append("(email ILIKE %s OR display_name ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if role:
        conds.append("role = %s")
        params.append(role)
    if is_active is not None:
        conds.append("is_active = %s")
        params.append(is_active)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM users {where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"""SELECT id, email, display_name, role, department, is_active,
                       last_login, created_at
                FROM users {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s""",
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    users = [
        {
            "id": r[0], "email": r[1], "display_name": r[2], "role": r[3],
            "department": r[4], "is_active": r[5],
            "last_login": r[6].isoformat() if r[6] else None,
            "created_at": r[7].isoformat() if r[7] else None,
        }
        for r in rows
    ]
    return {"users": users, "total": total}


@router.post("/users")
async def invite_user(body: UserInvite, request: Request):
    admin = require_admin(request)
    if not validate_email(body.email):
        raise HTTPException(400, "Invalid email")
    pwd = body.password or "ChangeMe123"
    err = validate_password(pwd)
    if err:
        raise HTTPException(400, err)
    pwd_hash = hash_password(pwd)
    with get_cursor() as cur:
        try:
            cur.execute(
                """INSERT INTO users (email, display_name, role, department, password_hash)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at""",
                (body.email, body.display_name, body.role, body.department, pwd_hash),
            )
            uid, created_at = cur.fetchone()
        except Exception as e:
            raise HTTPException(409, f"Could not create user: {e}")
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) "
            "VALUES (%s, %s, %s, %s, %s)",
            (admin["user_id"], "USER_INVITE", "users", uid, json.dumps({"email": body.email, "role": body.role})),
        )
    return {"id": uid, "created_at": created_at.isoformat(), "temp_password": pwd if not body.password else None}


@router.patch("/users/{user_id}")
async def patch_user(user_id: int, body: UserPatch, request: Request):
    admin = require_admin(request)
    sets, params = [], []
    for field in ("display_name", "role", "department", "is_active"):
        v = getattr(body, field)
        if v is not None:
            sets.append(f"{field} = %s")
            params.append(v)
    if not sets:
        raise HTTPException(400, "No fields to update")
    sets.append("updated_at = NOW()")
    params.append(user_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s RETURNING id", params)
        if not cur.fetchone():
            raise HTTPException(404, "User not found")
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
            (admin["user_id"], "USER_UPDATE", "users", user_id, json.dumps(body.model_dump(exclude_none=True))),
        )
    return {"id": user_id, "updated": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    admin = require_admin(request)
    if user_id == admin["user_id"]:
        raise HTTPException(400, "Cannot delete yourself")
    with get_cursor() as cur:
        cur.execute("UPDATE users SET is_active = FALSE WHERE id = %s RETURNING id", (user_id,))
        if not cur.fetchone():
            raise HTTPException(404, "User not found")
        cur.execute("DELETE FROM auth_tokens WHERE user_id = %s", (user_id,))
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id) VALUES (%s,%s,%s,%s)",
            (admin["user_id"], "USER_DISABLE", "users", user_id),
        )
    return {"id": user_id, "disabled": True}


@router.post("/users/{user_id}/revoke")
async def revoke_tokens(user_id: int, request: Request):
    admin = require_admin(request)
    with get_cursor() as cur:
        cur.execute("DELETE FROM auth_tokens WHERE user_id = %s", (user_id,))
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id) VALUES (%s,%s,%s,%s)",
            (admin["user_id"], "USER_REVOKE_TOKENS", "users", user_id),
        )
    return {"id": user_id, "revoked": True}


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
@router.get("/roles")
async def list_roles(request: Request):
    require_admin(request)
    with get_cursor() as cur:
        cur.execute("SELECT name, label, permissions, is_system, updated_at FROM roles ORDER BY name")
        roles = [
            {
                "name": r[0], "label": r[1], "permissions": r[2],
                "is_system": r[3],
                "updated_at": r[4].isoformat() if r[4] else None,
            }
            for r in cur.fetchall()
        ]
        cur.execute("SELECT key, description, category FROM permissions_catalog ORDER BY category, key")
        perms = [{"key": r[0], "description": r[1], "category": r[2]} for r in cur.fetchall()]
    return {"roles": roles, "permissions": perms}


class RoleCreate(BaseModel):
    name: str
    label: str
    permissions: dict = {}


@router.post("/roles")
async def create_role(body: RoleCreate, request: Request):
    admin = require_admin(request)
    import re as _re
    if not _re.match(r"^[a-z0-9_]+$", body.name):
        raise HTTPException(400, "name must be lowercase alphanumeric/underscore")
    with get_cursor() as cur:
        cur.execute("SELECT 1 FROM roles WHERE name = %s", (body.name,))
        if cur.fetchone():
            raise HTTPException(409, "Role already exists")
        cur.execute(
            "INSERT INTO roles (name, label, permissions, is_system) VALUES (%s,%s,%s,FALSE)",
            (body.name, body.label, json.dumps(body.permissions)),
        )
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, details) VALUES (%s,%s,%s,%s)",
            (admin["user_id"], "ROLE_CREATE", "roles", json.dumps({"name": body.name})),
        )
    return {"name": body.name, "created": True}


@router.delete("/roles/{name}")
async def delete_role(name: str, request: Request):
    admin = require_admin(request)
    with get_cursor() as cur:
        cur.execute("SELECT is_system FROM roles WHERE name = %s", (name,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Role not found")
        if row[0]:
            raise HTTPException(400, "Cannot delete system role")
        cur.execute("SELECT COUNT(*) FROM users WHERE role = %s", (name,))
        in_use = cur.fetchone()[0]
        if in_use:
            raise HTTPException(409, f"Role in use by {in_use} users — reassign first")
        cur.execute("DELETE FROM roles WHERE name = %s", (name,))
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, details) VALUES (%s,%s,%s,%s)",
            (admin["user_id"], "ROLE_DELETE", "roles", json.dumps({"name": name})),
        )
    return {"name": name, "deleted": True}


class RolePut(BaseModel):
    label: Optional[str] = None
    permissions: dict


@router.put("/roles/{name}")
async def update_role(name: str, body: RolePut, request: Request):
    admin = require_admin(request)
    with get_cursor() as cur:
        cur.execute("SELECT is_system FROM roles WHERE name = %s", (name,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Role not found")
        sets = ["permissions = %s", "updated_at = NOW()"]
        params = [json.dumps(body.permissions)]
        if body.label:
            sets.append("label = %s")
            params.append(body.label)
        params.append(name)
        cur.execute(f"UPDATE roles SET {', '.join(sets)} WHERE name = %s", params)
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
            (admin["user_id"], "ROLE_UPDATE", "roles", None, json.dumps({"name": name})),
        )
    return {"name": name, "updated": True}


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------
@router.get("/audit")
async def list_audit(
    request: Request,
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    days: int = Query(30, le=365),
    limit: int = Query(100, le=1000),
    offset: int = 0,
):
    require_admin(request)
    conds = ["a.created_at > NOW() - (%s || ' days')::interval"]
    params = [str(days)]
    if user_id:
        conds.append("a.user_id = %s"); params.append(user_id)
    if action:
        conds.append("a.action = %s"); params.append(action)
    if resource_type:
        conds.append("a.resource_type = %s"); params.append(resource_type)
    where = "WHERE " + " AND ".join(conds)
    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM audit_log a {where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"""SELECT a.id, a.user_id, u.display_name, a.action, a.resource_type,
                       a.resource_id, a.details, a.ip_address, a.created_at
                FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
                {where}
                ORDER BY a.created_at DESC LIMIT %s OFFSET %s""",
            (*params, limit, offset),
        )
        events = [
            {
                "id": r[0], "user_id": r[1], "user_name": r[2],
                "action": r[3], "resource_type": r[4], "resource_id": r[5],
                "details": r[6], "ip_address": r[7],
                "created_at": r[8].isoformat() if r[8] else None,
            }
            for r in cur.fetchall()
        ]
    return {"events": events, "total": total}


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------
@router.get("/insights")
async def insights(request: Request):
    require_admin(request)
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users WHERE is_active = TRUE"); active_users = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM candidates"); n_candidates = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM positions WHERE status = 'active'"); n_positions = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM jd_repository WHERE status = 'active'"); n_jds = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM offers"); n_offers = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM audit_log WHERE created_at > NOW() - interval '24 hours'"); audit_24h = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'LOGIN_FAIL' AND created_at > NOW() - interval '1 hour'"); login_fails = cur.fetchone()[0]

        cur.execute("""SELECT model, COUNT(*) AS calls,
                              SUM(tokens_in) AS toks_in, SUM(tokens_out) AS toks_out,
                              SUM(cost_usd) AS cost
                       FROM ai_usage WHERE created_at > NOW() - interval '24 hours'
                       GROUP BY model""")
        ai_today = [
            {"model": r[0], "calls": r[1], "tokens_in": r[2] or 0, "tokens_out": r[3] or 0, "cost_usd": float(r[4] or 0)}
            for r in cur.fetchall()
        ]
        cur.execute("SELECT COALESCE(SUM(cost_usd),0) FROM ai_usage WHERE created_at > NOW() - interval '7 days'")
        cost_7d = float(cur.fetchone()[0])

    from backend.core.config import is_ai_available
    ai_available = is_ai_available()

    insights_list = []
    if login_fails >= 4:
        insights_list.append({"level": "warn", "msg": f"{login_fails} failed logins in last hour — review IPs"})
    if n_jds == 0:
        insights_list.append({"level": "info", "msg": "No JDs in repository yet"})
    if n_candidates == 0:
        insights_list.append({"level": "info", "msg": "No candidates uploaded — run a CV upload to bootstrap"})
    if not ai_available:
        insights_list.append({"level": "error", "msg": "AI features disabled — set OPENROUTER_API_KEY"})

    return {
        "totals": {
            "active_users": active_users,
            "candidates": n_candidates,
            "positions": n_positions,
            "jds": n_jds,
            "offers": n_offers,
        },
        "activity": {"audit_24h": audit_24h, "login_fails_1h": login_fails},
        "ai": {"today": ai_today, "cost_7d": cost_7d, "available": ai_available},
        "insights": insights_list,
    }


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
@router.get("/system/config")
async def system_config(request: Request):
    require_admin(request)
    with get_cursor() as cur:
        cur.execute("SELECT key, value, description, updated_at FROM system_flags ORDER BY key")
        flags = [
            {"key": r[0], "value": r[1], "description": r[2],
             "updated_at": r[3].isoformat() if r[3] else None}
            for r in cur.fetchall()
        ]
    key = os.getenv("OPENROUTER_API_KEY", "")
    return {
        "flags": flags,
        "secrets": {
            "openrouter_set": bool(key) and not key.startswith("sk-or-v1-your"),
            "openrouter_masked": (key[:10] + "•" * 8 + key[-4:]) if len(key) > 16 else "",
            "smtp_set": bool(os.getenv("SMTP_HOST")),
        },
        "env": {
            "dev_mode": os.getenv("DEV_MODE", "false"),
            "log_format": os.getenv("LOG_FORMAT", "text"),
            "workers": os.getenv("WORKERS", "2"),
        },
    }


class FlagPatch(BaseModel):
    value: object


@router.patch("/system/config/{key}")
async def patch_flag(key: str, body: FlagPatch, request: Request):
    admin = require_admin(request)
    with get_cursor() as cur:
        cur.execute(
            """UPDATE system_flags SET value = %s, updated_at = NOW(), updated_by = %s
               WHERE key = %s RETURNING key""",
            (json.dumps(body.value), admin["user_id"], key),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Flag not found")
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
            (admin["user_id"], "FLAG_UPDATE", "system_flags", None, json.dumps({"key": key, "value": body.value})),
        )
    return {"key": key, "value": body.value}


# ---------------------------------------------------------------------------
# Tenant scoring policy + Sectors + Lock
# ---------------------------------------------------------------------------
@router.get("/scoring-policy")
async def get_scoring_policy(request: Request):
    require_admin(request)
    with get_cursor() as cur:
        cur.execute("SELECT key, value, enforcement FROM tenant_scoring_policy ORDER BY key")
        rows = [{"key": r[0], "value": float(r[1]), "enforcement": r[2]} for r in cur.fetchall()]
    return {"policy": rows}


class PolicyEntry(BaseModel):
    key: str
    value: float
    enforcement: Optional[str] = "clamp"


class PolicyPut(BaseModel):
    entries: list[PolicyEntry]


@router.put("/scoring-policy")
async def put_scoring_policy(body: PolicyPut, request: Request):
    admin = require_admin(request)
    with get_cursor() as cur:
        for e in body.entries:
            cur.execute("""
                INSERT INTO tenant_scoring_policy (key, value, enforcement, updated_at, updated_by)
                VALUES (%s, %s, %s, NOW(), %s)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    enforcement = EXCLUDED.enforcement,
                    updated_at = NOW(),
                    updated_by = EXCLUDED.updated_by
            """, (e.key, e.value, e.enforcement or "clamp", admin["user_id"]))
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, details) VALUES (%s,%s,%s,%s)",
            (admin["user_id"], "TENANT_POLICY_UPDATE", "tenant_scoring_policy",
             json.dumps([e.model_dump() for e in body.entries])),
        )
    return {"updated": len(body.entries)}


@router.get("/sectors")
async def list_sectors(request: Request):
    require_admin(request)
    with get_cursor() as cur:
        cur.execute("""
            SELECT id, name, email_domain, lead_user_id,
                   weight_skills, weight_experience, weight_industry,
                   weight_education, weight_certifications, weight_culture,
                   forced_dims, created_at
            FROM sectors ORDER BY name
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            cur.execute("SELECT COUNT(*) FROM users WHERE sector_id = %s", (r["id"],))
            r["users_count"] = cur.fetchone()[0]
    return {"sectors": rows}


class SectorWeightsPut(BaseModel):
    weight_skills: Optional[float] = None
    weight_experience: Optional[float] = None
    weight_industry: Optional[float] = None
    weight_education: Optional[float] = None
    weight_certifications: Optional[float] = None
    weight_culture: Optional[float] = None
    forced_dims: Optional[list[str]] = None


@router.put("/sectors/{sector_id}/weights")
async def put_sector_weights(sector_id: int, body: SectorWeightsPut, request: Request):
    admin = require_admin(request)
    sets, params = [], []
    for k, v in body.model_dump(exclude_none=True).items():
        if k == "forced_dims":
            sets.append("forced_dims = %s::jsonb"); params.append(json.dumps(v))
        else:
            sets.append(f"{k} = %s"); params.append(v)
    if not sets:
        raise HTTPException(400, "No fields")
    params.append(sector_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE sectors SET {', '.join(sets)} WHERE id = %s RETURNING id", params)
        if not cur.fetchone():
            raise HTTPException(404, "Sector not found")
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
            (admin["user_id"], "SECTOR_WEIGHTS_UPDATE", "sectors", sector_id,
             json.dumps(body.model_dump(exclude_none=True))),
        )
    return {"sector_id": sector_id, "updated": True}


class SectorCreateRequest(BaseModel):
    name: str
    email_domain: Optional[str] = None


@router.post("/sectors")
async def create_sector(body: SectorCreateRequest, request: Request):
    admin = require_admin(request)
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO sectors (name, email_domain) VALUES (%s, %s) RETURNING id",
            (body.name, body.email_domain),
        )
        sid = cur.fetchone()[0]
    return {"id": sid, "name": body.name}


# ---------------------------------------------------------------------------
# Branding (white-label) — single key in app_settings
# ---------------------------------------------------------------------------
import re as _re_brand

_BRAND_DEFAULTS = {
    "app_name": "City Agent Pulse",
    "logo_data_url": "",
    "accent_color": "#c96342",
    "footer_text": "Org Heartbeat",
}
_HEX_COLOR_RE = _re_brand.compile(r"^#[0-9a-fA-F]{6}$")
_LOGO_PREFIX_RE = _re_brand.compile(r"^data:image/(png|jpeg|jpg|svg\+xml|webp|gif);base64,")
_HTTPS_URL_RE = _re_brand.compile(r"^https://[^\s]+$")
_VALID_INTEGRATIONS = {"slack", "teams", "gcal", "outlook", "docusign", "linkedin"}


def _read_branding() -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT value FROM app_settings WHERE key = 'branding'")
        row = cur.fetchone()
    if not row:
        return dict(_BRAND_DEFAULTS)
    val = row[0]
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            val = {}
    merged = dict(_BRAND_DEFAULTS)
    if isinstance(val, dict):
        merged.update({k: v for k, v in val.items() if k in _BRAND_DEFAULTS})
    return merged


@router.get("/branding")
async def get_branding(request: Request):
    # Public read: white-label branding (app name, logo, accent) must be visible
    # on the login page and pre-auth bootstrap, before any token exists.
    # Writes below are admin-gated.
    return _read_branding()


@router.post("/branding")
async def save_branding(body: dict, request: Request):
    admin = require_admin(request)
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")

    accent = str(body.get("accent_color", _BRAND_DEFAULTS["accent_color"]))[:32].strip()
    if not _HEX_COLOR_RE.match(accent):
        raise HTTPException(400, "Accent color must be a 6-digit hex like #c96342")

    logo = str(body.get("logo_data_url", "") or "")
    if logo and not _LOGO_PREFIX_RE.match(logo):
        raise HTTPException(400, "Logo must be a data:image/(png|svg+xml|jpeg|webp|gif);base64,... URL")
    if len(logo) > 500_000:
        raise HTTPException(400, "Logo data URL exceeds 500 KB limit")

    payload = {
        "app_name": str(body.get("app_name", _BRAND_DEFAULTS["app_name"]) or _BRAND_DEFAULTS["app_name"])[:128].strip()
            or _BRAND_DEFAULTS["app_name"],
        "logo_data_url": logo,
        "accent_color": accent,
        "footer_text": str(body.get("footer_text", _BRAND_DEFAULTS["footer_text"]) or "")[:128],
    }

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO app_settings (key, value, updated_by, updated_at)
               VALUES ('branding', %s::jsonb, %s, now())
               ON CONFLICT (key) DO UPDATE
                 SET value = EXCLUDED.value,
                     updated_at = now(),
                     updated_by = EXCLUDED.updated_by""",
            (json.dumps(payload), admin.get("user_id")),
        )
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, details) VALUES (%s,%s,%s,%s)",
            (admin.get("user_id"), "BRANDING_UPDATE", "app_settings",
             json.dumps({"app_name": payload["app_name"], "accent_color": payload["accent_color"]})),
        )
    return payload


# ---------------------------------------------------------------------------
# Integrations (webhooks per provider) — key prefix 'integration:'
# ---------------------------------------------------------------------------
def _integration_key(key: str) -> str:
    k = (key or "").strip().lower()
    if k not in _VALID_INTEGRATIONS:
        raise HTTPException(400, f"Unknown integration. Allowed: {', '.join(sorted(_VALID_INTEGRATIONS))}")
    return k


@router.get("/integrations")
async def list_integrations(request: Request):
    require_admin(request)
    with get_cursor() as cur:
        cur.execute(
            "SELECT key, value, updated_at FROM app_settings WHERE key LIKE 'integration:%'"
        )
        rows = cur.fetchall()
    out: dict = {k: None for k in _VALID_INTEGRATIONS}
    for key, value, updated_at in rows:
        slug = key.split(":", 1)[1] if ":" in key else key
        if slug not in _VALID_INTEGRATIONS:
            continue
        val = value
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                val = {}
        webhook = (val or {}).get("webhook_url", "") if isinstance(val, dict) else ""
        out[slug] = {
            "webhook_url": webhook,
            "configured_at": updated_at.isoformat() if updated_at else None,
        }
    return {"integrations": out}


@router.post("/integrations/{key}")
async def save_integration(key: str, body: dict, request: Request):
    admin = require_admin(request)
    slug = _integration_key(key)
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")
    url = str(body.get("webhook_url", "") or "").strip()
    if not _HTTPS_URL_RE.match(url):
        raise HTTPException(400, "Webhook URL must start with https://")
    if len(url) > 2048:
        raise HTTPException(400, "Webhook URL exceeds 2048 character limit")

    payload = {"webhook_url": url}
    settings_key = f"integration:{slug}"
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO app_settings (key, value, updated_by, updated_at)
               VALUES (%s, %s::jsonb, %s, now())
               ON CONFLICT (key) DO UPDATE
                 SET value = EXCLUDED.value,
                     updated_at = now(),
                     updated_by = EXCLUDED.updated_by
               RETURNING updated_at""",
            (settings_key, json.dumps(payload), admin.get("user_id")),
        )
        updated_at = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) VALUES (%s,%s,%s,%s,%s)",
            (admin.get("user_id"), "INTEGRATION_SAVE", "app_settings", None,
             json.dumps({"key": settings_key})),
        )
    return {
        "key": slug,
        "webhook_url": url,
        "configured_at": updated_at.isoformat() if updated_at else None,
    }


@router.delete("/integrations/{key}")
async def delete_integration(key: str, request: Request):
    admin = require_admin(request)
    slug = _integration_key(key)
    settings_key = f"integration:{slug}"
    with get_cursor() as cur:
        cur.execute("DELETE FROM app_settings WHERE key = %s RETURNING key", (settings_key,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Integration not configured")
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, details) VALUES (%s,%s,%s,%s)",
            (admin.get("user_id"), "INTEGRATION_DELETE", "app_settings",
             json.dumps({"key": settings_key})),
        )
    return {"key": slug, "deleted": True}


# ---------------------------------------------------------------------------
# Retention defaults (mig 056) — recruiter+ writable, public-ish read.
# Drives expires_at stamping on new candidates + JDs.
# ---------------------------------------------------------------------------
def _require_recruiter_plus(request: Request) -> dict:
    user = get_current_user(request)
    if user.get("role") not in ("recruiter", "hiring_manager", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Recruiter role or higher required")
    return user


@router.get("/retention")
async def get_retention(request: Request):
    """Return current retention/expiry defaults {cv_days, jd_days}."""
    _require_recruiter_plus(request)
    from backend.core.expiry import get_retention_settings
    return get_retention_settings()


@router.post("/retention")
async def save_retention(body: dict, request: Request):
    """Update retention defaults. Affects rows created AFTER this change only."""
    user = _require_recruiter_plus(request)
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")
    try:
        cv_days = int(body.get("cv_days", 90) or 90)
        jd_days = int(body.get("jd_days", 90) or 90)
    except (TypeError, ValueError):
        raise HTTPException(400, "cv_days and jd_days must be integers")
    if cv_days < 1 or jd_days < 1 or cv_days > 3650 or jd_days > 3650:
        raise HTTPException(400, "Days must be between 1 and 3650")
    from backend.core.expiry import set_retention_settings
    payload = set_retention_settings(cv_days, jd_days, user.get("user_id"))
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (user_id, action, resource_type, details) VALUES (%s,%s,%s,%s)",
            (user.get("user_id"), "RETENTION_UPDATE", "app_settings", json.dumps(payload)),
        )
    return payload
