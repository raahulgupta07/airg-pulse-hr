"""Dual-ID resolver: int (internal) <-> public_id (external).

Public IDs: <prefix>_<ULID26>  e.g. cv_01HQ9X2K8M3F...
Internal IDs: BIGSERIAL int (joins, FKs).
"""
from __future__ import annotations
import secrets
import time
from typing import Optional, Union

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

TABLE_PREFIX = {
    "candidates": "cv",
    "jd_repository": "jd",
    "positions": "pos",
    "users": "usr",
    "sectors": "sec",
}
PREFIX_TABLE = {v: k for k, v in TABLE_PREFIX.items()}


def gen_ulid() -> str:
    """26-char Crockford base32 ULID (10 ts + 16 random)."""
    ts_ms = int(time.time() * 1000)
    rand = secrets.token_bytes(10)
    out = []
    for i in range(10):
        out.append(ALPHABET[(ts_ms >> ((9 - i) * 5)) & 0x1F])
    bits = int.from_bytes(rand, "big")
    for i in range(16):
        out.append(ALPHABET[(bits >> ((15 - i) * 5)) & 0x1F])
    return "".join(out)


def gen_public_id(table: str) -> str:
    prefix = TABLE_PREFIX.get(table)
    if not prefix:
        raise ValueError(f"no prefix for table {table}")
    return f"{prefix}_{gen_ulid()}"


def is_public_id(ref: Union[str, int]) -> bool:
    if isinstance(ref, int):
        return False
    s = str(ref)
    return "_" in s and s.split("_", 1)[0] in PREFIX_TABLE


async def resolve_id(db, table: str, ref: Union[str, int]) -> Optional[int]:
    """Resolve int id from either int or public_id string.

    db: asyncpg connection/pool exposing `.fetchval`.
    Returns int id or None if not found.
    """
    if ref is None:
        return None
    if isinstance(ref, int):
        return ref
    s = str(ref).strip()
    if s.isdigit():
        return int(s)
    if is_public_id(s):
        expected_prefix = TABLE_PREFIX[table]
        if not s.startswith(expected_prefix + "_"):
            return None
        row = await db.fetchval(f"SELECT id FROM {table} WHERE public_id = $1", s)
        return row
    return None


def resolve_id_sync(table: str, ref: Union[str, int, None]) -> Optional[int]:
    """Sync variant of resolve_id for psycopg-based routes.

    Accepts int OR str (digits OR public_id like ``cv_...``). Returns int id or None.
    Uses ``backend.core.database.get_cursor()`` for the lookup when a public_id is given.
    """
    if ref is None:
        return None
    if isinstance(ref, int):
        return ref
    s = str(ref).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if not is_public_id(s):
        return None
    expected_prefix = TABLE_PREFIX.get(table)
    if not expected_prefix or not s.startswith(expected_prefix + "_"):
        return None
    try:
        from backend.core.database import get_cursor
        with get_cursor() as cur:
            cur.execute(f"SELECT id FROM {table} WHERE public_id = %s", (s,))
            row = cur.fetchone()
            return int(row[0]) if row else None
    except Exception:
        return None


def to_public(rec: dict) -> dict:
    """Replace int `id` with `public_id` in output dict (keeps int as `_internal_id` if needed)."""
    if rec and "public_id" in rec:
        rec["id"] = rec["public_id"]
    return rec
