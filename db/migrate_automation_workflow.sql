-- Migration: Automation & Workflow tables
-- Run with: /opt/homebrew/Cellar/postgresql@18/18.2/bin/psql -h localhost -U hire -d hiredb -f db/migrate_automation_workflow.sql

CREATE TABLE IF NOT EXISTS automation_rules (
    id SERIAL PRIMARY KEY,
    position_id INTEGER REFERENCES positions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    trigger_event TEXT NOT NULL,
    conditions JSONB DEFAULT '{}',
    action_type TEXT NOT NULL,
    action_config JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    execution_count INTEGER DEFAULT 0,
    last_executed_at TIMESTAMP,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_automation_rules_position ON automation_rules(position_id);
CREATE INDEX IF NOT EXISTS idx_automation_rules_trigger ON automation_rules(trigger_event);

CREATE TABLE IF NOT EXISTS email_sequences (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    position_id INTEGER REFERENCES positions(id) ON DELETE CASCADE,
    steps JSONB NOT NULL DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_sequence_enrollments (
    id SERIAL PRIMARY KEY,
    sequence_id INTEGER REFERENCES email_sequences(id) ON DELETE CASCADE,
    candidate_id INTEGER REFERENCES candidates(id) ON DELETE CASCADE,
    current_step INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    next_send_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(sequence_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS sla_rules (
    id SERIAL PRIMARY KEY,
    position_id INTEGER REFERENCES positions(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    max_days INTEGER NOT NULL,
    alert_days INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS approval_chains (
    id SERIAL PRIMARY KEY,
    offer_id INTEGER REFERENCES offers(id) ON DELETE CASCADE,
    approver_id INTEGER REFERENCES users(id),
    step_order INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    approved_at TIMESTAMP,
    rejected_at TIMESTAMP,
    comments TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS interview_stages (
    id SERIAL PRIMARY KEY,
    position_id INTEGER REFERENCES positions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    stage_order INTEGER NOT NULL,
    interview_type TEXT DEFAULT 'video',
    duration_minutes INTEGER DEFAULT 60,
    description TEXT,
    required_scorecards INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW()
);
