-- 041: Position AI scan tracking + match_source on position_candidates
-- Tracks each auto-scan (queued/running/done/error), exposed via /api/positions/{slug}/ai

CREATE TABLE IF NOT EXISTS position_ai_scans (
  id SERIAL PRIMARY KEY,
  position_id INT NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'queued',
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  n_scored INT DEFAULT 0,
  n_matched INT DEFAULT 0,
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pas_position ON position_ai_scans(position_id, created_at DESC);

ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS match_source TEXT DEFAULT 'manual';
