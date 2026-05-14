-- 2026-05-11 — Cookie/email auth columns.
-- Idempotent. Safe to apply on top of existing M2 schema (which already has
-- pass_hash + operator_id; this migration adds the email/password_hash path).

ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP;

-- Default admin user is seeded by backend/scripts/seed_admin.py (uses bcrypt
-- at runtime). We do NOT inline a bcrypt hash here because:
--   (a) bcrypt hashes are unique per-salt and shouldn't be checked into SQL
--   (b) the seed script gates on "no users exist" so it never overwrites
