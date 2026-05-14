"""Verify the startup stale-scan sweeper marks long-running scans as error.

Inserts a synthetic running scan with started_at 15 min in the past, then
restarts the api container so backend.main:_sweep_stale_ai_scans runs at
startup. Asserts the row's status flips to 'error' with
error='stale_on_restart'.

Slow: api restart + warm-up is ~10–15s. Run last in any test sequence.
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
API_SERVICE = os.getenv("PULSE_API_SERVICE", "api")
DB_USER = os.getenv("PULSE_DB_USER", "hire")
DB_NAME = os.getenv("PULSE_DB_NAME", "pulsedb")
ADMIN_ID = os.getenv("PULSE_ADMIN_ID", "pulse_admin")
ADMIN_PW = os.getenv("PULSE_ADMIN_PW", "admin")


def _psql(sql: str) -> str:
    r = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER, "psql", "-U", DB_USER,
         "-d", DB_NAME, "-tA", "-F", "|", "-c", sql],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql: {r.stderr.strip()}")
    return r.stdout.strip()


def _psql_rows(sql: str) -> list[list[str]]:
    out = _psql(sql)
    return [line.split("|") for line in out.splitlines()] if out else []


def _wait_api_ready(timeout_s: float = 60.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = httpx.get(f"{API_BASE}/api/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


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
    last = None
    for _ in range(4):
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


@pytest.mark.slow
def test_sweeper_marks_stale_running_as_error(client, created_positions):
    # 1. Create position for FK ownership of the scan row
    title = f"stale-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/positions/", json={
        "title": title, "department": "QA",
        "location": "Remote", "employment_type": "full-time",
    })
    assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:200]}"
    pos = r.json()
    pid = int(pos["position_id"])
    created_positions.append(pid)

    # 2. INSERT running scan with started_at 15 min ago
    out = _psql(
        f"INSERT INTO position_ai_scans "
        f"(position_id, status, started_at, created_at) "
        f"VALUES ({pid}, 'running', NOW() - INTERVAL '15 minutes', "
        f"NOW() - INTERVAL '15 minutes') RETURNING id"
    )
    scan_id = None
    for ln in out.strip().splitlines():
        ln = ln.strip()
        if ln.isdigit():
            scan_id = int(ln)
            break
    assert scan_id is not None, f"could not parse scan id: {out!r}"

    # 3. Restart api container so startup sweeper runs
    r = subprocess.run(
        ["docker", "compose", "restart", API_SERVICE],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    if r.returncode != 0:
        # Try plain `docker restart pulse-api` as fallback
        r2 = subprocess.run(["docker", "restart", "pulse-api"],
                            capture_output=True, text=True, timeout=60)
        if r2.returncode != 0:
            pytest.skip(f"could not restart api: {r.stderr.strip()} / {r2.stderr.strip()}")

    # 4. Wait for api to come back + sweeper to complete
    assert _wait_api_ready(timeout_s=60.0), "api did not come back online"
    # Give sweeper a beat (it runs in startup task, may finish slightly after health-ok)
    time.sleep(3)

    # 5. Verify row was swept
    rows = _psql_rows(
        f"SELECT status, error FROM position_ai_scans WHERE id={scan_id}"
    )
    assert rows, f"scan {scan_id} disappeared"
    status, err = rows[0][0], rows[0][1]
    assert status == "error", f"expected status='error', got {status!r}"
    assert err == "stale_on_restart", f"expected error='stale_on_restart', got {err!r}"
