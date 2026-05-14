-- Migration 026: cache AI executive summary on candidate (auto-generated at upload)
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS ai_summary TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS ai_summary_generated_at TIMESTAMPTZ;
