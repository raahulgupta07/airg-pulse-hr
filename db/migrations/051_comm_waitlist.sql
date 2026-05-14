-- 051_comm_waitlist.sql — Communicate feature waitlist (Phase 0)

CREATE TABLE IF NOT EXISTS comm_waitlist (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE SET NULL,
    feature TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, feature)
);
CREATE INDEX IF NOT EXISTS idx_comm_waitlist_feature ON comm_waitlist(feature);
