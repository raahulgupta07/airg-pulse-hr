-- 049_user_notif_prefs.sql — per-user notification preferences (free-form JSON)
ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_prefs JSONB DEFAULT '{}'::jsonb;
