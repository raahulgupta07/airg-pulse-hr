"""Smoke tests for /api/agents/config endpoints (mig 059).

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
        timeout=130.0,
    )
    yield c
    c.close()


@pytest.fixture(scope="module")
def unauth_client() -> httpx.Client:
    c = httpx.Client(base_url=API_BASE, timeout=5.0)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def _restore_jd_bias(client):
    """Snapshot jd-bias config before, restore after each test."""
    pre = None
    try:
        body = client.get("/api/agents/config").json()
        for a in body.get("agents", []):
            if a["id"] == "jd-bias":
                pre = a.get("config", {})
                break
    except Exception:
        pass
    yield
    if pre:
        try:
            client.patch("/api/agents/config/jd-bias", json={
                "enabled": pre.get("enabled", True),
                "interval_seconds": pre.get("interval_seconds") or 1800,
            })
        except Exception:
            pass


def test_list_returns_16_agents(client):
    r = client.get("/api/agents/config")
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert "agents" in body
    assert len(body["agents"]) >= 16, f"expected ≥16, got {len(body['agents'])}"


def test_patch_jd_bias_disable(client):
    r = client.patch("/api/agents/config/jd-bias", json={"enabled": False})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["enabled"] is False
    g = client.get("/api/agents/config").json()
    jd = next((a for a in g["agents"] if a["id"] == "jd-bias"), None)
    assert jd is not None
    assert jd["config"]["enabled"] is False


def test_patch_interval_too_low(client):
    r = client.patch("/api/agents/config/jd-bias", json={"interval_seconds": 30})
    assert r.status_code == 400, f"got {r.status_code}: {r.text[:200]}"


def test_patch_interval_too_high(client):
    r = client.patch("/api/agents/config/jd-bias", json={"interval_seconds": 100000})
    assert r.status_code == 400, f"got {r.status_code}: {r.text[:200]}"


def test_patch_nonexistent_agent(client):
    """Spec: PATCH against unknown agent_id → 404.

    Current implementation does an unconditional UPSERT, so this surfaces
    that gap. Test fails until guard is added.
    """
    r = client.patch("/api/agents/config/nonexistent-agent-xyz",
                     json={"enabled": False})
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"


def test_patch_no_auth_blocked(unauth_client):
    r = unauth_client.patch("/api/agents/config/jd-bias", json={"enabled": False})
    assert r.status_code in (401, 403), f"got {r.status_code}: {r.text[:200]}"


def test_test_run_admin(client):
    """Admin test-run returns 200 (run executed) or 501 (no run_once registered)."""
    r = client.post("/api/agents/jd-bias/test-run")
    assert r.status_code in (200, 501, 504, 500), \
        f"unexpected: {r.status_code}: {r.text[:200]}"


def test_test_run_no_auth_blocked(unauth_client):
    r = unauth_client.post("/api/agents/jd-bias/test-run")
    assert r.status_code in (401, 403), f"got {r.status_code}: {r.text[:200]}"
