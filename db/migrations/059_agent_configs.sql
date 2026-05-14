-- 059: Per-agent admin-controlled config (enabled, interval, thresholds).
-- Read by agent loops at start of each cycle for runtime gating.

CREATE TABLE IF NOT EXISTS agent_configs (
    agent_id          TEXT PRIMARY KEY,
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    interval_seconds  INTEGER,
    thresholds        JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by_id     INTEGER REFERENCES users(id) ON DELETE SET NULL
);

-- Seed all known agent ids (registry + extra ids from spec). Idempotent.
INSERT INTO agent_configs (agent_id, enabled, interval_seconds, thresholds) VALUES
    ('match',            TRUE, NULL, '{}'::jsonb),
    ('sweeper',          TRUE,  300, '{}'::jsonb),
    ('jd-field-poll',    TRUE,   60, '{}'::jsonb),
    ('jd-field-realtime',TRUE, NULL, '{}'::jsonb),
    ('pipeline',         TRUE, NULL, '{}'::jsonb),
    ('scan',             TRUE, NULL, '{}'::jsonb),
    ('reformat',         TRUE, NULL, '{}'::jsonb),
    ('backup',           TRUE, 86400,'{}'::jsonb),
    ('jd-bias',          TRUE, NULL, '{}'::jsonb),
    ('jd-refresh',       TRUE, NULL, '{}'::jsonb),
    ('jd-translator',    TRUE, NULL, '{}'::jsonb),
    ('jd-completeness',  TRUE, NULL, '{}'::jsonb),
    ('brain-trainer',    TRUE, NULL, '{}'::jsonb),
    ('doc-ingestor',     TRUE, NULL, '{}'::jsonb),
    ('qa-suggester',     TRUE, NULL, '{}'::jsonb),
    ('faq-builder',      TRUE, NULL, '{}'::jsonb)
ON CONFLICT (agent_id) DO NOTHING;
