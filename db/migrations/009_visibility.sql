-- 009: visibility scopes for JDs + Candidates

CREATE TABLE IF NOT EXISTS sectors (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    email_domain TEXT,
    lead_user_id INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO sectors (name, email_domain) VALUES
    ('Default', NULL)
ON CONFLICT (name) DO NOTHING;

ALTER TABLE users ADD COLUMN IF NOT EXISTS sector_id INT REFERENCES sectors(id);

-- backfill: assign Default sector to existing users
UPDATE users SET sector_id = (SELECT id FROM sectors WHERE name = 'Default')
WHERE sector_id IS NULL;

-- jd_repository
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS visibility TEXT DEFAULT 'private';
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS sector_id INT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS published_by INT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

-- candidates
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS visibility TEXT DEFAULT 'private';
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS sector_id INT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS owner_id INT;

-- backfill existing candidates: owner = uploader user, fall back to dev user 1
UPDATE candidates SET owner_id = 1 WHERE owner_id IS NULL;
UPDATE candidates SET sector_id = (SELECT id FROM sectors WHERE name = 'Default') WHERE sector_id IS NULL;
UPDATE jd_repository SET sector_id = (SELECT id FROM sectors WHERE name = 'Default') WHERE sector_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_jd_visibility ON jd_repository(visibility);
CREATE INDEX IF NOT EXISTS idx_jd_sector ON jd_repository(sector_id);
CREATE INDEX IF NOT EXISTS idx_jd_creator ON jd_repository(created_by);
CREATE INDEX IF NOT EXISTS idx_cand_visibility ON candidates(visibility);
CREATE INDEX IF NOT EXISTS idx_cand_sector ON candidates(sector_id);
CREATE INDEX IF NOT EXISTS idx_cand_owner ON candidates(owner_id);

-- Add roles for sector lead and group hr (system roles)
INSERT INTO roles (name, label, permissions, is_system) VALUES
    ('group_hr',    'Group HR',     '{"keys":["candidates.view","candidates.upload","positions.view","jds.view","jds.generate","analytics.view","admin.access"],"can_publish_global":true}', TRUE),
    ('sector_lead', 'Sector Lead',  '{"keys":["candidates.view","candidates.upload","positions.view","positions.create","jds.view","jds.generate","offers.create","analytics.view"],"can_publish_sector":true}', TRUE)
ON CONFLICT (name) DO NOTHING;
