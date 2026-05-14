# Load Test Dashboards & Queries

Run these against the application Postgres while the load test is in flight.
Tail them on a 10-30 s loop (e.g. `watch -n 15 psql ... -c "..."`).

---

## 1. Per-tool latency p95 (last 5 min)

```sql
SELECT
  tool,
  count(*)                                                    AS calls,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms)    AS p50_ms,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)    AS p95_ms,
  percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms)    AS p99_ms
FROM tool_traces
WHERE ts > NOW() - INTERVAL '5 min'
GROUP BY tool
ORDER BY p95_ms DESC;
```

Watch for any single tool dominating p95 — that's your hot path to cache /
parallelize.

---

## 2. Cost per session p95 (last 15 min)

```sql
SELECT
  count(*)                                                  AS sessions,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY cost_usd)    AS p50_usd,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY cost_usd)    AS p95_usd,
  percentile_cont(0.99) WITHIN GROUP (ORDER BY cost_usd)    AS p99_usd,
  sum(cost_usd)                                             AS total_usd
FROM agent_runs
WHERE started_at > NOW() - INTERVAL '15 min';
```

Project hourly burn = `total_usd * (60 / 15)`. Compare to `LLM_DAILY_CAP_USD`.

---

## 3. LLM call count per session

```sql
SELECT
  run_id,
  count(*)                                                 AS llm_calls,
  sum(prompt_tokens)                                       AS in_tokens,
  sum(completion_tokens)                                   AS out_tokens,
  sum(cost_usd)                                            AS cost_usd
FROM llm_call_log
WHERE ts > NOW() - INTERVAL '5 min'
GROUP BY run_id
ORDER BY llm_calls DESC
LIMIT 20;
```

Distribution sanity:

```sql
SELECT
  percentile_cont(0.50) WITHIN GROUP (ORDER BY n)  AS p50_llm_calls,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY n)  AS p95_llm_calls
FROM (
  SELECT count(*) AS n
  FROM llm_call_log
  WHERE ts > NOW() - INTERVAL '5 min'
  GROUP BY run_id
) s;
```

Spikes here (p95 LLM calls > ~15 per session) usually mean the agent is
looping on a tool.

---

## 4. Stuck / runaway agent runs

```sql
SELECT
  run_id,
  user_id,
  started_at,
  NOW() - started_at AS age,
  status
FROM agent_runs
WHERE status = 'running'
  AND started_at < NOW() - INTERVAL '2 min'
ORDER BY started_at;
```

Any rows here during a load test = candidates for the watchdog / circuit
breaker.

---

## 5. Postgres pool pressure

```sql
SELECT count(*) AS conns FROM pg_stat_activity;

SELECT state, count(*)
FROM pg_stat_activity
GROUP BY state
ORDER BY 2 DESC;

-- Long-running queries
SELECT pid, state, NOW() - query_start AS age, left(query, 120) AS q
FROM pg_stat_activity
WHERE state != 'idle'
  AND query_start < NOW() - INTERVAL '5 s'
ORDER BY age DESC
LIMIT 20;
```

Compare `count(*)` to `SHOW max_connections;`.

---

## 6. Redis pressure

```bash
docker compose exec redis redis-cli INFO memory   | grep -E 'used_memory_human|maxmemory_human|mem_fragmentation_ratio'
docker compose exec redis redis-cli INFO clients  | grep -E 'connected_clients|blocked_clients'
docker compose exec redis redis-cli INFO stats    | grep -E 'instantaneous_ops_per_sec|evicted_keys|keyspace_hits|keyspace_misses'
```

Hit ratio target: `keyspace_hits / (keyspace_hits + keyspace_misses) > 0.8`
on cache namespaces.

---

## 7. OpenRouter / upstream errors

```sql
SELECT
  status,
  count(*)            AS n,
  max(ts)             AS last_seen
FROM llm_call_log
WHERE ts > NOW() - INTERVAL '5 min'
  AND status >= 400
GROUP BY status
ORDER BY n DESC;
```

Any `429` rows ⇒ raise concurrency cap on OpenRouter side or add upstream
backoff. Any `5xx` ⇒ stop the test.

---

## 8. End-of-run snapshot

After the run finishes, capture once for the postmortem:

```sql
-- Total spend during the run window (substitute the window).
SELECT sum(cost_usd) FROM agent_runs WHERE started_at > NOW() - INTERVAL '5 min';

-- Error breakdown
SELECT status_code, count(*) FROM api_request_log
WHERE ts > NOW() - INTERVAL '5 min'
GROUP BY status_code ORDER BY 2 DESC;

-- Top 10 slowest tool spans
SELECT tool, latency_ms, run_id, ts
FROM tool_traces
WHERE ts > NOW() - INTERVAL '5 min'
ORDER BY latency_ms DESC
LIMIT 10;
```

Save with `\o /tmp/load_run_<ts>.txt` in psql, or pipe through `psql -c`.
