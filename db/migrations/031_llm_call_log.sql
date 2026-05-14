-- Per-call LLM cost ledger. Powers /billing dashboard.
CREATE TABLE IF NOT EXISTS llm_call_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  tenant_id TEXT NOT NULL DEFAULT 'default',
  operator_id TEXT,
  candidate_id INT,
  run_id TEXT,
  step TEXT,
  model TEXT NOT NULL,
  in_tokens INT NOT NULL DEFAULT 0,
  out_tokens INT NOT NULL DEFAULT 0,
  cost_usd NUMERIC(10,6) NOT NULL DEFAULT 0,
  latency_ms INT,
  status TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS llm_call_log_ts_idx ON llm_call_log (ts DESC);
CREATE INDEX IF NOT EXISTS llm_call_log_tenant_ts_idx ON llm_call_log (tenant_id, ts DESC);
CREATE INDEX IF NOT EXISTS llm_call_log_model_idx ON llm_call_log (model);
CREATE INDEX IF NOT EXISTS llm_call_log_run_idx ON llm_call_log (run_id);
CREATE INDEX IF NOT EXISTS llm_call_log_step_idx ON llm_call_log (step);
