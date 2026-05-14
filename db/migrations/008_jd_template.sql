-- 008: align jd_repository with corporate JD template

ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS job_code TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS business_sector TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS grading TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS reporting_to TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS location TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS work_mode TEXT;        -- remote / hybrid / onsite
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS job_purpose TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS preferred_education TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS travel_requirement TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS physical_conditions TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS equal_opportunity TEXT DEFAULT
  'We are an equal opportunity employer. All qualified applicants will receive consideration without regard to race, color, religion, sex, sexual orientation, gender identity, national origin, disability, or veteran status.';
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS doc_version TEXT DEFAULT '1.0';
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS doc_owner TEXT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS doc_last_review DATE;
