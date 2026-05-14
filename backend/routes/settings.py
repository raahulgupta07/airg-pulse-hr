"""Settings API — superadmin-only CRUD over the persistent settings table.

All endpoints require Bearer token + role=superadmin. Values are arbitrary
JSON, stored in JSONB. See backend/core/settings.py for the storage layer.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.core.auth import require_role
from backend.core.settings import (
    delete_setting,
    get_setting,
    list_settings,
    set_setting,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SettingPut(BaseModel):
    value: Any
    scope: Optional[str] = "global"
    description: Optional[str] = ""


@router.get("")
@router.get("/")
async def list_all(
    scope: Optional[str] = Query(None, description="Filter by scope"),
    user=Depends(require_role("superadmin")),
):
    return {"settings": list_settings(scope=scope)}


@router.get("/{key}")
async def get_one(key: str, user=Depends(require_role("superadmin"))):
    sentinel = object()
    value = get_setting(key, default=sentinel)
    if value is sentinel:
        raise HTTPException(status_code=404, detail="setting_not_found")
    return {"key": key, "value": value}


@router.put("/{key}")
async def put_one(
    key: str,
    body: SettingPut,
    user=Depends(require_role("superadmin")),
):
    set_setting(
        key,
        body.value,
        scope=body.scope or "global",
        description=body.description or "",
    )
    logger.info(f"[settings] {user.get('user_id')} updated {key}")
    return {"key": key, "value": body.value, "scope": body.scope or "global"}


@router.delete("/{key}")
async def delete_one(key: str, user=Depends(require_role("superadmin"))):
    delete_setting(key)
    logger.info(f"[settings] {user.get('user_id')} deleted {key}")
    return {"deleted": key}
