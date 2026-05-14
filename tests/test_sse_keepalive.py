"""Verify the SSE stream emits ': ping' keepalives during a long-running scan.

The SSE endpoint is per-position: GET /api/positions/{slug}/ai/events.
We INSERT a synthetic 'running' scan row, open the stream, capture ~30s
worth of output, and assert at least one ': ping' line appears.

Cleanup marks the scan as done so dedupe doesn't block future scans.
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


def _psql(sql: str) -> str:
    r = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER, "psql", "-U", DB_USER,
         "-d", DB_NAME, "-tA", "-F", "|", "-c", sql],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql: {r.stderr.strip()}")
    return r.stdout.strip()


@pytest.fixture(scope="module", autouse=True)
def _gate():
    ok = False
    for _ in range(3):
        try:
            if httpx.get(f"{API_BASE}/api/health", timeout=5.0).status_code == 200:
                ok = True
                break
        except Exception:
            time.sleep(1)
    if not ok:
        pytest.skip("API not reachable")
    try:
        r = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                           capture_output=True, text=True, timeout=30)
        if DB_CONTAINER not in r.stdout.split():
            pytest.skip(f"{DB_CONTAINER} not running")
    except subprocess.TimeoutExpired:
        pytest.skip("docker ps timed out (daemon overloaded)")


@pytest.fixture(scope="module")
def auth_token() -> str:
    # Login is rate-limited 5/min; retry with backoff on 429.
    last = None
    for attempt in range(3):
        r = httpx.post(f"{API_BASE}/api/auth/login",
                       json={"operator_id": ADMIN_ID, "access_key": ADMIN_PW},
                       timeout=5.0)
        last = r
        if r.status_code == 200:
            return r.json().get("token") or pytest.skip("no token")
        if r.status_code == 429:
            time.sleep(15)
            continue
        break
    pytest.skip(f"login failed: {last.status_code if last else '?'}")


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


def test_sse_emits_ping_on_active_scan(client, auth_token, created_positions):
    # Create a position to host the scan row
    title = f"sse-ping-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/positions/", json={
        "title": title, "department": "QA",
        "location": "Remote", "employment_type": "full-time",
    })
    assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:200]}"
    pos = r.json()
    pid, slug = int(pos["position_id"]), pos["slug"]
    created_positions.append(pid)

    # Insert synthetic running scan
    out = _psql(
        f"INSERT INTO position_ai_scans (position_id, status, started_at) "
        f"VALUES ({pid}, 'running', now()) RETURNING id"
    )
    scan_id = None
    for ln in out.strip().splitlines():
        ln = ln.strip()
        if ln.isdigit():
            scan_id = int(ln)
            break
    if scan_id is None:
        pytest.skip(f"could not parse scan id: {out!r}")

    saw_ping = False
    buf = ""
    url = f"{API_BASE}/api/positions/{slug}/ai/events?token={auth_token}"
    try:
        # ~40s window — endpoint pings every 25 ticks (~25s); first ping at tick 25.
        with httpx.stream("GET", url, timeout=45.0,
                          headers={"Authorization": f"Bearer {auth_token}"}) as resp:
            assert resp.status_code == 200, f"SSE status {resp.status_code}"
            deadline = time.time() + 40.0
            for chunk in resp.iter_text():
                if chunk:
                    buf += chunk
                    # SSE comments per spec start with ":" — accept ":ping" or ": ping"
                    if ": ping" in buf or ":ping" in buf:
                        saw_ping = True
                        break
                if time.time() > deadline:
                    break
    except httpx.ReadTimeout:
        pass
    finally:
        try:
            _psql(
                f"UPDATE position_ai_scans SET status='done', finished_at=now() "
                f"WHERE id={scan_id}"
            )
        except Exception:
            pass

    assert saw_ping, f"did not receive any ': ping' line within 40s; buf tail={buf[-300:]!r}"
