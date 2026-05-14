-- 025_facet_options.sql
-- Self-growing AI filter facet system: AI-mined skills/companies/locations/etc.
-- Each unique normalized value becomes a left-rail filter option with NEW badge.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS facet_options (
  id           serial PRIMARY KEY,
  facet_type   text NOT NULL,    -- skill | company | location | language | cert | education
  value        text NOT NULL,
  canonical    text NOT NULL,
  source       text DEFAULT 'ai',
  count        int  DEFAULT 0,
  is_new       bool DEFAULT TRUE,
  added_at     timestamptz DEFAULT NOW(),
  updated_at   timestamptz DEFAULT NOW(),
  UNIQUE(facet_type, canonical)
);

CREATE INDEX IF NOT EXISTS idx_facet_type_count ON facet_options(facet_type, count DESC);
CREATE INDEX IF NOT EXISTS idx_facet_is_new    ON facet_options(is_new) WHERE is_new = TRUE;
CREATE INDEX IF NOT EXISTS idx_facet_canon_trgm ON facet_options USING GIN (canonical gin_trgm_ops);
