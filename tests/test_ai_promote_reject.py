"""Tests for AI promote/reject endpoints on position_candidates.

Same fixture conventions as test_ai_scan.py (httpx against localhost:8090,
psql via `docker exec pulse-db`). Each test creates its own position and
attaches a candidate manually so we don't depend on AI scoring producing
matches above threshold.
"""
from __future__ import annotations

import os
import subprocess
import time
import uuid

import httpx
import pytest


API_BASE = os.getenv("PULSE_API_BASE", "http://localhost:8090")
DB_CONTAINER = os.getenv("PULSE_DB_CONTAINER", "pulse-db")
DB_USER = os.getenv("PULSE_DB_USER", "hire")
DB_NAME = os.getenv("PULSE_DB_NAME", "pulsedb")
ADMIN_ID = os.getenv("PULSE_ADMIN_ID", "pulse_admin")
ADMIN_PW = os.getenv("PULSE_ADMIN_PW", "admin")


def _api_alive() -> bool:
    try:
        return httpx.get(f"{API_BASE}/api/health", timeout=2.0).status_code == 200
    except Exception:
        return False


def _docker_exists() -> bool:
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=3,
        )
        return r.returncode == 0 and DB_CONTAINER in r.stdout.split()
    except Exception:
        return False


def _psql(sql: str) -> str:
    cmd = [
        "docker", "exec", "-i", DB_CONTAINER,
        "psql", "-U", DB_USER, "-d", DB_NAME,
        "-tA", "-F", "|", "-c", sql,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()} (sql={sql!r})")
    return r.stdout.strip()


def _psql_rows(sql: str) -> list[list[str]]:
    out = _psql(sql)
    return [line.split("|") for line in out.splitlines()] if out else []


@pytest.fixture(scope="module", autouse=True)
def _gate():
    if not _api_alive():
        pytest.skip(f"API not reachable at {API_BASE}")
    if not _docker_exists():
        pytest.skip(f"Docker container {DB_CONTAINER!r} not running")


@pytest.fixture(scope="module")
def auth_token() -> str:
    r = httpx.post(
        f"{API_BASE}/api/auth/login",
        json={"operator_id": ADMIN_ID, "access_key": ADMIN_PW},
        timeout=5.0,
    )
    if r.status_code != 200:
        pytest.skip(f"Login failed ({r.status_code})")
    tok = r.json().get("token")
    if not tok:
        pytest.skip("No token in login response")
    return tok


@pytest.fixture(scope="module")
def client(auth_token: str) -> httpx.Client:
    c = httpx.Client(
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=15.0,
    )
    yield c
    c.close()


@pytest.fixture
def created_positions() -> list[int]:
    ids: list[int] = []
    yield ids
    if ids:
        try:
            id_list = ",".join(str(i) for i in ids)
            _psql(f"DELETE FROM positions WHERE id IN ({id_list})")
        except Exception:
            pass


def _make_position(client: httpx.Client, tracker: list[int],
                   hint: str = "promo-test") -> dict:
    title = f"{hint}-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/positions/", json={
        "title": title, "department": "QA",
        "location": "Remote", "employment_type": "full-time",
    })
    assert r.status_code in (200, 201), f"create position: {r.status_code} {r.text[:200]}"
    payload = r.json()
    pid = payload.get("position_id")
    if pid:
        tracker.append(int(pid))
    return payload


def _pick_candidate_id() -> int | None:
    rows = _psql_rows(
        "SELECT id FROM candidates WHERE COALESCE(is_processed,FALSE)=TRUE "
        "ORDER BY id DESC LIMIT 1"
    )
    return int(rows[0][0]) if rows else None


def _attach(pid: int, cid: int, source: str = "manual") -> None:
    _psql(
        f"INSERT INTO position_candidates (position_id, candidate_id, stage, match_source) "
        f"VALUES ({pid}, {cid}, 'uploaded', '{source}') "
        f"ON CONFLICT (position_id, candidate_id) DO UPDATE "
        f"SET stage='uploaded', dismissed=FALSE, match_source=EXCLUDED.match_source"
    )


# ── tests ──────────────────────────────────────────────────────────────────

def test_promote_moves_to_screened(client, created_positions):
    cid = _pick_candidate_id()
    if cid is None:
        pytest.skip("no processed candidates available")
    pos = _make_position(client, created_positions, "promote-ok")
    pid, slug = pos["position_id"], pos["slug"]
    _attach(pid, cid)

    r = client.post(f"/api/positions/{slug}/ai/{cid}/promote")
    assert r.status_code == 200, f"promote: {r.status_code} {r.text[:200]}"

    rows = _psql_rows(
        f"SELECT stage, match_source FROM position_candidates "
        f"WHERE position_id={pid} AND candidate_id={cid}"
    )
    assert rows, "row missing after promote"
    assert rows[0][0] == "screened", f"stage={rows[0][0]!r}"
    assert rows[0][1] == "ai_promoted", f"match_source={rows[0][1]!r}"


def test_reject_sets_dismissed(client, created_positions):
    cid = _pick_candidate_id()
    if cid is None:
        pytest.skip("no processed candidates available")
    pos = _make_position(client, created_positions, "reject-ok")
    pid, slug = pos["position_id"], pos["slug"]
    _attach(pid, cid)

    r = client.post(f"/api/positions/{slug}/ai/{cid}/reject")
    assert r.status_code == 200, f"reject: {r.status_code} {r.text[:200]}"

    rows = _psql_rows(
        f"SELECT dismissed, stage FROM position_candidates "
        f"WHERE position_id={pid} AND candidate_id={cid}"
    )
    assert rows
    dismissed = rows[0][0].lower() in ("t", "true")
    assert dismissed, f"dismissed={rows[0][0]!r}"
    assert rows[0][1] == "rejected", f"stage={rows[0][1]!r}"


def test_promote_404_unattached_candidate(client, created_positions):
    cid = _pick_candidate_id()
    if cid is None:
        pytest.skip("no processed candidates available")
    pos = _make_position(client, created_positions, "promo-404")
    slug = pos["slug"]
    # Do NOT attach; expect 404.
    r = client.post(f"/api/positions/{slug}/ai/{cid}/promote")
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"


def test_reject_404_unattached_candidate(client, created_positions):
    cid = _pick_candidate_id()
    if cid is None:
        pytest.skip("no processed candidates available")
    pos = _make_position(client, created_positions, "rej-404")
    slug = pos["slug"]
    r = client.post(f"/api/positions/{slug}/ai/{cid}/reject")
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"


@pytest.mark.skip(reason="needs 2nd user")
def test_promote_403_non_owner():
    pass
