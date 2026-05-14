"""Tests for POST /api/positions/{slug}/ai/bulk-promote."""
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
                     timeout=20.0)
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


def _make_position(client, tracker, hint="bulk"):
    title = f"{hint}-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/positions/", json={
        "title": title, "department": "QA",
        "location": "Remote", "employment_type": "full-time",
    })
    assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:200]}"
    p = r.json()
    tracker.append(int(p["position_id"]))
    return p


def _pick_n_candidates(n: int) -> list[int]:
    rows = _psql_rows(
        f"SELECT id FROM candidates WHERE COALESCE(is_processed,FALSE)=TRUE "
        f"ORDER BY id DESC LIMIT {n}"
    )
    return [int(r[0]) for r in rows]


def _attach(pid: int, cid: int) -> None:
    _psql(
        f"INSERT INTO position_candidates (position_id, candidate_id, stage, match_source) "
        f"VALUES ({pid}, {cid}, 'uploaded', 'manual') "
        f"ON CONFLICT (position_id, candidate_id) DO UPDATE "
        f"SET stage='uploaded', dismissed=FALSE"
    )


# ── tests ──────────────────────────────────────────────────────────────────

def test_bulk_promote_happy_path(client, created_positions):
    cids = _pick_n_candidates(3)
    if len(cids) < 3:
        pytest.skip("need >=3 processed candidates")
    pos = _make_position(client, created_positions, "bulk-ok")
    pid, slug = pos["position_id"], pos["slug"]
    for cid in cids:
        _attach(pid, cid)

    r = client.post(f"/api/positions/{slug}/ai/bulk-promote",
                    json={"candidate_ids": cids})
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    data = r.json()
    assert data.get("total") == 3, f"total={data.get('total')}"
    assert sorted(data.get("promoted", [])) == sorted(cids), data
    assert data.get("failed") == [], f"failed={data.get('failed')}"

    rows = _psql_rows(
        f"SELECT candidate_id, stage FROM position_candidates "
        f"WHERE position_id={pid} AND candidate_id IN ({','.join(str(c) for c in cids)})"
    )
    stages = {int(r[0]): r[1] for r in rows}
    for cid in cids:
        assert stages.get(cid) == "screened", f"cid={cid} stage={stages.get(cid)!r}"


def test_bulk_promote_cap_exceeded(client, created_positions):
    pos = _make_position(client, created_positions, "bulk-cap")
    slug = pos["slug"]
    bogus = list(range(1, 52))  # 51 ids
    r = client.post(f"/api/positions/{slug}/ai/bulk-promote",
                    json={"candidate_ids": bogus})
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"
    assert "max" in r.text.lower() or "cap" in r.text.lower() or "too many" in r.text.lower(), \
        f"error doesn't mention cap: {r.text[:200]}"


def test_bulk_promote_partial_failure(client, created_positions):
    cids = _pick_n_candidates(2)
    if len(cids) < 2:
        pytest.skip("need >=2 processed candidates")
    pos = _make_position(client, created_positions, "bulk-partial")
    pid, slug = pos["position_id"], pos["slug"]
    # Attach only the first; second + a bogus id will fail
    _attach(pid, cids[0])
    bogus_id = 999_999_999
    payload_ids = [cids[0], cids[1], bogus_id]

    r = client.post(f"/api/positions/{slug}/ai/bulk-promote",
                    json={"candidate_ids": payload_ids})
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    data = r.json()
    assert cids[0] in data.get("promoted", []), data
    failed = data.get("failed", [])
    failed_cids = {f.get("cid") for f in failed}
    assert cids[1] in failed_cids, f"cids[1] not in failed: {failed}"
    assert bogus_id in failed_cids, f"bogus not in failed: {failed}"
    for f in failed:
        assert "reason" in f, f"failed entry missing reason: {f}"
