-- Prevent multiple concurrent scans for the same position.
-- Partial unique index: only one queued/running scan allowed at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_pas_active
  ON position_ai_scans(position_id)
  WHERE status IN ('queued', 'running');
