-- 056: Seed default retention/expiry settings into app_settings.
-- Read via backend.core.expiry.get_default_expiry_days(kind).

INSERT INTO app_settings (key, value)
VALUES ('expiry_defaults', '{"cv_days": 90, "jd_days": 90}'::jsonb)
ON CONFLICT (key) DO NOTHING;
