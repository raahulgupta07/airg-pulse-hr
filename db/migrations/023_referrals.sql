-- Referrals table (referenced by candidate_extras.py /referral routes)
CREATE TABLE IF NOT EXISTS referrals (
    id              serial PRIMARY KEY,
    candidate_id    int REFERENCES candidates(id) ON DELETE CASCADE,
    position_id     int REFERENCES positions(id) ON DELETE SET NULL,
    referrer_name   text NOT NULL,
    referrer_email  text,
    referrer_user_id int REFERENCES users(id) ON DELETE SET NULL,
    relationship    text,
    notes           text,
    bonus_amount    numeric(10,2),
    bonus_paid      boolean DEFAULT FALSE,
    status          text DEFAULT 'pending',
    created_at      timestamptz DEFAULT now(),
    updated_at      timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_referrals_candidate ON referrals(candidate_id);
CREATE INDEX IF NOT EXISTS idx_referrals_position  ON referrals(position_id);
