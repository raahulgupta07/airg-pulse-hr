-- 054_position_candidate_state.sql
-- Split position_candidates rows into 'suggested' vs 'attached' vs 'rejected' states.
-- AI Scan Agent now writes 'suggested'; user explicitly promotes to 'attached'.

ALTER TABLE position_candidates
    ADD COLUMN IF NOT EXISTS attachment_state TEXT DEFAULT 'attached';

-- Backfill: rows from auto-scan that were never moved past 'uploaded' = suggestions
UPDATE position_candidates
   SET attachment_state = 'suggested'
 WHERE attachment_state = 'attached'
   AND auto_added = TRUE
   AND COALESCE(stage, 'uploaded') = 'uploaded';

-- Rejected stage rows get explicit state too
UPDATE position_candidates
   SET attachment_state = 'rejected'
 WHERE COALESCE(stage, '') = 'rejected'
   AND attachment_state = 'attached';

CREATE INDEX IF NOT EXISTS idx_pc_attachment_state ON position_candidates(attachment_state);

COMMENT ON COLUMN position_candidates.attachment_state IS
    'suggested = AI scan output, awaiting review · attached = user-confirmed in pipeline · rejected = dismissed';
