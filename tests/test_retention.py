"""Smoke tests for /api/admin/retention endpoints (mig 056).

Mirrors fixture pattern from tests/test_interview_kit.py.
"""
from __future__ import annotations

import os
import subprocess

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


@pytest.fixture(scope="module", autouse=True)
def _gate():
    if not _api_alive():
        pytest.skip(f"API not reachable at {API_BASE}")
    if not _docker_exists():
        pytest.skip(f"Docker container {DB_CONTAINER} not running")


@pytest.fixture(scope="module")
def auth_token() -> str:
    r = httpx.post(
        f"{API_BASE}/api/auth/login",
        json={"operator_id": ADMIN_ID, "access_key": ADMIN_PW},
        timeout=5.0,
    )
    if r.status_code != 200:
        pytest.skip(f"Login failed ({r.status_code})")
    return r.json().get("token") or pytest.skip("No token in response")


@pytest.fixture(scope="module")
def client(auth_token: str) -> httpx.Client:
    c = httpx.Client(
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=10.0,
    )
    yield c
    c.close()


@pytest.fixture(scope="module")
def unauth_client() -> httpx.Client:
    c = httpx.Client(base_url=API_BASE, timeout=5.0)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def _restore_defaults(client):
    """Snapshot retention before, restore after each test."""
    pre = client.get("/api/admin/retention").json()
    yield
    try:
        client.post("/api/admin/retention", json={
            "cv_days": pre.get("cv_days", 90),
            "jd_days": pre.get("jd_days", 90),
        })
    except Exception:
        pass


def test_get_returns_defaults(client):
    r = client.get("/api/admin/retention")
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert "cv_days" in body
    assert "jd_days" in body
    assert isinstance(body["cv_days"], int)
    assert isinstance(body["jd_days"], int)


def test_post_updates_cv_days(client):
    r = client.post("/api/admin/retention", json={"cv_days": 30, "jd_days": 90})
    assert r.status_code == 200, r.text[:200]
    assert r.json()["cv_days"] == 30
    g = client.get("/api/admin/retention")
    assert g.status_code == 200
    assert g.json()["cv_days"] == 30


def test_post_negative_rejected(client):
    r = client.post("/api/admin/retention", json={"cv_days": -1, "jd_days": 90})
    assert r.status_code == 400, f"got {r.status_code}: {r.text[:200]}"


def test_post_over_cap_rejected(client):
    r = client.post("/api/admin/retention", json={"cv_days": 5000, "jd_days": 90})
    assert r.status_code == 400, f"got {r.status_code}: {r.text[:200]}"


def test_post_no_auth_blocked(unauth_client):
    """No bearer token at all → 401/403."""
    r = unauth_client.post("/api/admin/retention", json={"cv_days": 30})
    assert r.status_code in (401, 403), f"got {r.status_code}: {r.text[:200]}"
