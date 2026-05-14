-- 055: Expiry + Audit columns on candidates and jd_repository.
-- Adds expires_at + created_by_id/updated_by_id audit columns. Backfills expires_at
-- to created_at + 90 days. Pure additive; no data loss.

-- ── candidates ──
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS created_by_id INTEGER REFERENCES users(id);
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS updated_by_id INTEGER REFERENCES users(id);
-- updated_at already exists on candidates (init.sql); ADD IF NOT EXISTS is safe no-op.
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

UPDATE candidates
   SET expires_at = (created_at + INTERVAL '90 days')
 WHERE expires_at IS NULL;

-- Backfill audit cols from existing legacy fields where possible.
UPDATE candidates SET created_by_id = owner_id   WHERE created_by_id IS NULL AND owner_id   IS NOT NULL;
UPDATE candidates SET updated_by_id = updated_by WHERE updated_by_id IS NULL AND updated_by IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_candidates_expires_at ON candidates(expires_at);

-- ── jd_repository ──
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS created_by_id INTEGER REFERENCES users(id);
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS updated_by_id INTEGER REFERENCES users(id);
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

UPDATE jd_repository
   SET expires_at = (created_at + INTERVAL '90 days')
 WHERE expires_at IS NULL;

UPDATE jd_repository SET created_by_id = created_by WHERE created_by_id IS NULL AND created_by IS NOT NULL;
UPDATE jd_repository SET updated_by_id = updated_by WHERE updated_by_id IS NULL AND updated_by IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jd_repository_expires_at ON jd_repository(expires_at);
