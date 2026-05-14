-- 016_analytics.sql — Analytics extensions for funnel/cohort, scorecards, DEI,
-- cost-per-hire, quality-of-hire, predictive (likelihood-to-hire + forecasts).

-- ---------------------------------------------------------------------------
-- 1. UTM + applied_at on candidates
-- ---------------------------------------------------------------------------
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS utm_source TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS utm_campaign TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS utm_medium TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_candidates_utm_source ON candidates(utm_source);
CREATE INDEX IF NOT EXISTS idx_candidates_applied_at ON candidates(applied_at);

-- ---------------------------------------------------------------------------
-- 2. Stage history on position_candidates + auto-append trigger
-- ---------------------------------------------------------------------------
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS stage_history JSONB DEFAULT '[]'::jsonb;

CREATE OR REPLACE FUNCTION fn_pc_stage_history() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.stage_history := COALESCE(NEW.stage_history, '[]'::jsonb)
            || jsonb_build_array(jsonb_build_object(
                'stage', NEW.stage,
                'at', to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            ));
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' AND COALESCE(NEW.stage, '') <> COALESCE(OLD.stage, '') THEN
        NEW.stage_history := COALESCE(OLD.stage_history, '[]'::jsonb)
            || jsonb_build_array(jsonb_build_object(
                'stage', NEW.stage,
                'from', OLD.stage,
                'at', to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            ));
        RETURN NEW;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_pc_stage_history ON position_candidates;
CREATE TRIGGER trg_pc_stage_history
    BEFORE INSERT OR UPDATE OF stage ON position_candidates
    FOR EACH ROW EXECUTE FUNCTION fn_pc_stage_history();

-- ---------------------------------------------------------------------------
-- 3. Quality of hire reviews
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qoh_reviews (
    id SERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    position_id INTEGER REFERENCES positions(id) ON DELETE SET NULL,
    hired_at TIMESTAMPTZ,
    review_at TIMESTAMPTZ DEFAULT NOW(),
    period TEXT,                    -- '90d' | '180d' | '360d'
    manager_rating NUMERIC,         -- 1..5
    retained BOOLEAN,
    notes TEXT,
    submitted_by INTEGER REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qoh_candidate ON qoh_reviews(candidate_id);
CREATE INDEX IF NOT EXISTS idx_qoh_period    ON qoh_reviews(period);
CREATE INDEX IF NOT EXISTS idx_qoh_hired_at  ON qoh_reviews(hired_at);

-- ---------------------------------------------------------------------------
-- 4. Recruitment costs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recruitment_costs (
    id SERIAL PRIMARY KEY,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    category TEXT NOT NULL,         -- 'job_board', 'agency', 'referral_bonus', 'tooling', 'salary', 'other'
    channel TEXT,                   -- 'linkedin', 'indeed', 'referral', etc.
    amount NUMERIC NOT NULL DEFAULT 0,
    currency TEXT DEFAULT 'USD',
    position_id INTEGER REFERENCES positions(id) ON DELETE SET NULL,
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_costs_period   ON recruitment_costs(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_costs_channel  ON recruitment_costs(channel);
CREATE INDEX IF NOT EXISTS idx_costs_position ON recruitment_costs(position_id);

-- ---------------------------------------------------------------------------
-- 5. Predictive: likelihood-to-hire & position forecast
-- ---------------------------------------------------------------------------
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS likelihood_to_hire NUMERIC;
ALTER TABLE position_candidates ADD COLUMN IF NOT EXISTS lth_updated_at TIMESTAMPTZ;

ALTER TABLE positions ADD COLUMN IF NOT EXISTS forecast_days_to_fill NUMERIC;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS forecast_confidence NUMERIC;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS forecast_updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_pc_lth ON position_candidates(likelihood_to_hire DESC NULLS LAST);
