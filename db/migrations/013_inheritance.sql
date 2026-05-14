-- 013: tenant + sector weight policy + JD lock

CREATE TABLE IF NOT EXISTS tenant_scoring_policy (
    key TEXT PRIMARY KEY,            -- e.g. 'skills.min', 'skills.max', 'knockout.cap'
    value NUMERIC NOT NULL,
    enforcement TEXT DEFAULT 'clamp',-- 'clamp' | 'block'
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by INT
);

INSERT INTO tenant_scoring_policy (key, value, enforcement) VALUES
    ('skills.min', 0, 'clamp'),
    ('skills.max', 100, 'clamp'),
    ('experience.min', 0, 'clamp'),
    ('experience.max', 100, 'clamp'),
    ('industry.min', 0, 'clamp'),
    ('industry.max', 100, 'clamp'),
    ('education.min', 0, 'clamp'),
    ('education.max', 100, 'clamp'),
    ('certifications.min', 0, 'clamp'),
    ('certifications.max', 100, 'clamp'),
    ('culture.min', 0, 'clamp'),
    ('culture.max', 100, 'clamp'),
    ('knockout.min', 0, 'clamp'),
    ('knockout.max', 100, 'clamp')
ON CONFLICT (key) DO NOTHING;

ALTER TABLE sectors ADD COLUMN IF NOT EXISTS weight_skills NUMERIC;
ALTER TABLE sectors ADD COLUMN IF NOT EXISTS weight_experience NUMERIC;
ALTER TABLE sectors ADD COLUMN IF NOT EXISTS weight_industry NUMERIC;
ALTER TABLE sectors ADD COLUMN IF NOT EXISTS weight_education NUMERIC;
ALTER TABLE sectors ADD COLUMN IF NOT EXISTS weight_certifications NUMERIC;
ALTER TABLE sectors ADD COLUMN IF NOT EXISTS weight_culture NUMERIC;
ALTER TABLE sectors ADD COLUMN IF NOT EXISTS forced_dims JSONB DEFAULT '[]';

ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS weights_locked BOOLEAN DEFAULT FALSE;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS weights_locked_dims JSONB DEFAULT '[]';

-- AI suggestions cache
CREATE TABLE IF NOT EXISTS weight_suggestions (
    id SERIAL PRIMARY KEY,
    position_id INT NOT NULL,
    suggestion_type TEXT,
    description TEXT,
    weights JSONB,
    knockout NUMERIC,
    expected_pass_count INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    dismissed BOOLEAN DEFAULT FALSE,
    applied BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_ws_position ON weight_suggestions(position_id, dismissed, applied);
