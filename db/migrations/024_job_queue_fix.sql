-- 024: job_queue schema align with backend.core.job_queue.py expectations

ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS job_type      TEXT;
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS max_attempts  INT DEFAULT 3;
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS result        JSONB;
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS error         TEXT;
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS completed_at  TIMESTAMPTZ;

-- Backfill job_type from old `kind` column where missing
UPDATE job_queue SET job_type = kind WHERE job_type IS NULL AND kind IS NOT NULL;
