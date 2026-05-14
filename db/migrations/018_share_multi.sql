-- 018: multi-select share (sector + global at the same time)

ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS shared_sector BOOLEAN DEFAULT FALSE;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS shared_global BOOLEAN DEFAULT FALSE;
ALTER TABLE candidates    ADD COLUMN IF NOT EXISTS shared_sector BOOLEAN DEFAULT FALSE;
ALTER TABLE candidates    ADD COLUMN IF NOT EXISTS shared_global BOOLEAN DEFAULT FALSE;

-- Backfill from existing visibility enum
UPDATE jd_repository SET shared_sector = TRUE WHERE visibility = 'sector';
UPDATE jd_repository SET shared_global = TRUE WHERE visibility = 'global';
UPDATE candidates    SET shared_sector = TRUE WHERE visibility = 'sector';
UPDATE candidates    SET shared_global = TRUE WHERE visibility = 'global';

CREATE INDEX IF NOT EXISTS idx_jd_shared_sector ON jd_repository(shared_sector);
CREATE INDEX IF NOT EXISTS idx_jd_shared_global ON jd_repository(shared_global);
CREATE INDEX IF NOT EXISTS idx_cand_shared_sector ON candidates(shared_sector);
CREATE INDEX IF NOT EXISTS idx_cand_shared_global ON candidates(shared_global);
