"""Verify positions created WITHOUT jd_text do not enqueue an AI scan."""
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
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
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
        pytest.skip(f"Login failed ({r.status_code})")
    tok = r.json().get("token")
    if not tok:
        pytest.skip("No token")
    return tok


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


def test_create_without_jd_no_scan_row(client, created_positions):
    title = f"no-jd-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/positions/", json={
        "title": title,
        "department": "QA",
        "location": "Remote",
        "employment_type": "full-time",
        # explicitly no jd_text
    })
    assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:200]}"
    pid = r.json().get("position_id")
    assert pid, "no position_id returned"
    created_positions.append(int(pid))

    # Wait 3s — auto-scan, if it were to fire, would have inserted a row.
    time.sleep(3)
    rows = _psql_rows(
        f"SELECT id, status FROM position_ai_scans WHERE position_id={pid}"
    )
    assert not rows, (
        f"expected NO position_ai_scans for jd-less position, got {rows}"
    )
