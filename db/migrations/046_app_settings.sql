-- 046: Generic key-value app settings store
-- Used for white-label branding (key='branding') and integration webhooks
-- (key='integration:slack', 'integration:teams', etc).

CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    updated_by  INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_app_settings_key_prefix
    ON app_settings (key text_pattern_ops);
