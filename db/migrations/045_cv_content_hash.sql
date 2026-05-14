-- 045: CV upload dedup via SHA-256 of file bytes
-- Prevents re-running pipeline on identical content (renamed files, same bytes).

ALTER TABLE candidates ADD COLUMN IF NOT EXISTS cv_content_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_candidates_content_hash
    ON candidates (cv_content_hash)
    WHERE cv_content_hash IS NOT NULL AND status = 'active';
