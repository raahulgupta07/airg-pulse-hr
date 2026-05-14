-- 011: AI recommendations + dismissal tracking on position_candidates

ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS auto_added BOOLEAN DEFAULT FALSE;
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS ai_recommended BOOLEAN DEFAULT FALSE;
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS dismissed BOOLEAN DEFAULT FALSE;
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS dismissed_by INT;
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMPTZ;
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS dismissal_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_pc_dismissed ON position_candidates(position_id, dismissed);
CREATE INDEX IF NOT EXISTS idx_pc_candidate_active ON position_candidates(candidate_id) WHERE dismissed = FALSE;

-- system flags for auto-scan
INSERT INTO system_flags (key, value, description) VALUES
  ('auto_scan_threshold', '60'::jsonb, 'Min match % to auto-recommend on JD save'),
  ('auto_scan_on_jd_save', 'true'::jsonb, 'Auto-scan repo when JD attached to position')
ON CONFLICT (key) DO NOTHING;
