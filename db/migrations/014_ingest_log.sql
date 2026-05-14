-- 014: unified ingest log + pending review queue

CREATE TABLE IF NOT EXISTS ingest_log (
    id SERIAL PRIMARY KEY,
    user_id INT,
    filename TEXT,
    file_size INT,
    mime TEXT,
    file_type TEXT,
    file_path TEXT,
    extracted_chars INT,
    classified_as TEXT,
    confidence NUMERIC,
    reason TEXT,
    pipeline TEXT,
    target_type TEXT,
    target_id INT,
    status TEXT DEFAULT 'success',
    error_msg TEXT,
    elapsed_ms INT,
    raw_text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    decided_by INT,
    decided_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ingest_status ON ingest_log(status);
CREATE INDEX IF NOT EXISTS idx_ingest_created ON ingest_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_user ON ingest_log(user_id);
