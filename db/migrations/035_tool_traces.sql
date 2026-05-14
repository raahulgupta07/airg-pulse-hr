-- Per-step tool-call trace for Agno agent runs. One row per tool
-- invocation within a run (run_id FK to agent_runs.run_id, soft —
-- no enforced FK so trace writes never block on run row). Captures
-- input/output payloads, latency, status, and error for replay +
-- debugging in /agent run-detail view.
CREATE TABLE IF NOT EXISTS tool_traces (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL,
  step_idx INT,
  tool TEXT NOT NULL,
  input JSONB,
  output JSONB,
  latency_ms INT,
  status TEXT DEFAULT 'ok',
  error TEXT,
  ts TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS tool_traces_run_idx ON tool_traces (run_id);
CREATE INDEX IF NOT EXISTS tool_traces_tool_idx ON tool_traces (tool);
CREATE INDEX IF NOT EXISTS tool_traces_ts_idx ON tool_traces (ts DESC);
