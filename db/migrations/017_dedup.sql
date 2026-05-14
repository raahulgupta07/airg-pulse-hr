-- 017_dedup.sql — duplicate detection + merge pipeline
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE jd_repository  ADD COLUMN IF NOT EXISTS uuid UUID DEFAULT gen_random_uuid();
ALTER TABLE candidates     ADD COLUMN IF NOT EXISTS uuid UUID DEFAULT gen_random_uuid();
ALTER TABLE positions      ADD COLUMN IF NOT EXISTS uuid UUID DEFAULT gen_random_uuid();

UPDATE candidates    SET uuid = gen_random_uuid() WHERE uuid IS NULL;
UPDATE jd_repository SET uuid = gen_random_uuid() WHERE uuid IS NULL;
UPDATE positions     SET uuid = gen_random_uuid() WHERE uuid IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_uuid ON candidates(uuid);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jd_uuid ON jd_repository(uuid);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pos_uuid ON positions(uuid);

ALTER TABLE candidates    ADD COLUMN IF NOT EXISTS merged_into INT;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS merged_into INT;

CREATE TABLE IF NOT EXISTS merge_proposals (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    winner_id INT NOT NULL,
    loser_id INT NOT NULL,
    confidence NUMERIC,
    method TEXT,
    diff JSONB DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    decided_by INT,
    decided_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_merge_status ON merge_proposals(status);
CREATE INDEX IF NOT EXISTS idx_merge_entity ON merge_proposals(entity_type, winner_id, loser_id);

CREATE TABLE IF NOT EXISTS not_duplicates (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    a_id INT NOT NULL,
    b_id INT NOT NULL,
    decided_by INT,
    decided_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notdup_unique
    ON not_duplicates(entity_type, LEAST(a_id,b_id), GREATEST(a_id,b_id));

CREATE TABLE IF NOT EXISTS merge_fk_history (
    id SERIAL PRIMARY KEY,
    proposal_id INT REFERENCES merge_proposals(id) ON DELETE CASCADE,
    table_name TEXT,
    fk_column TEXT,
    row_id INT,
    old_value INT,
    new_value INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fk_hist_proposal ON merge_fk_history(proposal_id);
