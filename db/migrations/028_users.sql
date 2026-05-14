-- 028: JWT auth user fields (operator_id, pass_hash, lockout)
-- Creates users table if missing (fresh installs); ALTERs existing tables
-- (legacy installs from 001+006) to add the JWT-auth columns.

CREATE TABLE IF NOT EXISTS users(
  id BIGSERIAL PRIMARY KEY,
  operator_id TEXT UNIQUE NOT NULL,
  pass_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'operator',
  created_at TIMESTAMPTZ DEFAULT now(),
  last_login_at TIMESTAMPTZ,
  failed_login_count INT DEFAULT 0,
  locked_until TIMESTAMPTZ
);

-- Bridge legacy schema (email/password_hash) → new schema (operator_id/pass_hash)
ALTER TABLE users ADD COLUMN IF NOT EXISTS operator_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS pass_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'operator';
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_count INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;

-- Backfill operator_id from email for legacy rows so unique index can apply
UPDATE users SET operator_id = email WHERE operator_id IS NULL AND email IS NOT NULL;
-- Backfill pass_hash from legacy password_hash column where present
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name='users' AND column_name='password_hash') THEN
    EXECUTE 'UPDATE users SET pass_hash = password_hash WHERE pass_hash IS NULL AND password_hash IS NOT NULL';
  END IF;
END$$;

CREATE UNIQUE INDEX IF NOT EXISTS users_operator_id_uidx ON users(operator_id);
CREATE INDEX IF NOT EXISTS users_operator_id_idx ON users(operator_id);
