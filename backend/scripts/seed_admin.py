"""Seed a default admin user if no users exist.

Usage:
    python -m backend.scripts.seed_admin

Idempotent — no-op when any user row already exists.
"""
from __future__ import annotations

import logging
import sys

from backend.core.database import get_cursor
from backend.auth import hash_password

logger = logging.getLogger(__name__)

DEFAULT_EMAIL = "admin@pulse.local"
DEFAULT_PASSWORD = "admin123"
DEFAULT_NAME = "Admin"
DEFAULT_ROLE = "admin"


def seed_admin() -> int:
    """Insert default admin if users table is empty. Returns id (or 0 if skipped)."""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]
    if count and count > 0:
        print(f"seed_admin: skipped — {count} user(s) already exist")
        return 0

    pw_hash = hash_password(DEFAULT_PASSWORD)
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO users (email, display_name, password_hash, role, is_active) "
            "VALUES (%s, %s, %s, %s, TRUE) RETURNING id",
            (DEFAULT_EMAIL, DEFAULT_NAME, pw_hash, DEFAULT_ROLE),
        )
        uid = cur.fetchone()[0]
    print(
        f"seed_admin: created user id={uid} email={DEFAULT_EMAIL} "
        f"password={DEFAULT_PASSWORD!r} — CHANGE THIS IMMEDIATELY"
    )
    return uid


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        seed_admin()
    except Exception as exc:
        print(f"seed_admin: FAILED — {exc}", file=sys.stderr)
        sys.exit(1)
