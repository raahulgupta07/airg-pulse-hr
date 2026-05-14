-- 004: tables missing from init.sql

CREATE TABLE IF NOT EXISTS automation_rules (
    id SERIAL PRIMARY KEY,
    position_id INT,
    name TEXT NOT NULL,
    trigger_event TEXT NOT NULL,
    conditions JSONB DEFAULT '{}',
    action_type TEXT NOT NULL,
    action_config JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    run_count INT DEFAULT 0,
    last_run_at TIMESTAMPTZ,
    created_by INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_automation_rules_pos ON automation_rules(position_id);
CREATE INDEX IF NOT EXISTS idx_automation_rules_trigger ON automation_rules(trigger_event);

CREATE TABLE IF NOT EXISTS candidate_pools (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_by INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pool_members (
    pool_id INT REFERENCES candidate_pools(id) ON DELETE CASCADE,
    candidate_id INT REFERENCES candidates(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (pool_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS eeo_data (
    id SERIAL PRIMARY KEY,
    candidate_id INT UNIQUE REFERENCES candidates(id) ON DELETE CASCADE,
    gender TEXT,
    ethnicity TEXT,
    veteran_status TEXT,
    disability_status TEXT,
    voluntarily_provided BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_sequences (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    position_id INT,
    steps JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_by INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INT,
    type TEXT NOT NULL,
    title TEXT,
    message TEXT,
    link TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notif_user_read ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notif_created ON notifications(created_at DESC);

CREATE TABLE IF NOT EXISTS offers (
    id SERIAL PRIMARY KEY,
    position_id INT,
    candidate_id INT,
    salary_amount NUMERIC,
    salary_currency TEXT DEFAULT 'USD',
    salary_period TEXT DEFAULT 'annual',
    equity TEXT,
    bonus NUMERIC,
    start_date DATE,
    expiry_date DATE,
    benefits TEXT,
    notes TEXT,
    status TEXT DEFAULT 'draft',
    approval_chain JSONB DEFAULT '[]',
    created_by INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (position_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS position_templates (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT,
    department TEXT,
    employment_type TEXT DEFAULT 'full_time',
    jd_text TEXT,
    required_skills TEXT[] DEFAULT '{}',
    nice_to_have_skills TEXT[] DEFAULT '{}',
    min_experience_years INT DEFAULT 0,
    weight_skills NUMERIC DEFAULT 0.4,
    weight_experience NUMERIC DEFAULT 0.25,
    weight_education NUMERIC DEFAULT 0.10,
    weight_certifications NUMERIC DEFAULT 0.10,
    weight_industry NUMERIC DEFAULT 0.15,
    created_by INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id SERIAL PRIMARY KEY,
    user_id INT,
    name TEXT NOT NULL,
    filters JSONB DEFAULT '{}',
    notify_on_match BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_saved_searches_user ON saved_searches(user_id);

CREATE TABLE IF NOT EXISTS sla_rules (
    id SERIAL PRIMARY KEY,
    position_id INT,
    stage TEXT NOT NULL,
    max_days INT NOT NULL,
    alert_days INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
