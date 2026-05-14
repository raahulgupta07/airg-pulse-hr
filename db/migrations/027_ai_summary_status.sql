-- Migration 027: track AI summary generation status so Step 13 failures
-- in cv_pipeline don't break uploads. Values: 'pending' | 'ready' | 'failed'.
ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS ai_summary_status TEXT DEFAULT 'pending';

CREATE INDEX IF NOT EXISTS idx_candidates_ai_summary_status
    ON candidates(ai_summary_status);
