"""GDPR — per-user data export and right-to-erasure endpoints.

Mounted under /api/users. Admin/superadmin only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from backend.core.auth import get_current_user
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def _rows_to_dicts(cur) -> list[dict]:
    cols = [c.name for c in cur.description]
    out = []
    for row in cur.fetchall():
        d = {}
        for k, v in zip(cols, row):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            else:
                d[k] = v
        out.append(d)
    return out


@router.get("/{user_id}/gdpr-export")
async def gdpr_export(user_id: int, request: Request):
    """Export every PII record we hold for a user as a JSON download."""
    admin = _require_admin(request)
    out: dict = {
        "export_date": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "exported_by": admin.get("user_id"),
        "data": {},
    }
    with get_cursor() as cur:
        # Core user record (PII fields only)
        cur.execute(
            """SELECT id, email, operator_id, display_name, role, department,
                      avatar_url, sector_id, is_active, created_at, updated_at,
                      last_login, last_login_at
               FROM users WHERE id = %s""",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        out["data"]["user"] = {
            "id": row[0], "email": row[1], "operator_id": row[2],
            "display_name": row[3], "role": row[4], "department": row[5],
            "avatar_url": row[6], "sector_id": row[7], "is_active": row[8],
            "created_at": row[9].isoformat() if row[9] else None,
            "updated_at": row[10].isoformat() if row[10] else None,
            "last_login": row[11].isoformat() if row[11] else None,
            "last_login_at": row[12].isoformat() if row[12] else None,
        }

        # Candidates this user owns
        try:
            cur.execute(
                "SELECT id, name, email, phone, location, current_role, "
                "current_company, created_at FROM candidates WHERE owner_id = %s",
                (user_id,),
            )
            out["data"]["candidates"] = _rows_to_dicts(cur)
        except Exception as e:
            logger.warning(f"[gdpr-export] candidates failed: {e}")
            out["data"]["candidates"] = []

        # Notifications addressed to this user
        try:
            cur.execute(
                "SELECT id, type, title, message, link, is_read, created_at "
                "FROM notifications WHERE user_id = %s",
                (user_id,),
            )
            out["data"]["notifications"] = _rows_to_dicts(cur)
        except Exception as e:
            logger.warning(f"[gdpr-export] notifications failed: {e}")
            out["data"]["notifications"] = []

        # Positions this user manages
        try:
            cur.execute(
                "SELECT id, slug, title, department, location, status, created_at "
                "FROM positions WHERE hiring_manager_id = %s",
                (user_id,),
            )
            out["data"]["positions"] = _rows_to_dicts(cur)
        except Exception as e:
            logger.warning(f"[gdpr-export] positions failed: {e}")
            out["data"]["positions"] = []

        # Audit-log rows attributed to this user
        try:
            cur.execute(
                "SELECT id, action, resource_type, resource_id, details, created_at "
                "FROM audit_log WHERE user_id = %s ORDER BY created_at DESC LIMIT 1000",
                (user_id,),
            )
            out["data"]["audit_log"] = _rows_to_dicts(cur)
        except Exception as e:
            logger.warning(f"[gdpr-export] audit_log failed: {e}")
            out["data"]["audit_log"] = []

        # Notes / activity authored by this user (best-effort)
        try:
            cur.execute(
                "SELECT id, candidate_id, body, created_at "
                "FROM candidate_notes WHERE created_by = %s",
                (user_id,),
            )
            out["data"]["candidate_notes"] = _rows_to_dicts(cur)
        except Exception as e:
            logger.warning(f"[gdpr-export] candidate_notes failed: {e}")
            out["data"]["candidate_notes"] = []

        # Audit log the export itself
        try:
            cur.execute(
                "INSERT INTO audit_log (user_id, action, resource_type, resource_id) "
                "VALUES (%s, %s, %s, %s)",
                (admin.get("user_id"), "GDPR_EXPORT", "users", user_id),
            )
        except Exception:
            pass

    return out


@router.delete("/{user_id}")
async def delete_user_with_optional_gdpr(
    user_id: int,
    request: Request,
    gdpr: bool = False,
):
    """Delete a user. With ?gdpr=true, scrubs PII fields in addition to soft-delete.

    Default (gdpr=false) preserves the existing soft-delete behaviour
    (sets is_active=false, revokes tokens). gdpr=true additionally rewrites
    email / operator_id / display_name / avatar_url / department to anonymous
    placeholders and clears related PII (candidate notes body kept by reference
    as authored by deleted user).
    """
    admin = _require_admin(request)
    if user_id == admin.get("user_id"):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    scrubbed_at = datetime.now(timezone.utc).isoformat()
    with get_cursor() as cur:
        # Confirm user exists
        cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="User not found")

        if not gdpr:
            # Existing soft-delete path (parity with /api/admin/users/{id} DELETE)
            cur.execute(
                "UPDATE users SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
                (user_id,),
            )
            try:
                cur.execute("DELETE FROM auth_tokens WHERE user_id = %s", (user_id,))
            except Exception:
                pass
            try:
                cur.execute(
                    "INSERT INTO audit_log (user_id, action, resource_type, resource_id) "
                    "VALUES (%s, %s, %s, %s)",
                    (admin.get("user_id"), "USER_DISABLE", "users", user_id),
                )
            except Exception:
                pass
            return {"ok": True, "user_id": user_id, "disabled": True}

        # GDPR scrub — overwrite PII columns with anonymised stand-ins
        anon_email = f"deleted-{user_id}@example.invalid"
        anon_op_id = f"deleted-{user_id}"
        try:
            cur.execute(
                """UPDATE users
                   SET email = %s,
                       operator_id = %s,
                       display_name = %s,
                       avatar_url = NULL,
                       department = NULL,
                       password_hash = NULL,
                       pass_hash = NULL,
                       is_active = FALSE,
                       updated_at = NOW()
                   WHERE id = %s""",
                (anon_email, anon_op_id, "[deleted]", user_id),
            )
        except Exception as e:
            logger.error(f"[gdpr-delete] users scrub failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to scrub user record")

        # Revoke any active tokens
        try:
            cur.execute("DELETE FROM auth_tokens WHERE user_id = %s", (user_id,))
        except Exception:
            pass

        # Scrub notifications addressed to this user (delete outright — they
        # carry copies of titles/messages that may include PII references).
        try:
            cur.execute("DELETE FROM notifications WHERE user_id = %s", (user_id,))
        except Exception as e:
            logger.warning(f"[gdpr-delete] notifications scrub failed: {e}")

        # Audit log the GDPR action
        try:
            cur.execute(
                "INSERT INTO audit_log (user_id, action, resource_type, resource_id, details) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (admin.get("user_id"), "GDPR_DELETE", "users", user_id,
                 '{"scrubbed_at": "' + scrubbed_at + '"}'),
            )
        except Exception:
            pass

    return {
        "ok": True,
        "user_id": user_id,
        "gdpr": True,
        "scrubbed_at": scrubbed_at,
    }
