-- Settings table — persistent, user-tweakable knobs (NOT env vars).
-- Survives container redeploys; backed up via pgdata volume + scripts/backup.sh.
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL,
  scope TEXT NOT NULL DEFAULT 'global',
  description TEXT,
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS settings_scope_idx ON settings(scope);
