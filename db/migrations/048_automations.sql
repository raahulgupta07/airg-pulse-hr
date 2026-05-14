-- 048_automations.sql — workflow builder rules (frontend WorkflowsPanel shape)
-- Spec table per task. The pre-existing automation_rules table (from earlier
-- engine) carries trigger_event/conditions/action_type/action_config columns.
-- We extend it (additive) with the new shape so both worlds coexist:
--   - existing rule-engine code (check_automation_rules) keeps reading
--     trigger_event/conditions/action_type/action_config/is_active
--   - the new /api/automations CRUD reads/writes
--     trigger/condition/action/enabled

CREATE TABLE IF NOT EXISTS automation_rules (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  trigger TEXT NOT NULL,
  condition JSONB,
  action JSONB NOT NULL,
  enabled BOOLEAN DEFAULT TRUE,
  created_by INTEGER REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Additive columns when table pre-exists with the older schema.
ALTER TABLE automation_rules ADD COLUMN IF NOT EXISTS trigger    TEXT;
ALTER TABLE automation_rules ADD COLUMN IF NOT EXISTS condition  JSONB;
ALTER TABLE automation_rules ADD COLUMN IF NOT EXISTS action     JSONB;
ALTER TABLE automation_rules ADD COLUMN IF NOT EXISTS enabled    BOOLEAN DEFAULT TRUE;

-- Backfill from legacy columns where present, so old rows render in the UI.
UPDATE automation_rules
   SET trigger = COALESCE(trigger, trigger_event)
 WHERE trigger IS NULL;

UPDATE automation_rules
   SET condition = COALESCE(condition, conditions)
 WHERE condition IS NULL;

UPDATE automation_rules
   SET action = COALESCE(
         action,
         jsonb_build_object('type', action_type, 'payload', COALESCE(action_config::text, ''))
       )
 WHERE action IS NULL;

UPDATE automation_rules
   SET enabled = COALESCE(enabled, is_active, TRUE)
 WHERE enabled IS NULL;

CREATE INDEX IF NOT EXISTS idx_automation_rules_trigger_new ON automation_rules(trigger);
CREATE INDEX IF NOT EXISTS idx_automation_rules_enabled    ON automation_rules(enabled);
