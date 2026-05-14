-- 057: JD agents — bias detection, translations, completeness scoring

ALTER TABLE jd_repository
    ADD COLUMN IF NOT EXISTS bias_report JSONB,
    ADD COLUMN IF NOT EXISTS translate_to TEXT[] DEFAULT '{}';

-- completeness_score already exists as NUMERIC in mig 003 — reuse.
-- Ensure it can hold INT 0-100 (NUMERIC handles fine).

CREATE TABLE IF NOT EXISTS jd_translations (
    id SERIAL PRIMARY KEY,
    jd_id INT NOT NULL REFERENCES jd_repository(id) ON DELETE CASCADE,
    lang TEXT NOT NULL,
    body TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(jd_id, lang)
);

CREATE INDEX IF NOT EXISTS idx_jd_translations_jd ON jd_translations(jd_id);
CREATE INDEX IF NOT EXISTS idx_jd_repo_bias ON jd_repository((bias_report IS NOT NULL));
CREATE INDEX IF NOT EXISTS idx_jd_repo_translate_to ON jd_repository USING GIN(translate_to);
