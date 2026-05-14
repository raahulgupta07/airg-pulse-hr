-- Real-time JD enrichment via LISTEN/NOTIFY
-- Replaces 5-min polling with instant trigger-based notification.
-- Listener: backend/agents/jd_enrich_listener.py

-- ---------------------------------------------------------------------------
-- 1. Notify function — fires when a JD has text but is missing structured fields
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION notify_jd_needs_enrich() RETURNS TRIGGER AS $$
BEGIN
    -- Only emit if jd_text is substantive AND at least one structured field is empty
    IF NEW.jd_text IS NOT NULL
       AND length(NEW.jd_text) > 50
       AND (
            COALESCE(NEW.department, '') = ''
            OR COALESCE(NEW.seniority_level, '') = ''
            OR NEW.min_experience_years IS NULL
            OR NEW.min_experience_years = 0
            OR NEW.required_skills IS NULL
            OR cardinality(NEW.required_skills) = 0
            OR NEW.nice_to_have_skills IS NULL
            OR cardinality(NEW.nice_to_have_skills) = 0
       )
    THEN
        PERFORM pg_notify('jd_enrich_needed', NEW.id::text);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- 2. Trigger on jd_repository
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_jd_needs_enrich ON jd_repository;

CREATE TRIGGER trg_jd_needs_enrich
AFTER INSERT OR UPDATE OF jd_text, department, seniority_level,
                          min_experience_years, required_skills, nice_to_have_skills
ON jd_repository
FOR EACH ROW
EXECUTE FUNCTION notify_jd_needs_enrich();

-- ---------------------------------------------------------------------------
-- 3. One-shot backfill — emit NOTIFY for already-existing rows that need enrichment
--    Listener may not be connected at this moment; that's OK — fallback poll catches them.
--    But if listener is up (re-runs / hot path), they get processed instantly.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    r RECORD;
    n INT := 0;
BEGIN
    FOR r IN
        SELECT id FROM jd_repository
        WHERE jd_text IS NOT NULL
          AND length(jd_text) > 50
          AND COALESCE(status, 'active') = 'active'
          AND (
               COALESCE(department, '') = ''
               OR COALESCE(seniority_level, '') = ''
               OR min_experience_years IS NULL
               OR min_experience_years = 0
               OR required_skills IS NULL
               OR cardinality(required_skills) = 0
               OR nice_to_have_skills IS NULL
               OR cardinality(nice_to_have_skills) = 0
          )
        ORDER BY created_at DESC
        LIMIT 500
    LOOP
        PERFORM pg_notify('jd_enrich_needed', r.id::text);
        n := n + 1;
    END LOOP;
    RAISE NOTICE 'jd_enrich backfill: emitted NOTIFY for % rows', n;
END$$;
