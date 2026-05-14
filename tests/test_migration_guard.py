"""Tests for backend.core.migrations safety guard, hashing, and lock release.

Uses a fake in-memory DB connection to keep tests hermetic (no Postgres needed).
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fake DB plumbing — minimal psycopg-like cursor/connection.
# ---------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, store):
        self.store = store
        self._last_result = []

    def execute(self, sql, params=()):
        s = sql.strip().lower()
        self.store["executed"].append((sql, params))
        if "pg_advisory_lock" in s:
            self.store["lock_acquired"] = True
            self._last_result = [(None,)]
        elif "pg_advisory_unlock" in s:
            self.store["lock_released"] = True
            self._last_result = [(True,)]
        elif "create table if not exists _migrations" in s:
            self._last_result = []
        elif "create table if not exists schema_migrations" in s:
            self._last_result = []
        elif "select exists" in s and "_migrations" in s:
            self._last_result = [(True,)]
        elif "select name, hash from _migrations" in s:
            self._last_result = [(n, h) for n, (h, _notes) in self.store["rows"].items()]
        elif s.startswith("select name from _migrations"):
            names = list(self.store["rows"].keys())
            self._last_result = [(names[-1],)] if names else []
        elif s.startswith("insert into _migrations"):
            name, h, notes = params
            self.store["rows"][name] = (h, notes)
            self._last_result = []
        elif s.startswith("insert into schema_migrations"):
            self._last_result = []
        elif self.store.get("raise_on_apply") and not s.startswith(("select", "insert", "create")):
            raise RuntimeError("boom")
        else:
            self._last_result = []

    def fetchone(self):
        return self._last_result[0] if self._last_result else None

    def fetchall(self):
        return list(self._last_result)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.store["commits"] += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def fake_db(monkeypatch):
    store = {
        "rows": {},          # name -> (hash, notes)
        "executed": [],
        "commits": 0,
        "lock_acquired": False,
        "lock_released": False,
        "raise_on_apply": False,
    }
    from contextlib import contextmanager

    @contextmanager
    def fake_get_conn():
        yield FakeConn(store)

    import backend.core.migrations as mig
    importlib.reload(mig)
    monkeypatch.setattr(mig, "get_conn", fake_get_conn)
    return store, mig


@pytest.fixture
def tmp_migrations(tmp_path, monkeypatch):
    d = tmp_path / "migrations"
    d.mkdir()
    import backend.core.migrations as mig
    monkeypatch.setattr(mig, "MIGRATIONS_DIR", d)
    return d


def _write(d: Path, name: str, sql: str):
    (d / name).write_text(sql)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_forbidden_pattern_blocks(fake_db, tmp_migrations, monkeypatch):
    monkeypatch.delenv("ALLOW_DESTRUCTIVE_MIGRATIONS", raising=False)
    store, mig = fake_db
    _write(tmp_migrations, "001_init.sql", "CREATE TABLE foo(id int);")
    _write(tmp_migrations, "002_bad.sql", "ALTER TABLE foo DROP COLUMN id;")
    with pytest.raises(RuntimeError, match="DROP COLUMN"):
        mig.run_migrations()


def test_forbidden_drop_table_blocks(fake_db, tmp_migrations, monkeypatch):
    monkeypatch.delenv("ALLOW_DESTRUCTIVE_MIGRATIONS", raising=False)
    store, mig = fake_db
    _write(tmp_migrations, "001_bad.sql", "DROP TABLE foo;")
    with pytest.raises(RuntimeError, match="DROP TABLE"):
        mig.run_migrations()


def test_drop_table_if_exists_paired_with_create_allowed(fake_db, tmp_migrations, monkeypatch):
    monkeypatch.delenv("ALLOW_DESTRUCTIVE_MIGRATIONS", raising=False)
    store, mig = fake_db
    _write(tmp_migrations, "001_rebuild.sql",
           "DROP TABLE IF EXISTS foo;\nCREATE TABLE foo(id int);")
    mig.run_migrations()
    assert "001_rebuild.sql" in store["rows"]


def test_override_allows(fake_db, tmp_migrations, monkeypatch):
    monkeypatch.setenv("ALLOW_DESTRUCTIVE_MIGRATIONS", "1")
    store, mig = fake_db
    _write(tmp_migrations, "001_bad.sql", "ALTER TABLE foo DROP COLUMN id;")
    mig.run_migrations()
    assert "001_bad.sql" in store["rows"]
    h, notes = store["rows"]["001_bad.sql"]
    assert notes and "DESTRUCTIVE_OVERRIDE" in notes
    assert "DROP COLUMN" in notes


def test_already_applied_skipped(fake_db, tmp_migrations, monkeypatch):
    monkeypatch.delenv("ALLOW_DESTRUCTIVE_MIGRATIONS", raising=False)
    store, mig = fake_db
    sql = "CREATE TABLE foo(id int);"
    _write(tmp_migrations, "001_init.sql", sql)
    mig.run_migrations()
    assert len(store["rows"]) == 1
    before_executed = len(store["executed"])

    mig.run_migrations()
    # Second run should NOT have executed any new migration SQL.
    new_inserts = [e for e in store["executed"][before_executed:] if "insert into _migrations" in e[0].lower()]
    assert new_inserts == []


def test_hash_drift_detected_not_reapplied(fake_db, tmp_migrations, monkeypatch, caplog):
    monkeypatch.delenv("ALLOW_DESTRUCTIVE_MIGRATIONS", raising=False)
    store, mig = fake_db
    f = tmp_migrations / "001_init.sql"
    f.write_text("CREATE TABLE foo(id int);")
    mig.run_migrations()
    original_hash = store["rows"]["001_init.sql"][0]

    # Edit file (non-destructive) → hash changes
    f.write_text("CREATE TABLE foo(id int, name text);")
    with caplog.at_level("WARNING"):
        mig.run_migrations()
    # Hash in store unchanged (NOT re-applied).
    assert store["rows"]["001_init.sql"][0] == original_hash
    assert any("drift" in rec.message.lower() for rec in caplog.records)


def test_advisory_lock_released_on_error(fake_db, tmp_migrations, monkeypatch):
    monkeypatch.setenv("ALLOW_DESTRUCTIVE_MIGRATIONS", "1")
    store, mig = fake_db
    _write(tmp_migrations, "001_init.sql", "UPDATE foo SET x=1;")
    store["raise_on_apply"] = True
    with pytest.raises(RuntimeError, match="boom"):
        mig.run_migrations()
    assert store["lock_acquired"] is True
    assert store["lock_released"] is True


def test_advisory_lock_released_on_success(fake_db, tmp_migrations, monkeypatch):
    monkeypatch.delenv("ALLOW_DESTRUCTIVE_MIGRATIONS", raising=False)
    store, mig = fake_db
    _write(tmp_migrations, "001_init.sql", "CREATE TABLE foo(id int);")
    mig.run_migrations()
    assert store["lock_acquired"] and store["lock_released"]
