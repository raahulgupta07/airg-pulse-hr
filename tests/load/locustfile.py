"""
Locust load test for HUB-HR-Agent chat v2 SSE agent.

Scenarios:
  - chat_send (weight 5): random Q from golden.jsonl → POST /api/chat/, consume SSE
  - view_pipeline (weight 2): GET /api/positions, GET /api/positions/{slug}/candidates
  - view_billing (weight 1): GET /api/billing/summary

Custom metrics emitted via locust events (visible in HTML/CSV report):
  - chat_ttft_ms              (time to first SSE token)
  - chat_total_ms             (full stream duration)
  - chat_tool_call_count      (number of tool_call events per response)
  - chat_cost_usd             (sum of cost_usd parsed from tool_result events)

Install:
    pip install locust

Run:
    ./run_load.sh 100 5 5m http://localhost:8090
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any

try:
    from locust import HttpUser, between, events, task
except ImportError as exc:  # pragma: no cover - test-only dep
    raise SystemExit(
        "locust is not installed. Install with: pip install locust"
    ) from exc


# ---------------------------------------------------------------------------
# Golden corpus loading
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOLDEN_PATH = _REPO_ROOT / "backend" / "agents" / "eval" / "golden.jsonl"


def _load_golden_queries() -> list[str]:
    """Load queries from the golden eval set. Falls back to a tiny default."""
    if not _GOLDEN_PATH.exists():
        return [
            "Show me the open positions",
            "Who are the top candidates for the latest role?",
            "What is my billing usage this month?",
        ]
    queries: list[str] = []
    with _GOLDEN_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Accept several common keys.
            for key in ("query", "question", "prompt", "input", "user"):
                if key in row and isinstance(row[key], str) and row[key].strip():
                    queries.append(row[key].strip())
                    break
    return queries or ["Show me the open positions"]


_QUERIES = _load_golden_queries()


# ---------------------------------------------------------------------------
# Auth / config
# ---------------------------------------------------------------------------

OPERATOR_ID = os.getenv("LOAD_OPERATOR_ID", "pulse_admin")
ACCESS_KEY = os.getenv("LOAD_ACCESS_KEY", "PulseAdmin#2026!")
CHAT_TIMEOUT_S = float(os.getenv("LOAD_CHAT_TIMEOUT", "60"))


def _fire_metric(name: str, value: float, response_length: int = 0) -> None:
    """Emit a custom metric to locust's request stats stream."""
    events.request.fire(
        request_type="METRIC",
        name=name,
        response_time=value,
        response_length=response_length,
        exception=None,
        context={},
    )


# ---------------------------------------------------------------------------
# User scenarios
# ---------------------------------------------------------------------------


class ChatUser(HttpUser):
    wait_time = between(2, 8)

    token: str | None = None
    position_slugs: list[str] = []

    # --- lifecycle ----------------------------------------------------------

    def on_start(self) -> None:
        """Authenticate and cache JWT + a few position slugs."""
        with self.client.post(
            "/api/auth/login",
            json={"operator_id": OPERATOR_ID, "access_key": ACCESS_KEY},
            name="auth:login",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"login failed: {resp.status_code} {resp.text[:200]}")
                return
            try:
                payload = resp.json()
            except ValueError:
                resp.failure("login response not JSON")
                return
            tok = payload.get("access_token")
            if not tok:
                resp.failure("no access_token in login response")
                return
            self.token = tok
            self.client.headers.update({"Authorization": f"Bearer {tok}"})

        # Warm cache of position slugs (best-effort).
        try:
            r = self.client.get("/api/positions", name="bootstrap:positions")
            if r.status_code == 200:
                data = r.json()
                items = data if isinstance(data, list) else data.get("items") or data.get("positions") or []
                slugs = [it.get("slug") for it in items if isinstance(it, dict) and it.get("slug")]
                self.position_slugs = slugs[:20]
        except Exception:
            self.position_slugs = []

    # --- helpers ------------------------------------------------------------

    def _consume_sse(self, resp: Any, started: float) -> tuple[float | None, int, float]:
        """
        Iterate an SSE stream. Returns (ttft_ms, tool_call_count, cost_usd_sum).
        Parses lines of form `event: <name>` and `data: <json>`.
        """
        ttft_ms: float | None = None
        tool_calls = 0
        cost_usd = 0.0
        current_event: str | None = None

        for raw in resp.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            if ttft_ms is None and raw:
                ttft_ms = (time.perf_counter() - started) * 1000.0
            if not raw:
                current_event = None
                continue
            if raw.startswith(":"):
                continue  # SSE comment/heartbeat
            if raw.startswith("event:"):
                current_event = raw[6:].strip()
                continue
            if raw.startswith("data:"):
                data_str = raw[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    payload = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # Event type can come from `event:` line or from payload field.
                etype = current_event or (payload.get("type") if isinstance(payload, dict) else None)

                if etype == "tool_call":
                    tool_calls += 1
                elif etype == "tool_result" and isinstance(payload, dict):
                    cost = (
                        payload.get("cost_usd")
                        or (payload.get("result") or {}).get("cost_usd")
                        or (payload.get("data") or {}).get("cost_usd")
                    )
                    try:
                        if cost is not None:
                            cost_usd += float(cost)
                    except (TypeError, ValueError):
                        pass
        return ttft_ms, tool_calls, cost_usd

    def _send_chat(self, url: str, name: str, message: str) -> None:
        body = {"message": message, "stream": True}
        started = time.perf_counter()
        with self.client.post(
            url,
            json=body,
            name=name,
            stream=True,
            catch_response=True,
            headers={"Accept": "text/event-stream"},
            timeout=CHAT_TIMEOUT_S,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"chat HTTP {resp.status_code}: {resp.text[:200]}")
                return
            try:
                ttft_ms, tool_calls, cost_usd = self._consume_sse(resp, started)
            except Exception as e:  # noqa: BLE001
                resp.failure(f"sse parse error: {e}")
                return
            total_ms = (time.perf_counter() - started) * 1000.0

            if ttft_ms is not None:
                _fire_metric("chat_ttft_ms", ttft_ms)
            _fire_metric("chat_total_ms", total_ms)
            _fire_metric("chat_tool_call_count", tool_calls)
            # locust expects ms-ish floats; we still log dollar metric (×1000 for visibility).
            _fire_metric("chat_cost_usd_x1000", cost_usd * 1000.0)
            resp.success()

    # --- tasks --------------------------------------------------------------

    @task(5)
    def chat_send(self) -> None:
        if not self.token:
            return
        message = random.choice(_QUERIES)
        # 25% of chat traffic targets a position-scoped chat if we have slugs.
        if self.position_slugs and random.random() < 0.25:
            slug = random.choice(self.position_slugs)
            self._send_chat(
                f"/api/chat/position/{slug}",
                name="chat:position",
                message=message,
            )
        else:
            self._send_chat("/api/chat/", name="chat:global", message=message)

    @task(2)
    def view_pipeline(self) -> None:
        if not self.token:
            return
        with self.client.get("/api/positions", name="positions:list", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"positions HTTP {r.status_code}")
                return
            try:
                data = r.json()
            except ValueError:
                r.failure("positions: non-JSON response")
                return
            items = data if isinstance(data, list) else data.get("items") or data.get("positions") or []
            slugs = [it.get("slug") for it in items if isinstance(it, dict) and it.get("slug")]
            if slugs:
                self.position_slugs = slugs[:20]

        if self.position_slugs:
            slug = random.choice(self.position_slugs)
            self.client.get(
                f"/api/positions/{slug}/candidates",
                name="positions:candidates",
            )

    @task(1)
    def view_billing(self) -> None:
        if not self.token:
            return
        self.client.get("/api/billing/summary", name="billing:summary")
