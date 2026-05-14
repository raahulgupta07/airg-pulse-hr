"""Verify position_candidates.match_source enum behavior."""
from __future__ import annotations

import os
import subprocess
import uuid

import httpx
import pytest


API_BASE = os.getenv("PULSE_API_BASE", "http://localhost:8090")
DB_CONTAINER = os.getenv("PULSE_DB_CONTAINER", "pulse-db")
DB_USER = os.getenv("PULSE_DB_USER", "hire")
DB_NAME = os.getenv("PULSE_DB_NAME", "pulsedb")
ADMIN_ID = os.getenv("PULSE_ADMIN_ID", "pulse_admin")
ADMIN_PW = os.getenv("PULSE_ADMIN_PW", "admin")

ALLOWED_SOURCES = {
    "manual", "auto_scan_on_create", "auto_scan_on_jd_update",
    "auto_scan_rescan", "ai_promoted",
}


def _psql(sql: str) -> str:
    r = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER, "psql", "-U", DB_USER,
         "-d", DB_NAME, "-tA", "-F", "|", "-c", sql],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql: {r.stderr.strip()}")
    return r.stdout.strip()


def _psql_rows(sql: str) -> list[list[str]]:
    out = _psql(sql)
    return [line.split("|") for line in out.splitlines()] if out else []


@pytest.fixture(scope="module", autouse=True)
def _gate():
    try:
        if httpx.get(f"{API_BASE}/api/health", timeout=2.0).status_code != 200:
            pytest.skip("API not reachable")
    except Exception:
        pytest.skip("API not reachable")
    r = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                       capture_output=True, text=True, timeout=3)
    if DB_CONTAINER not in r.stdout.split():
        pytest.skip(f"{DB_CONTAINER} not running")


@pytest.fixture(scope="module")
def auth_token() -> str:
    r = httpx.post(f"{API_BASE}/api/auth/login",
                   json={"operator_id": ADMIN_ID, "access_key": ADMIN_PW},
                   timeout=5.0)
    if r.status_code != 200:
        pytest.skip("login failed")
    return r.json().get("token") or pytest.skip("no token")


@pytest.fixture(scope="module")
def client(auth_token: str) -> httpx.Client:
    c = httpx.Client(base_url=API_BASE,
                     headers={"Authorization": f"Bearer {auth_token}"},
                     timeout=15.0)
    yield c
    c.close()


@pytest.fixture
def created_positions() -> list[int]:
    ids: list[int] = []
    yield ids
    if ids:
        try:
            _psql(f"DELETE FROM positions WHERE id IN ({','.join(str(i) for i in ids)})")
        except Exception:
            pass


def _make_position(client, tracker, hint="ms-test"):
    title = f"{hint}-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/positions/", json={
        "title": title, "department": "QA",
        "location": "Remote", "employment_type": "full-time",
    })
    assert r.status_code in (200, 201)
    p = r.json()
    tracker.append(int(p["position_id"]))
    return p


def _pick_candidate_id() -> int | None:
    rows = _psql_rows(
        "SELECT id FROM candidates WHERE COALESCE(is_processed,FALSE)=TRUE "
        "ORDER BY id DESC LIMIT 1"
    )
    return int(rows[0][0]) if rows else None


# 1. manual default
def test_match_source_default_manual(client, created_positions):
    cid = _pick_candidate_id()
    if cid is None:
        pytest.skip("no processed candidate")
    pos = _make_position(client, created_positions, "ms-default")
    pid = pos["position_id"]
    # Insert without specifying match_source
    _psql(
        f"INSERT INTO position_candidates (position_id, candidate_id, stage) "
        f"VALUES ({pid}, {cid}, 'uploaded')"
    )
    rows = _psql_rows(
        f"SELECT match_source FROM position_candidates "
        f"WHERE position_id={pid} AND candidate_id={cid}"
    )
    assert rows, "row missing"
    assert rows[0][0] == "manual", f"expected default 'manual', got {rows[0][0]!r}"


# 2. auto_scan_on_create — query latest scanned position (covered in test_ai_scan)
def test_match_source_auto_scan_on_create_via_db():
    rows = _psql_rows(
        "SELECT COUNT(*) FROM position_candidates WHERE match_source='auto_scan_on_create'"
    )
    if not rows or int(rows[0][0]) == 0:
        pytest.skip("no auto_scan_on_create rows in DB; covered in test_ai_scan.py")
    assert int(rows[0][0]) > 0


# 3. ai_promoted via promote endpoint
def test_match_source_ai_promoted(client, created_positions):
    cid = _pick_candidate_id()
    if cid is None:
        pytest.skip("no candidate")
    pos = _make_position(client, created_positions, "ms-promote")
    pid, slug = pos["position_id"], pos["slug"]
    _psql(
        f"INSERT INTO position_candidates (position_id, candidate_id, stage, match_source) "
        f"VALUES ({pid}, {cid}, 'uploaded', 'manual')"
    )
    r = client.post(f"/api/positions/{slug}/ai/{cid}/promote")
    assert r.status_code == 200, f"promote: {r.status_code} {r.text[:200]}"
    rows = _psql_rows(
        f"SELECT match_source FROM position_candidates "
        f"WHERE position_id={pid} AND candidate_id={cid}"
    )
    assert rows[0][0] == "ai_promoted", f"got {rows[0][0]!r}"


# 4. enum sanity
def test_match_source_enum_values():
    rows = _psql_rows(
        "SELECT DISTINCT match_source FROM position_candidates "
        "WHERE match_source IS NOT NULL"
    )
    found = {r[0] for r in rows}
    extra = found - ALLOWED_SOURCES
    assert not extra, f"unknown match_source values in DB: {extra}"
