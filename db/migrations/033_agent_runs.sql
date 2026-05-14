-- Agno agent run ledger. One row per agent invocation. Tracks
-- session, tenant, operator, tool-call breadcrumbs, token + cost
-- accounting, and terminal status. Powers /agent dashboard +
-- per-run trace drill-down (joins tool_traces on run_id).
CREATE TABLE IF NOT EXISTS agent_runs (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT UNIQUE NOT NULL,
  session_id BIGINT,
  tenant_id INT,
  operator_id INT,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  ended_at TIMESTAMPTZ,
  tool_calls JSONB DEFAULT '[]',
  steps INT DEFAULT 0,
  in_tokens INT DEFAULT 0,
  out_tokens INT DEFAULT 0,
  cost_usd NUMERIC(10,6) DEFAULT 0,
  status TEXT DEFAULT 'running',
  error TEXT
);
CREATE INDEX IF NOT EXISTS agent_runs_session_idx ON agent_runs (session_id);
CREATE INDEX IF NOT EXISTS agent_runs_tenant_idx ON agent_runs (tenant_id);
CREATE INDEX IF NOT EXISTS agent_runs_started_idx ON agent_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS agent_runs_status_idx ON agent_runs (status);
