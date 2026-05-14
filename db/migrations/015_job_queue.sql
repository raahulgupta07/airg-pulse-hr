-- 015: job queue + auto-sync flags

CREATE TABLE IF NOT EXISTS job_queue (
    id SERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    attempts INT DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_job_status_kind ON job_queue(status, kind);
CREATE INDEX IF NOT EXISTS idx_job_created ON job_queue(created_at DESC);

INSERT INTO system_flags (key, value, description) VALUES
    ('auto_scan_on_position_create', 'true'::jsonb, 'Scan repo for matches on position create'),
    ('auto_match_on_cv_upload',      'true'::jsonb, 'Match new CV against open positions'),
    ('auto_rescore_on_weight_change','true'::jsonb, 'Rescore attached candidates on weight change')
ON CONFLICT (key) DO NOTHING;
