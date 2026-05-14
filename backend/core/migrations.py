"""Versioned SQL migrations using PostgreSQL.

Conventions
-----------
* File naming: ``NNN_short_name.sql`` (zero-padded 3-digit prefix, sorted lexicographically).
* Files live in ``db/migrations/`` and are loaded in sorted order at app startup.
* **Additive-only rule**: do NOT write ``DROP COLUMN``, ``DROP TABLE``,
  ``RENAME COLUMN``, ``ALTER COLUMN ... TYPE``, or ``TRUNCATE`` in a migration.
  Schema changes that drop / mutate existing data put production data at risk
  and are blocked by the safety guard below.
  Prefer: add a new column, dual-write, backfill, then deprecate in a later
  release window.
* Hashes (sha256 of file contents) are recorded in ``_migrations``; if a file
  is edited after being applied, drift is logged (WARNING) but NOT re-applied.
* A pg advisory lock (id 13371337) serializes concurrent runners (e.g. multiple
  ECS tasks booting at once).

Override (use with extreme caution)
-----------------------------------
Set ``ALLOW_DESTRUCTIVE_MIGRATIONS=1`` to bypass the safety guard. A loud
WARNING is logged and the override is recorded in ``_migrations.notes``.
Procedure for safe overrides:
  1. Take a fresh ``pg_dump`` backup.
  2. Announce / coordinate with team.
  3. Deploy with the env var set, monitor, then unset on next deploy.
"""
from __future__ import annotations

import os
import re
import hashlib
import logging
from pathlib import Path
from backend.core.database import get_conn

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "db" / "migrations"
ADVISORY_LOCK_KEY = 13371337

# Destructive patterns (case-insensitive). DROP TABLE handled separately.
_FORBIDDEN_PATTERNS = [
    ("DROP COLUMN", re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE)),
    ("RENAME COLUMN", re.compile(r"\bRENAME\s+COLUMN\b", re.IGNORECASE)),
    ("ALTER COLUMN ... TYPE", re.compile(r"\bALTER\s+COLUMN\b[^;]*\bTYPE\b", re.IGNORECASE)),
    ("TRUNCATE", re.compile(r"\bTRUNCATE\b", re.IGNORECASE)),
]
_DROP_TABLE_RE = re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE)
_DROP_TABLE_IF_EXISTS_RE = re.compile(r"\bDROP\s+TABLE\s+IF\s+EXISTS\b", re.IGNORECASE)
_CREATE_TABLE_RE = re.compile(r"\bCREATE\s+TABLE\b", re.IGNORECASE)


def _scan_destructive(name: str, sql: str) -> list[str]:
    """Return a list of matched destructive patterns in this file (empty = safe)."""
    matches: list[str] = []
    for label, pat in _FORBIDDEN_PATTERNS:
        if pat.search(sql):
            matches.append(label)
    # DROP TABLE handling: allow `DROP TABLE IF EXISTS` paired with `CREATE TABLE`
    # in the same file (idempotent rebuild). Otherwise flag.
    if _DROP_TABLE_RE.search(sql):
        only_if_exists_paired = (
            _DROP_TABLE_IF_EXISTS_RE.search(sql)
            and _CREATE_TABLE_RE.search(sql)
            # And there is no bare `DROP TABLE` (without IF EXISTS) outside the paired form.
            and not re.search(r"\bDROP\s+TABLE\b(?!\s+IF\s+EXISTS)", sql, re.IGNORECASE)
        )
        if not only_if_exists_paired:
            matches.append("DROP TABLE")
    return matches


def _check_safety(name: str, sql: str, override: bool) -> str | None:
    """Raise RuntimeError if destructive and not overridden.

    Returns a notes string when overridden (to record in _migrations.notes),
    else None.
    """
    matches = _scan_destructive(name, sql)
    if not matches:
        return None
    if not override:
        raise RuntimeError(
            f"Refusing to apply destructive migration {name!r}: matched "
            f"{matches}. Set ALLOW_DESTRUCTIVE_MIGRATIONS=1 to override "
            f"(after taking a backup)."
        )
    msg = (
        f"!!! DESTRUCTIVE MIGRATION OVERRIDE !!! file={name} patterns={matches} "
        f"— applying because ALLOW_DESTRUCTIVE_MIGRATIONS=1"
    )
    logger.warning(msg)
    logger.warning("!" * 80)
    return f"DESTRUCTIVE_OVERRIDE: {','.join(matches)}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_migrations():
    """Run all pending migrations under a pg advisory lock.

    For each .sql file in sorted order:
      1. Compute sha256.
      2. Scan for destructive patterns (block unless override env set).
      3. If row in _migrations exists with same hash → skip.
      4. If row exists with different hash → log drift WARNING and skip.
      5. Else apply + insert row.
    """
    if not MIGRATIONS_DIR.exists():
        logger.warning(f"Migrations dir not found: {MIGRATIONS_DIR}")
        return

    override = os.getenv("ALLOW_DESTRUCTIVE_MIGRATIONS", "").strip() in ("1", "true", "yes", "on")
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    with get_conn() as conn:
        # Acquire serialization lock first (separate cursor / autocommit-ish).
        lock_cur = conn.cursor()
        lock_cur.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        conn.commit()  # ensure lock is materialized
        try:
            with conn.cursor() as cur:
                # Ensure tracking table exists (new + legacy side-by-side).
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS _migrations (
                        name TEXT PRIMARY KEY,
                        hash TEXT NOT NULL,
                        applied_at TIMESTAMPTZ DEFAULT now(),
                        notes TEXT
                    )
                """)
                # Keep legacy table too — older code paths may reference it.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        applied_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                conn.commit()

                # Defense-in-depth: scan EVERY file (even already-applied) at startup.
                # If a past file has been edited to add destructive SQL, refuse to boot.
                for f in migration_files:
                    sql = f.read_text()
                    # _check_safety raises if destructive & not overridden.
                    _check_safety(f.name, sql, override)

                # Pre-load tracking rows.
                cur.execute("SELECT name, hash FROM _migrations")
                applied = {row[0]: row[1] for row in cur.fetchall()}

                for f in migration_files:
                    sql = f.read_text()
                    h = _sha256(sql)
                    notes = _check_safety(f.name, sql, override)  # never raises here (already passed)

                    prior = applied.get(f.name)
                    if prior is not None:
                        if prior == h:
                            continue  # silent skip
                        logger.warning(
                            f"Migration drift: {f.name} hash changed "
                            f"(stored={prior[:12]}… current={h[:12]}…). "
                            f"NOT re-applying — investigate manually."
                        )
                        continue

                    logger.info(f"Running migration {f.name}…")
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO _migrations (name, hash, notes) VALUES (%s, %s, %s)",
                        (f.name, h, notes),
                    )
                    # Mirror into legacy table when name follows NNN_*.sql.
                    try:
                        version = int(f.name.split("_")[0])
                        cur.execute(
                            "INSERT INTO schema_migrations (version, name) VALUES (%s, %s) "
                            "ON CONFLICT (version) DO NOTHING",
                            (version, f.name),
                        )
                    except (ValueError, IndexError):
                        pass
                    logger.info(f"Migration {f.name} applied")

                conn.commit()
        finally:
            try:
                lock_cur.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to release advisory lock: {e}")
            try:
                lock_cur.close()
            except Exception:
                pass

    logger.info("All migrations up to date")


# ---------------------------------------------------------------------------
# Health-check helper (used by /api/health)
# ---------------------------------------------------------------------------
def migration_status() -> dict:
    """Return migration health snapshot for /api/health.

    Shape: {applied, files, pending: [...], drift: [...], last_applied}
    """
    out: dict = {"applied": 0, "files": 0, "pending": [], "drift": [], "last_applied": None}
    if not MIGRATIONS_DIR.exists():
        return out

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    out["files"] = len(files)
    file_hashes = {f.name: _sha256(f.read_text()) for f in files}

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS(
                        SELECT 1 FROM information_schema.tables WHERE table_name='_migrations'
                    )
                """)
                if not cur.fetchone()[0]:
                    out["pending"] = list(file_hashes.keys())
                    return out

                cur.execute("SELECT name, hash FROM _migrations")
                rows = {r[0]: r[1] for r in cur.fetchall()}
                out["applied"] = len(rows)

                for name, h in file_hashes.items():
                    if name not in rows:
                        out["pending"].append(name)
                    elif rows[name] != h:
                        out["drift"].append(name)

                cur.execute("SELECT name FROM _migrations ORDER BY applied_at DESC NULLS LAST LIMIT 1")
                row = cur.fetchone()
                if row:
                    out["last_applied"] = row[0]
    except Exception as e:
        logger.debug(f"[migration_status] failed: {e}")
    return out
