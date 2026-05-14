"""Email + Offer template CRUD.

Two routers exported:
  - email_router  → mounted at /api/email-templates
  - offer_router  → mounted at /api/offer-templates

All endpoints require recruiter+ role. JSON in/out. DELETE returns 204.
The offer template accepts both `name` and `title` in payloads (frontend
historically used `title`); responses include both keys for compatibility.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.core.auth import get_current_user
from backend.core.database import get_cursor
from backend.core.permissions import require_role

logger = logging.getLogger(__name__)

MAX_NAME = 128
MAX_BODY = 50 * 1024  # 50KB
MAX_SUBJECT = 998     # RFC 5322 line limit


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------
class EmailTemplateIn(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None


class OfferTemplateIn(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None  # frontend alias
    body: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validate_name(name: Optional[str], required: bool = True) -> Optional[str]:
    if name is None:
        if required:
            raise HTTPException(400, "name is required")
        return None
    n = name.strip()
    if not n:
        if required:
            raise HTTPException(400, "name must be non-empty")
        return None
    if len(n) > MAX_NAME:
        raise HTTPException(400, f"name too long (max {MAX_NAME} chars)")
    return n


def _validate_body(body: Optional[str]) -> Optional[str]:
    if body is None:
        return None
    if len(body) > MAX_BODY:
        raise HTTPException(400, f"body too large (max {MAX_BODY} bytes)")
    return body


def _validate_subject(subject: Optional[str]) -> Optional[str]:
    if subject is None:
        return None
    if len(subject) > MAX_SUBJECT:
        raise HTTPException(400, f"subject too long (max {MAX_SUBJECT} chars)")
    return subject


def _row_to_dict(cur, row) -> dict:
    if not row:
        return {}
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _email_serialize(d: dict) -> dict:
    return {
        "id": d.get("id"),
        "name": d.get("name") or "",
        "subject": d.get("subject") or "",
        "body": d.get("body") or "",
        "created_by": d.get("created_by"),
        "created_at": d.get("created_at").isoformat() if d.get("created_at") else None,
        "updated_at": d.get("updated_at").isoformat() if d.get("updated_at") else None,
    }


def _offer_serialize(d: dict) -> dict:
    name = d.get("name") or ""
    return {
        "id": d.get("id"),
        "name": name,
        "title": name,  # alias for frontend
        "body": d.get("body") or "",
        "variables": d.get("variables") or {},
        "created_by": d.get("created_by"),
        "created_at": d.get("created_at").isoformat() if d.get("created_at") else None,
        "updated_at": d.get("updated_at").isoformat() if d.get("updated_at") else None,
    }


# ---------------------------------------------------------------------------
# Email router
# ---------------------------------------------------------------------------
email_router = APIRouter()

EMAIL_COLS = "id, name, subject, body, created_by, created_at, updated_at"


@email_router.get("", dependencies=[Depends(require_role("recruiter"))])
@email_router.get("/", dependencies=[Depends(require_role("recruiter"))])
async def list_email_templates(request: Request):
    with get_cursor() as cur:
        cur.execute(f"SELECT {EMAIL_COLS} FROM email_templates ORDER BY id ASC")
        rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    return [_email_serialize(r) for r in rows]


@email_router.post("", dependencies=[Depends(require_role("recruiter"))])
@email_router.post("/", dependencies=[Depends(require_role("recruiter"))])
async def create_email_template(
    body: EmailTemplateIn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    name = _validate_name(body.name, required=True)
    subject = _validate_subject(body.subject)
    body_text = _validate_body(body.body)
    with get_cursor() as cur:
        cur.execute(
            f"INSERT INTO email_templates (name, subject, body, created_by) "
            f"VALUES (%s, %s, %s, %s) RETURNING {EMAIL_COLS}",
            (name, subject, body_text, user.get("id")),
        )
        row = _row_to_dict(cur, cur.fetchone())
    logger.info(f"email_template.created id={row.get('id')} by={user.get('id')}")
    return _email_serialize(row)


@email_router.put("/{tid}", dependencies=[Depends(require_role("recruiter"))])
async def update_email_template(
    tid: int,
    body: EmailTemplateIn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    sets: list[str] = []
    vals: list = []
    if body.name is not None:
        name = _validate_name(body.name, required=True)
        sets.append("name = %s"); vals.append(name)
    if body.subject is not None:
        sets.append("subject = %s"); vals.append(_validate_subject(body.subject))
    if body.body is not None:
        sets.append("body = %s"); vals.append(_validate_body(body.body))
    if not sets:
        raise HTTPException(400, "no fields to update")
    sets.append("updated_at = NOW()")
    vals.append(tid)
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE email_templates SET {', '.join(sets)} WHERE id = %s "
            f"RETURNING {EMAIL_COLS}",
            tuple(vals),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "email template not found")
        out = _row_to_dict(cur, row)
    return _email_serialize(out)


@email_router.delete("/{tid}", status_code=204, dependencies=[Depends(require_role("recruiter"))])
async def delete_email_template(
    tid: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    with get_cursor() as cur:
        cur.execute("DELETE FROM email_templates WHERE id = %s RETURNING id", (tid,))
        if not cur.fetchone():
            raise HTTPException(404, "email template not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Offer router
# ---------------------------------------------------------------------------
offer_router = APIRouter()

OFFER_COLS = "id, name, body, variables, created_by, created_at, updated_at"


@offer_router.get("", dependencies=[Depends(require_role("recruiter"))])
@offer_router.get("/", dependencies=[Depends(require_role("recruiter"))])
async def list_offer_templates(request: Request):
    with get_cursor() as cur:
        cur.execute(f"SELECT {OFFER_COLS} FROM offer_templates ORDER BY id ASC")
        rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    return [_offer_serialize(r) for r in rows]


@offer_router.post("", dependencies=[Depends(require_role("recruiter"))])
@offer_router.post("/", dependencies=[Depends(require_role("recruiter"))])
async def create_offer_template(
    body: OfferTemplateIn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    # Accept either `name` or `title`
    raw_name = body.name if body.name is not None else body.title
    name = _validate_name(raw_name, required=True)
    body_text = _validate_body(body.body)
    with get_cursor() as cur:
        cur.execute(
            f"INSERT INTO offer_templates (name, body, created_by) "
            f"VALUES (%s, %s, %s) RETURNING {OFFER_COLS}",
            (name, body_text, user.get("id")),
        )
        row = _row_to_dict(cur, cur.fetchone())
    logger.info(f"offer_template.created id={row.get('id')} by={user.get('id')}")
    return _offer_serialize(row)


@offer_router.put("/{tid}", dependencies=[Depends(require_role("recruiter"))])
async def update_offer_template(
    tid: int,
    body: OfferTemplateIn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    sets: list[str] = []
    vals: list = []
    raw_name = body.name if body.name is not None else body.title
    if raw_name is not None:
        name = _validate_name(raw_name, required=True)
        sets.append("name = %s"); vals.append(name)
    if body.body is not None:
        sets.append("body = %s"); vals.append(_validate_body(body.body))
    if not sets:
        raise HTTPException(400, "no fields to update")
    sets.append("updated_at = NOW()")
    vals.append(tid)
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE offer_templates SET {', '.join(sets)} WHERE id = %s "
            f"RETURNING {OFFER_COLS}",
            tuple(vals),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "offer template not found")
        out = _row_to_dict(cur, row)
    return _offer_serialize(out)


@offer_router.delete("/{tid}", status_code=204, dependencies=[Depends(require_role("recruiter"))])
async def delete_offer_template(
    tid: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    with get_cursor() as cur:
        cur.execute("DELETE FROM offer_templates WHERE id = %s RETURNING id", (tid,))
        if not cur.fetchone():
            raise HTTPException(404, "offer template not found")
    return Response(status_code=204)
