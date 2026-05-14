# Chat v2 Load Test (Locust)

Scaffold for load-testing the HUB-HR-Agent chat v2 SSE agent at ~100 concurrent
users. The scenario mixes streaming chat with realistic side traffic
(pipeline browsing, billing).

> **Note**: A real run requires the chat v2 stack (Agno + LangGraph) to be
> installed in the API container. Rebuild Docker before pushing real load:
> `docker compose build api && docker compose up -d api`.

---

## 1. Prerequisites

```bash
pip install locust
```

Locust is **not** added to `backend/requirements.txt` — it is a test-only
dependency. Install it in your local venv (or a dedicated load-test venv).

Backend must be running with chat v2 enabled. In `.env`:

```
AGENT_V2=true
```

Then restart the API:

```bash
docker compose restart api
# or, locally:
uvicorn backend.app:app --port 8090 --reload
```

Confirm health:

```bash
curl -s http://localhost:8090/api/health | jq
```

You want `redis: ok`, `db: ok`, `llm: ok`, sane `pool` stats, and a recent
`uptime`.

---

## 2. Run

```bash
cd tests/load
./run_load.sh                                 # 100u, 5/s spawn, 5m, localhost:8090
./run_load.sh 100 5 5m http://localhost:8090  # explicit
./run_load.sh 25 5 2m http://localhost:8090   # smoke run before going to 100
```

Credentials default to `pulse_admin` / `PulseAdmin#2026!`. Override with:

```bash
LOAD_OPERATOR_ID=foo LOAD_ACCESS_KEY='bar' ./run_load.sh
```

Outputs (in `tests/load/`):
- `report.html` — Locust HTML report (open in browser)
- `stats_stats.csv`, `stats_failures.csv`, `stats_stats_history.csv`

---

## 3. What to watch

### In Locust report
- **p50 / p95 latency** for `chat:global` and `chat:position`
- **Custom metrics** (logged as `METRIC` request type):
  - `chat_ttft_ms` — time to first SSE token
  - `chat_total_ms` — full stream duration
  - `chat_tool_call_count` — tools invoked per response
  - `chat_cost_usd_x1000` — $ per response × 1000 (locust wants ms-ish numbers)
- **Failure rate** — should be < 1%
- **OpenRouter 429s** — surface as failures with `429` in the message

### In a separate terminal (during the run)

Postgres connection peak:
```sql
SELECT count(*) FROM pg_stat_activity;
SELECT state, count(*) FROM pg_stat_activity GROUP BY state;
```

Redis memory:
```bash
docker compose exec redis redis-cli INFO memory | grep used_memory_human
```

Live cost vs daily cap (`LLM_DAILY_CAP_USD` in `.env`):
```sql
SELECT COALESCE(SUM(cost_usd), 0) AS spent_today
FROM llm_call_log
WHERE ts >= date_trunc('day', NOW());
```

API health every 10s:
```bash
watch -n 10 'curl -s http://localhost:8090/api/health | jq'
```

See `dashboards.md` for the full SQL playbook.

---

## 4. Pass criteria (100 concurrent users, 5 min run)

| Metric                          | Threshold              |
|--------------------------------|------------------------|
| Chat p95 (total stream)         | < 8 s                  |
| Chat p95 (time to first token)  | < 2 s                  |
| Error rate (all endpoints)      | < 1 %                  |
| HTTP 5xx count                  | 0                      |
| Hourly LLM spend                | < $50/hr               |
| OpenRouter 429s                 | 0                      |
| Postgres connections at peak    | < 80 % of `max_connections` |
| Redis memory                    | < 70 % of maxmemory    |
| Stuck `agent_runs` (`status='running'` > 2 min) | 0     |

If any threshold is breached, capture:
1. `report.html` and CSVs from this directory
2. Output of the SQL queries in `dashboards.md`
3. API + worker container logs for the run window

---

## 5. Tuning knobs

In `locustfile.py`:
- `wait_time = between(2, 8)` — adjust think time
- `LOAD_CHAT_TIMEOUT` env var — per-request timeout in seconds (default 60)
- Task weights on `@task(N)` — change traffic mix

The query corpus is pulled from `backend/agents/eval/golden.jsonl`. Update
that file (separately) to evolve the load profile — do **not** create a
parallel corpus here.
