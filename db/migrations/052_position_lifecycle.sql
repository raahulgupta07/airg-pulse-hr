-- 052_position_lifecycle.sql — Hiring board lifecycle stages

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS lifecycle_stage TEXT DEFAULT 'sourcing',
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- Soft check (skip CHECK constraint to avoid migration repeat errors;
-- enforce in app layer)

-- Backfill from existing status
UPDATE positions
   SET lifecycle_stage = CASE
       WHEN status = 'active'   THEN 'sourcing'
       WHEN status = 'closed'   THEN 'filled'
       WHEN status = 'archived' THEN 'archived'
       ELSE 'sourcing'
   END
 WHERE lifecycle_stage IS NULL OR lifecycle_stage = 'sourcing';

CREATE INDEX IF NOT EXISTS idx_positions_lifecycle_stage ON positions(lifecycle_stage);
