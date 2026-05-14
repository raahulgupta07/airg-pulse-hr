-- 007: admin console schema

CREATE TABLE IF NOT EXISTS roles (
    name TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    permissions JSONB DEFAULT '{}',
    is_system BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS permissions_catalog (
    key TEXT PRIMARY KEY,
    description TEXT,
    category TEXT
);

CREATE TABLE IF NOT EXISTS ai_usage (
    id BIGSERIAL PRIMARY KEY,
    user_id INT,
    model TEXT,
    feature TEXT,
    tokens_in INT DEFAULT 0,
    tokens_out INT DEFAULT 0,
    cost_usd NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_usage_user ON ai_usage(user_id);

CREATE TABLE IF NOT EXISTS system_flags (
    key TEXT PRIMARY KEY,
    value JSONB DEFAULT '{}',
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by INT
);

-- Permission catalog
INSERT INTO permissions_catalog (key, description, category) VALUES
    ('candidates.view',     'View candidates',          'candidates'),
    ('candidates.upload',   'Upload CVs',               'candidates'),
    ('candidates.delete',   'Delete candidates',        'candidates'),
    ('positions.view',      'View positions',           'positions'),
    ('positions.create',    'Create positions',         'positions'),
    ('positions.delete',    'Delete positions',         'positions'),
    ('jds.view',            'View JD repository',       'jds'),
    ('jds.generate',        'AI-generate JDs',          'jds'),
    ('offers.create',       'Create offers',            'offers'),
    ('offers.approve',      'Approve offers',           'offers'),
    ('analytics.view',      'View analytics',           'analytics'),
    ('admin.access',        'Access admin console',     'admin'),
    ('admin.users',         'Manage users',             'admin'),
    ('admin.roles',         'Manage roles',             'admin'),
    ('admin.audit',         'View audit log',           'admin'),
    ('admin.system',        'System settings',          'admin')
ON CONFLICT (key) DO NOTHING;

-- Default roles
INSERT INTO roles (name, label, permissions, is_system) VALUES
    ('admin',       'Administrator', '{"all": true}',                                            TRUE),
    ('hm',          'Hiring Manager','{"keys":["candidates.view","candidates.upload","positions.view","positions.create","jds.view","jds.generate","offers.create","offers.approve","analytics.view"]}', TRUE),
    ('recruiter',   'Recruiter',     '{"keys":["candidates.view","candidates.upload","positions.view","positions.create","jds.view","jds.generate","offers.create","analytics.view"]}', TRUE),
    ('interviewer', 'Interviewer',   '{"keys":["candidates.view","positions.view","jds.view"]}', TRUE)
ON CONFLICT (name) DO NOTHING;

-- Default flags
INSERT INTO system_flags (key, value, description) VALUES
    ('maintenance_mode', 'false'::jsonb, 'Block non-admin requests'),
    ('require_2fa',      'false'::jsonb, 'Require 2FA for login'),
    ('rate_limit_on',    'true'::jsonb,  'Enable rate limiting'),
    ('ai_features_on',   'true'::jsonb,  'Enable AI features'),
    ('feature_positions',  'true'::jsonb, 'Show Positions nav'),
    ('feature_jds',        'true'::jsonb, 'Show JD Repo nav'),
    ('feature_candidates', 'true'::jsonb, 'Show CV Repo nav'),
    ('feature_analytics',  'true'::jsonb, 'Show Analytics nav'),
    ('feature_interviews', 'true'::jsonb, 'Show Interviews nav'),
    ('feature_pools',      'true'::jsonb, 'Show Pools nav'),
    ('feature_chat',       'true'::jsonb, 'Show HR Brain nav')
ON CONFLICT (key) DO NOTHING;

-- audit_log enhancements
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip_address TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_agent TEXT;

-- ensure dev user is admin
UPDATE users SET role = 'admin' WHERE id = 1 AND role IS DISTINCT FROM 'admin';
