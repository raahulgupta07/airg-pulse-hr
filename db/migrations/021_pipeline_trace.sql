CREATE TABLE IF NOT EXISTS pipeline_trace (
  id            serial PRIMARY KEY,
  candidate_id  int REFERENCES candidates(id) ON DELETE CASCADE,
  ingest_id     int,
  run_id        uuid NOT NULL,
  step_order    int NOT NULL,
  step_name     text NOT NULL,
  model         text,
  status        text NOT NULL DEFAULT 'pending',
  latency_ms    int,
  cost_usd      numeric(12,6),
  input_tokens  int,
  output_tokens int,
  details       jsonb,
  error_msg     text,
  started_at    timestamptz DEFAULT now(),
  finished_at   timestamptz
);
CREATE INDEX IF NOT EXISTS idx_pipeline_trace_cand ON pipeline_trace(candidate_id, run_id, step_order);
CREATE INDEX IF NOT EXISTS idx_pipeline_trace_run ON pipeline_trace(run_id);
