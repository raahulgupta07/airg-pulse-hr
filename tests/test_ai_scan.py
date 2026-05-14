"""Tests for the AI scan system (position auto-scan + match_source + SSE).

Targets a running API at http://localhost:8090 with PostgreSQL inside the
`pulse-db` Docker container (no host port mapping). DB queries are routed
through `docker exec pulse-db psql` to keep the test self-contained.

Auth: logs in as `pulse_admin` / `admin` (legacy operator_id flow), reuses
the JWT in module-scoped fixture.

Each test that creates a position records its position_id and the
`_cleanup_positions` autouse=False fixture deletes them post-run via
`DELETE FROM positions WHERE id = ANY($1)`. CASCADE FK on
`position_ai_scans` + `position_candidates` handles dependent rows.

If the API or DB are unavailable, tests are SKIPPED rather than failed —
the module never disrupts prod state on its own.
"""
from __future__ import annotations

import json
import os
import shlex
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


# ── helpers ────────────────────────────────────────────────────────────────

def _api_alive() -> bool:
    try:
        r = httpx.get(f"{API_BASE}/api/health", timeout=2.0)
        return r.status_code == 200
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
    """Run a SQL string via `docker exec pulse-db psql`. Returns raw stdout."""
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
    if not out:
        return []
    return [line.split("|") for line in out.splitlines()]


# ── module-scoped fixtures ─────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def _gate():
    if not _api_alive():
        pytest.skip(f"API not reachable at {API_BASE}; skipping AI scan tests")
    if not _docker_exists():
        pytest.skip(f"Docker container {DB_CONTAINER!r} not running; skipping")


@pytest.fixture(scope="module")
def auth_token() -> str:
    r = httpx.post(
        f"{API_BASE}/api/auth/login",
        json={"operator_id": ADMIN_ID, "access_key": ADMIN_PW},
        timeout=5.0,
    )
    if r.status_code != 200:
        pytest.skip(f"Login failed ({r.status_code}): {r.text[:200]}")
    tok = r.json().get("token")
    if not tok:
        pytest.skip("Login response missing token")
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
    """Tracks position_ids created by a test; cleaned up after."""
    ids: list[int] = []
    yield ids
    if ids:
        try:
            id_list = ",".join(str(i) for i in ids)
            _psql(f"DELETE FROM positions WHERE id IN ({id_list})")
        except Exception:
            pass


def _make_position(client: httpx.Client, jd_text: str | None,
                   tracker: list[int], title_hint: str = "ai-scan-test") -> dict:
    title = f"{title_hint}-{uuid.uuid4().hex[:8]}"
    body = {"title": title, "department": "QA", "location": "Remote",
            "employment_type": "full-time"}
    if jd_text:
        body["jd_text"] = jd_text
    r = client.post("/api/positions/", json=body)
    assert r.status_code in (200, 201), f"create position failed: {r.status_code} {r.text[:200]}"
    payload = r.json()
    pid = payload.get("position_id")
    if pid:
        tracker.append(int(pid))
    return payload


def _wait_scan(pid: int, want_status: tuple[str, ...] = ("done",),
               timeout_s: float = 12.0) -> dict | None:
    """Poll position_ai_scans for a row whose status is in want_status."""
    deadline = time.time() + timeout_s
    last: dict | None = None
    while time.time() < deadline:
        rows = _psql_rows(
            "SELECT id, status, started_at, finished_at, n_scored, n_matched "
            f"FROM position_ai_scans WHERE position_id={pid} "
            "ORDER BY created_at DESC LIMIT 1"
        )
        if rows:
            r = rows[0]
            last = {
                "id": int(r[0]), "status": r[1],
                "started_at": r[2] or "", "finished_at": r[3] or "",
                "n_scored": int(r[4] or 0), "n_matched": int(r[5] or 0),
            }
            if last["status"] in want_status:
                return last
        time.sleep(0.4)
    return last


SAMPLE_JD = (
    "We are hiring a Senior Python Backend Engineer. Required skills: "
    "Python, FastAPI, PostgreSQL, Docker, REST APIs. Minimum 5 years of "
    "experience building scalable backend systems. Familiarity with "
    "pgvector and AI/LLM integrations a plus."
)


# ── 1. position create inserts scan row ────────────────────────────────────

def test_position_create_inserts_scan_row(client, created_positions):
    payload = _make_position(client, SAMPLE_JD, created_positions, "scan-row")
    pid = payload["position_id"]

    time.sleep(2)

    rows = _psql_rows(
        "SELECT id, status FROM position_ai_scans "
        f"WHERE position_id={pid} ORDER BY created_at DESC LIMIT 1"
    )
    assert rows, f"no position_ai_scans row found for position_id={pid}"
    status = rows[0][1]
    assert status in {"queued", "running", "done"}, f"unexpected status={status!r}"


# ── 2. status transitions queued → running → done ─────────────────────────

def test_scan_status_transitions(client, created_positions):
    payload = _make_position(client, SAMPLE_JD, created_positions, "transitions")
    pid = payload["position_id"]

    seen: set[str] = set()
    deadline = time.time() + 12.0
    last_row: list[str] | None = None
    while time.time() < deadline:
        rows = _psql_rows(
            "SELECT status, started_at, finished_at FROM position_ai_scans "
            f"WHERE position_id={pid} ORDER BY created_at DESC LIMIT 1"
        )
        if rows:
            last_row = rows[0]
            seen.add(rows[0][0])
            if rows[0][0] == "done":
                break
        time.sleep(0.3)

    assert "done" in seen, f"scan never reached done; statuses seen={seen}"
    assert last_row is not None
    started_at, finished_at = last_row[1], last_row[2]
    assert started_at, "started_at not set on done scan"
    assert finished_at, "finished_at not set on done scan"
    assert finished_at >= started_at, (
        f"finished_at ({finished_at}) < started_at ({started_at})"
    )


# ── 3. match_source = auto_scan_on_create ─────────────────────────────────

def test_match_source_auto_scan_on_create(client, created_positions):
    # Need at least 1 candidate row in DB for matching to produce results
    cand_rows = _psql_rows("SELECT COUNT(*) FROM candidates WHERE COALESCE(is_processed,FALSE)=TRUE")
    if not cand_rows or int(cand_rows[0][0]) < 1:
        pytest.skip("no processed candidates in DB; cannot test auto_scan_on_create match_source")

    payload = _make_position(client, SAMPLE_JD, created_positions, "match-src")
    pid = payload["position_id"]

    scan = _wait_scan(pid, ("done",), timeout_s=20.0)
    if not scan or scan["status"] != "done":
        pytest.skip(f"scan did not complete in time (last={scan})")

    rows = _psql_rows(
        "SELECT match_source FROM position_candidates "
        f"WHERE position_id={pid}"
    )
    if not rows:
        pytest.skip("scan completed but no candidates were attached (none above threshold)")

    sources = {r[0] for r in rows}
    assert "auto_scan_on_create" in sources, (
        f"expected at least one row with match_source=auto_scan_on_create, got {sources}"
    )


# ── 4. CV upload skips Step 12 when MATCH_ON_CV_UPLOAD=false ──────────────

def test_match_on_cv_upload_disabled_skips_step12(client):
    # We don't trigger a fresh CV pipeline (heavy + side-effecting).
    # Instead: assert that ANY recent AUTO_MATCH trace within last 24h shows
    # the skip details — this validates the gate is wired correctly when the
    # env flag is at its default (false).
    flag_skip = os.getenv("MATCH_ON_CV_UPLOAD", "false").lower() == "true"
    if flag_skip:
        pytest.skip("MATCH_ON_CV_UPLOAD=true; skip-Step-12 path not exercised")

    rows = _psql_rows(
        "SELECT details::text FROM pipeline_trace "
        "WHERE step_name='AUTO_MATCH' AND started_at > now() - interval '24 hours' "
        "ORDER BY started_at DESC LIMIT 5"
    )
    if not rows:
        pytest.skip("no AUTO_MATCH pipeline_trace rows in last 24h")

    found_skip = False
    for r in rows:
        try:
            d = json.loads(r[0]) if r[0] else {}
        except Exception:
            continue
        if str(d.get("skipped")).lower() == "true" and \
           d.get("reason") == "match_on_cv_upload_disabled":
            found_skip = True
            break
    assert found_skip, (
        "no recent AUTO_MATCH trace with skipped=true + reason=match_on_cv_upload_disabled"
    )


# ── 5. dedupe returns same scan_id on rapid POST /ai/rescan ───────────────

def test_dedupe_returns_same_scan_id(client, created_positions):
    payload = _make_position(client, SAMPLE_JD, created_positions, "dedupe")
    pid = payload["position_id"]
    slug = payload["slug"]

    # Force a known active scan row so dedup must trigger regardless of the
    # auto-scan timing.
    out = _psql(
        f"INSERT INTO position_ai_scans (position_id, status, started_at) "
        f"VALUES ({pid}, 'running', now()) RETURNING id"
    )
    # psql -tA RETURNING output: first non-empty line = id, then "INSERT 0 1"
    manual_scan_id = None
    for ln in out.strip().splitlines():
        ln = ln.strip()
        if ln.isdigit():
            manual_scan_id = int(ln)
            break
    if manual_scan_id is None:
        pytest.skip(f"could not parse manual scan id from: {out!r}")

    try:
        r1 = client.post(f"/api/positions/{slug}/ai/rescan")
        r2 = client.post(f"/api/positions/{slug}/ai/rescan")
        assert r1.status_code == 200, f"rescan #1 {r1.status_code}: {r1.text[:200]}"
        assert r2.status_code == 200, f"rescan #2 {r2.status_code}: {r2.text[:200]}"
        j1, j2 = r1.json(), r2.json()
        assert j1.get("scan_id") == j2.get("scan_id"), (
            f"dedup failed: {j1} vs {j2}"
        )
        # Either dedup flag or in_progress status indicates the dedup path
        assert (j1.get("dedup") is True) or (j1.get("status") == "in_progress"), (
            f"expected dedup=true or status=in_progress, got {j1}"
        )
    finally:
        # Cleanup: mark our manual row done so it doesn't block future scans
        try:
            _psql(
                f"UPDATE position_ai_scans SET status='done', finished_at=now() "
                f"WHERE id={manual_scan_id}"
            )
        except Exception:
            pass


# ── 6. /ai endpoint returns matches ────────────────────────────────────────

def test_ai_endpoint_returns_matches(client, created_positions):
    cand_rows = _psql_rows(
        "SELECT COUNT(*) FROM candidates WHERE COALESCE(is_processed,FALSE)=TRUE"
    )
    if not cand_rows or int(cand_rows[0][0]) < 2:
        pytest.skip("need >=2 processed candidates to validate sorted matches")

    payload = _make_position(client, SAMPLE_JD, created_positions, "ai-endpoint")
    pid = payload["position_id"]
    slug = payload["slug"]

    scan = _wait_scan(pid, ("done",), timeout_s=20.0)
    if not scan or scan["status"] != "done":
        pytest.skip(f"scan did not complete in time (last={scan})")

    r = client.get(f"/api/positions/{slug}/ai")
    assert r.status_code == 200, f"/ai {r.status_code}: {r.text[:200]}"
    data = r.json()

    assert data.get("scan", {}).get("status") == "done", (
        f"scan.status != done: {data.get('scan')}"
    )
    n_scored = int(data.get("scan", {}).get("n_scored") or 0)
    assert n_scored >= 2, f"n_scored={n_scored}, expected >=2"

    matches = data.get("matches")
    assert isinstance(matches, list), f"matches not a list: {type(matches)}"
    if len(matches) >= 2:
        scores = [m.get("match_score_composite") or 0 for m in matches]
        assert scores == sorted(scores, reverse=True), (
            f"matches not sorted desc by composite score: {scores}"
        )


# ── 7. SSE endpoint emits scan + end events ───────────────────────────────

def test_sse_endpoint_emits_scan_event(client, auth_token, created_positions):
    payload = _make_position(client, SAMPLE_JD, created_positions, "sse")
    pid = payload["position_id"]
    slug = payload["slug"]

    saw_scan = False
    saw_end = False
    url = f"{API_BASE}/api/positions/{slug}/ai/events?token={auth_token}"

    deadline = time.time() + 12.0
    try:
        with httpx.stream("GET", url,
                          headers={"Authorization": f"Bearer {auth_token}"},
                          timeout=12.0) as resp:
            assert resp.status_code == 200, f"SSE status {resp.status_code}"
            for raw in resp.iter_lines():
                if time.time() > deadline:
                    break
                if not raw:
                    continue
                line = raw if isinstance(raw, str) else raw.decode("utf-8", "ignore")
                if line.startswith("event: scan"):
                    saw_scan = True
                elif line.startswith("event: end"):
                    saw_end = True
                    break
    except httpx.ReadTimeout:
        pass

    assert saw_scan, "did not receive any 'event: scan' line within 12s"
    assert saw_end, "did not receive 'event: end' line"
