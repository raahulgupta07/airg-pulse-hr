-- 044: Interview kit — questions library per position (+ tailored per candidate)
-- Audience: HR_BP / HIRING_MGR / PANEL / TECH
-- Category: BEHAVIORAL / TECHNICAL / CULTURE / ROLE_SPECIFIC / GAP_PROBE / STRENGTH_VERIFY
-- Stage: SCREEN / TECH / ONSITE / FINAL
-- Source: ai_generic / ai_tailored / manual

CREATE TABLE IF NOT EXISTS interview_questions (
  id SERIAL PRIMARY KEY,
  position_id INT NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
  candidate_id INT REFERENCES candidates(id) ON DELETE CASCADE,
  audience TEXT NOT NULL DEFAULT 'HR_BP',
  category TEXT NOT NULL DEFAULT 'BEHAVIORAL',
  stage TEXT NOT NULL DEFAULT 'SCREEN',
  question TEXT NOT NULL,
  look_for TEXT[] DEFAULT '{}',
  red_flags TEXT[] DEFAULT '{}',
  source TEXT NOT NULL DEFAULT 'ai_generic',
  used BOOLEAN DEFAULT FALSE,
  used_at TIMESTAMPTZ,
  created_by INT REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_iq_pos ON interview_questions(position_id, candidate_id, audience, stage);
CREATE INDEX IF NOT EXISTS ix_iq_pos_generic ON interview_questions(position_id) WHERE candidate_id IS NULL;
