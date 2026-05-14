-- 012: scoring weights on JD + position alignment

-- JD weights
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS weight_skills NUMERIC DEFAULT 40;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS weight_experience NUMERIC DEFAULT 25;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS weight_industry NUMERIC DEFAULT 15;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS weight_education NUMERIC DEFAULT 10;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS weight_certifications NUMERIC DEFAULT 10;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS weight_culture NUMERIC DEFAULT 0;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS knockout_threshold NUMERIC DEFAULT 0;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS scoring_profile TEXT DEFAULT 'engineering';

-- Position weights — additions
ALTER TABLE positions ADD COLUMN IF NOT EXISTS weight_culture NUMERIC DEFAULT 0;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS knockout_threshold NUMERIC DEFAULT 0;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS scoring_profile TEXT;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS weights_overridden BOOLEAN DEFAULT FALSE;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS weights_source_jd_id INT;
