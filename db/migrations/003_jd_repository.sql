-- 003: jd_repository table (missing from init.sql)

CREATE TABLE IF NOT EXISTS jd_repository (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    department TEXT,
    seniority_level TEXT,
    employment_type TEXT DEFAULT 'full_time',
    jd_text TEXT NOT NULL,
    required_skills TEXT[] DEFAULT '{}',
    nice_to_have_skills TEXT[] DEFAULT '{}',
    min_experience_years INT DEFAULT 0,
    education_level TEXT DEFAULT '',
    industry_keywords TEXT[] DEFAULT '{}',
    required_certifications TEXT[] DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    status TEXT DEFAULT 'active',
    used_count INT DEFAULT 0,
    jd_enhanced BOOLEAN DEFAULT FALSE,
    dei_score NUMERIC,
    legal_check JSONB,
    completeness_score NUMERIC,
    created_by INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jd_repo_status ON jd_repository(status);
CREATE INDEX IF NOT EXISTS idx_jd_repo_updated ON jd_repository(updated_at DESC);
