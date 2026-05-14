"""Brain provider — wraps HR Brain learnings (query + write).

update_brain requires role allowlist (enforced in hr_agent.py — recruiter blocked).
"""
from __future__ import annotations

import logging

from backend.core.database import (
    get_brain_entries,
    get_feedback_patterns,
    get_cursor,
)

logger = logging.getLogger(__name__)


def query_brain(
    topic: str = None,
    position_id: int = None,
    limit: int = 20,
) -> list[dict]:
    """Query HR Brain knowledge entries.

    Wraps get_brain_entries; applies optional case-insensitive topic filter
    against category / key / value, then trims to `limit`.
    """
    rows = get_brain_entries(category=None, position_id=position_id)

    if topic:
        needle = topic.lower()
        rows = [
            r for r in rows
            if needle in (r.get("category") or "").lower()
            or needle in (r.get("key") or "").lower()
            or needle in (r.get("value") or "").lower()
        ]

    out = []
    for r in rows[:limit]:
        out.append({
            "id": r.get("id"),
            "category": r.get("category"),
            "key": r.get("key"),
            "value": r.get("value"),
            # hr_brain has no confidence column — synthesize from source.
            "confidence": 1.0 if r.get("source") == "admin" else 0.7,
            "source": r.get("source"),
        })
    return out


def get_feedback_do_avoid(position_id: int = None) -> dict:
    """Return DO/AVOID patterns from hr_brain_learnings for agent injection."""
    return get_feedback_patterns(position_id=position_id)


def update_brain(
    category: str,
    key: str,
    value: str,
    source: str = "agent",
    confidence: float = 0.7,
    position_id: int = None,
    tenant_id: int = None,  # accepted for future multi-tenant; unused (no column)
) -> dict:
    """Upsert an HR Brain entry.

    Looks for an existing (category, key, position_id) row; updates value+source
    if found, otherwise inserts. Returns {id, status: 'created'|'updated'}.

    Note: confidence and tenant_id are accepted but the hr_brain table does not
    persist them — they're tracked in metadata-free form for now.
    """
    with get_cursor() as cur:
        # Match scope: position-specific or global (NULL position_id).
        if position_id is None:
            cur.execute(
                "SELECT id FROM hr_brain "
                "WHERE category = %s AND key = %s AND position_id IS NULL "
                "LIMIT 1",
                (category, key),
            )
        else:
            cur.execute(
                "SELECT id FROM hr_brain "
                "WHERE category = %s AND key = %s AND position_id = %s "
                "LIMIT 1",
                (category, key, position_id),
            )
        existing = cur.fetchone()

        if existing:
            entry_id = existing[0]
            cur.execute(
                "UPDATE hr_brain "
                "SET value = %s, source = %s, updated_at = NOW() "
                "WHERE id = %s",
                (value, source, entry_id),
            )
            return {"id": entry_id, "status": "updated"}

        cur.execute(
            "INSERT INTO hr_brain (category, key, value, source, position_id) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (category, key, value, source, position_id),
        )
        new_id = cur.fetchone()[0]
        return {"id": new_id, "status": "created"}
