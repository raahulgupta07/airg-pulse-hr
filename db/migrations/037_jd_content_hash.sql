-- 037: Content hash for JD dedup
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS jd_content_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_jd_content_hash ON jd_repository(jd_content_hash) WHERE status = 'active';
