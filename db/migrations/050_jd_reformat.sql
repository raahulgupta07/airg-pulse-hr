-- 050_jd_reformat.sql
-- Auto-reformat JD layout on upload — preserves wording, restructures markdown.
-- Adds raw-text backup + source-tracking columns.

ALTER TABLE jd_repository
    ADD COLUMN IF NOT EXISTS jd_text_raw TEXT,
    ADD COLUMN IF NOT EXISTS jd_text_source TEXT DEFAULT 'raw',
    ADD COLUMN IF NOT EXISTS reformat_quality_score REAL;

-- jd_text_source values:
--   raw            — pasted/uploaded as-is, no processing
--   extracted      — docx/pdf extractor output (no AI)
--   ai_reformatted — Lite-model layout-only restructure (preserves wording)
--   ai_enhanced    — Flash/Sonnet rewrite (changes wording, scores added)

COMMENT ON COLUMN jd_repository.jd_text_raw IS 'Original pre-reformat text. Reverting restores from here.';
COMMENT ON COLUMN jd_repository.jd_text_source IS 'raw / extracted / ai_reformatted / ai_enhanced';
COMMENT ON COLUMN jd_repository.reformat_quality_score IS 'Structure score 0-1 of jd_text. Below 0.5 triggered reformat.';
