-- 010: track who last modified jd / candidate

ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS updated_by INT;
ALTER TABLE candidates    ADD COLUMN IF NOT EXISTS updated_by INT;

-- Backfill: set updated_by = creator/owner so existing rows show something
UPDATE jd_repository SET updated_by = created_by WHERE updated_by IS NULL;
UPDATE candidates    SET updated_by = owner_id   WHERE updated_by IS NULL;

CREATE INDEX IF NOT EXISTS idx_jd_updated_by   ON jd_repository(updated_by);
CREATE INDEX IF NOT EXISTS idx_cand_updated_by ON candidates(updated_by);

-- Trigger: auto-stamp updated_at on UPDATE (already exists in some tables; add if missing)
CREATE OR REPLACE FUNCTION trg_set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS jd_updated_at ON jd_repository;
CREATE TRIGGER jd_updated_at BEFORE UPDATE ON jd_repository
  FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

DROP TRIGGER IF EXISTS cand_updated_at ON candidates;
CREATE TRIGGER cand_updated_at BEFORE UPDATE ON candidates
  FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
