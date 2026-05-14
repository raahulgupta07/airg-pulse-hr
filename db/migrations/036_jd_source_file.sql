-- 036: Add source file tracking to JD repository
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS source_file_path TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS source_file_name TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS source_file_type TEXT;
