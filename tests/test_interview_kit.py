"""Tests for /interview-kit endpoints — list/edit/delete/audience filter.

Generation tests skipped unless OPENROUTER_API_KEY set (live LLM call).
Mirrors fixture pattern from test_ai_promote_reject.py.
"""
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
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout.strip()


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
        timeout=20.0,
    )
    yield c
    c.close()


@pytest.fixture
def position(client: httpx.Client):
    title = f"ik-test-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/positions/", json={
        "title": title, "department": "QA", "location": "Remote",
        "employment_type": "full-time",
        "jd_text": "Backend engineer. Python, FastAPI, Postgres. 5+ yrs.",
    })
    assert r.status_code in (200, 201)
    body = r.json()
    pid = body.get("position_id")
    slug = body.get("slug") or _psql(f"SELECT slug FROM positions WHERE id={pid}")
    yield {"id": int(pid), "slug": slug, "title": title}
    if pid:
        try:
            _psql(f"DELETE FROM positions WHERE id={pid}")
        except Exception:
            pass


def _seed_question(pid: int, *, audience="HR_BP", stage="SCREEN",
                   category="BEHAVIORAL", q="Walk me thru a recent project.",
                   candidate_id=None) -> int:
    cid = "NULL" if candidate_id is None else str(int(candidate_id))
    sql = (
        f"INSERT INTO interview_questions "
        f"(position_id, candidate_id, audience, category, stage, question, "
        f"look_for, red_flags, source) "
        f"VALUES ({pid}, {cid}, '{audience}', '{category}', '{stage}', "
        f"$${q}$$, ARRAY['ownership']::text[], ARRAY['vague timeline']::text[], 'manual') "
        f"RETURNING id"
    )
    out = _psql(sql)
    return int(out.split("\n")[0])


def test_list_empty(client, position):
    r = client.get(f"/api/positions/{position['slug']}/interview-kit")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["questions"] == []
    assert body["position"]["id"] == position["id"]


def test_list_with_seed(client, position):
    qid = _seed_question(position["id"])
    r = client.get(f"/api/positions/{position['slug']}/interview-kit")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    q = body["questions"][0]
    assert q["id"] == qid
    assert q["audience"] == "HR_BP"
    assert q["category"] == "BEHAVIORAL"


def test_audience_filter(client, position):
    _seed_question(position["id"], audience="HR_BP")
    _seed_question(position["id"], audience="TECH", category="TECHNICAL")
    r = client.get(f"/api/positions/{position['slug']}/interview-kit?audience=TECH")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["questions"][0]["audience"] == "TECH"


def test_stage_filter(client, position):
    _seed_question(position["id"], stage="SCREEN")
    _seed_question(position["id"], stage="ONSITE")
    r = client.get(f"/api/positions/{position['slug']}/interview-kit?stage=ONSITE")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_edit_question(client, position):
    qid = _seed_question(position["id"])
    r = client.patch(f"/api/interview-kit/{qid}", json={
        "question": "UPDATED q",
        "look_for": ["new signal"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "UPDATED q"
    assert body["look_for"] == ["new signal"]


def test_mark_used(client, position):
    qid = _seed_question(position["id"])
    r = client.post(f"/api/interview-kit/{qid}/used")
    assert r.status_code == 200
    assert r.json()["used"] is True


def test_delete_question(client, position):
    qid = _seed_question(position["id"])
    r = client.delete(f"/api/interview-kit/{qid}")
    assert r.status_code == 200
    assert r.json()["deleted"] == qid
    # confirm gone
    r2 = client.delete(f"/api/interview-kit/{qid}")
    assert r2.status_code == 404


def test_export_md(client, position):
    _seed_question(position["id"], q="Tell me about a tradeoff.")
    r = client.get(f"/api/positions/{position['slug']}/interview-kit/export.md")
    assert r.status_code == 200
    assert "text/markdown" in r.headers.get("content-type", "")
    assert "Tell me about a tradeoff." in r.text
    assert "# Interview Kit" in r.text


def test_bad_audience_rejected(client, position):
    qid = _seed_question(position["id"])
    r = client.patch(f"/api/interview-kit/{qid}", json={"audience": "INVALID"})
    assert r.status_code == 400


@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="needs LLM key")
def test_generate_generic(client, position):
    r = client.post(f"/api/positions/{position['slug']}/interview-kit/generate", json={
        "audience": "HR_BP", "stage": "SCREEN", "count": 4,
    })
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["generated"] >= 1
    assert all(q["source"] == "ai_generic" for q in body["questions"])


def test_position_404(client):
    r = client.get("/api/positions/nope-not-real-xyz/interview-kit")
    assert r.status_code == 404
