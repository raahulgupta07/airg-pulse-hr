"""Automation rules — workflow builder CRUD.

Frontend (`WorkflowsPanel.svelte`) payload shape:
  {
    name,
    trigger:   'cv_uploaded' | 'stage_changed' | 'sla_breach' | ...,
    condition: { field, op, value } | null,
    action:    { type, payload },
    enabled:   bool
  }

Persisted on `automation_rules` table (mig 048 — additive: new columns
`trigger`, `condition`, `action`, `enabled` coexist with the legacy
`trigger_event`/`conditions`/`action_type`/`action_config`/`is_active`
columns from the older rule-engine).

All routes admin/superadmin only. Routes are declared WITHOUT trailing
slash (FastAPI strict-routing).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.auth import get_current_user, require_role
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class RuleIn(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    trigger: str = Field(..., max_length=80)
    condition: Optional[dict] = None
    action: dict
    enabled: bool = True


class RulePatch(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    trigger: Optional[str] = Field(None, max_length=80)
    condition: Optional[dict] = None
    action: Optional[dict] = None
    enabled: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_rule(row, cols) -> dict:
    d = dict(zip(cols, row))
    # Coerce JSONB columns into native dict/None.
    for k in ("condition", "action"):
        v = d.get(k)
        if isinstance(v, str):
            try:
                d[k] = json.loads(v)
            except Exception:
                d[k] = None
    # Frontend expects ISO string for created_at.
    if d.get("created_at") is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("")
async def list_rules(request: Request):
    """List all automation rules (admin/superadmin)."""
    user = get_current_user(request)
    if user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, trigger, condition, action, enabled,
                   created_by, created_at
              FROM automation_rules
             ORDER BY created_at DESC NULLS LAST, id DESC
            """
        )
        cols = [d[0] for d in cur.description]
        rules = [_row_to_rule(r, cols) for r in cur.fetchall()]
    return {"rules": rules}


@router.post("", dependencies=[Depends(require_role("admin", "superadmin"))])
async def create_rule(request: Request, body: RuleIn):
    """Create a workflow rule."""
    user = get_current_user(request)

    if not isinstance(body.action, dict) or not body.action.get("type"):
        raise HTTPException(status_code=400, detail="Action type is required")
    if not body.trigger.strip():
        raise HTTPException(status_code=400, detail="Trigger is required")

    name = (body.name or "").strip() or f"{body.trigger} rule"

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO automation_rules
                (name, trigger, condition, action, enabled, created_by,
                 trigger_event, action_type, conditions, action_config, is_active)
            VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s,
                    %s, %s, %s::jsonb, %s::jsonb, %s)
            RETURNING id, name, trigger, condition, action, enabled,
                      created_by, created_at
            """,
            (
                name,
                body.trigger,
                json.dumps(body.condition) if body.condition is not None else None,
                json.dumps(body.action),
                bool(body.enabled),
                user.get("user_id") or None,
                # Mirror into legacy cols so older NOT-NULL constraints + the
                # legacy rule-engine keep working.
                body.trigger,
                str(body.action.get("type") or "noop"),
                json.dumps(body.condition or {}),
                json.dumps(body.action or {}),
                bool(body.enabled),
            ),
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
    return _row_to_rule(row, cols)


@router.put("/{rule_id}", dependencies=[Depends(require_role("admin", "superadmin"))])
async def update_rule(rule_id: int, request: Request, body: RulePatch):
    """Update fields on a rule (any subset)."""
    get_current_user(request)

    sets: list[str] = []
    params: list = []

    if body.name is not None:
        sets.append("name = %s")
        params.append(body.name.strip())
    if body.trigger is not None:
        sets.append("trigger = %s")
        params.append(body.trigger)
        sets.append("trigger_event = %s")
        params.append(body.trigger)
    if body.condition is not None:
        sets.append("condition = %s::jsonb")
        params.append(json.dumps(body.condition))
        sets.append("conditions = %s::jsonb")
        params.append(json.dumps(body.condition))
    if body.action is not None:
        sets.append("action = %s::jsonb")
        params.append(json.dumps(body.action))
        sets.append("action_type = %s")
        params.append(str(body.action.get("type") or "noop"))
        sets.append("action_config = %s::jsonb")
        params.append(json.dumps(body.action))
    if body.enabled is not None:
        sets.append("enabled = %s")
        params.append(bool(body.enabled))
        sets.append("is_active = %s")
        params.append(bool(body.enabled))

    if not sets:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(rule_id)
    with get_cursor() as cur:
        cur.execute(
            f"""
            UPDATE automation_rules SET {", ".join(sets)}
             WHERE id = %s
         RETURNING id, name, trigger, condition, action, enabled,
                   created_by, created_at
            """,
            params,
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return _row_to_rule(row, cols)


@router.delete(
    "/{rule_id}",
    status_code=204,
    dependencies=[Depends(require_role("admin", "superadmin"))],
)
async def delete_rule(rule_id: int, request: Request):
    """Hard-delete a rule."""
    get_current_user(request)
    with get_cursor() as cur:
        cur.execute("DELETE FROM automation_rules WHERE id = %s RETURNING id", (rule_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return None
