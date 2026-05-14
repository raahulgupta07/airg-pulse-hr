"""Centralised RBAC helpers — role hierarchy + FastAPI dep factories.

Hierarchy (high → low):
    superadmin > admin > group_hr > recruiter > hiring_manager > viewer
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request

from backend.core.auth import get_current_user

logger = logging.getLogger(__name__)

ROLE_RANK = {
    "viewer": 0,
    "hiring_manager": 1,
    "recruiter": 2,
    "group_hr": 3,
    "admin": 4,
    "superadmin": 5,
}


def _role(user: dict) -> str:
    return (user.get("role") or "viewer") if isinstance(user, dict) else "viewer"


def _uid(user: dict) -> Any:
    if not isinstance(user, dict):
        return None
    return user.get("id") or user.get("user_id")


def has_min_role(user: dict, min_role: str) -> bool:
    return ROLE_RANK.get(_role(user), 0) >= ROLE_RANK.get(min_role, 99)


def is_owner_or_min(user: dict, owner_id: Any, min_role: str) -> bool:
    uid = _uid(user)
    try:
        if uid is not None and owner_id is not None and int(uid) == int(owner_id):
            return True
    except (TypeError, ValueError):
        if uid == owner_id:
            return True
    return has_min_role(user, min_role)


def _log_denied(user: dict, request: Request | None, min_role: str) -> None:
    try:
        path = request.url.path if request is not None else "?"
    except Exception:
        path = "?"
    logger.warning(
        "rbac_denied user_id=%s role=%s path=%s requires=%s",
        _uid(user), _role(user), path, min_role,
    )


def require_role(min_role: str):
    """FastAPI dependency factory — 403 if user below `min_role`."""
    def dep(request: Request, user: dict = Depends(get_current_user)) -> dict:
        if not has_min_role(user, min_role):
            _log_denied(user, request, min_role)
            raise HTTPException(status_code=403, detail=f"requires {min_role}+")
        return user
    return dep


def ensure_owner_or_min(user: dict, owner_id: Any, min_role: str, request: Request | None = None) -> None:
    """Imperative guard — call inside route body for owner-or-admin checks."""
    if not is_owner_or_min(user, owner_id, min_role):
        _log_denied(user, request, f"owner-or-{min_role}")
        raise HTTPException(status_code=403, detail=f"requires owner or {min_role}+")
