-- 058 — brain agents tables (Brain Trainer, Document Ingestor, Q&A Suggester, FAQ Builder)

-- Org Brain knowledge store (chunked + embedded HR docs)
CREATE TABLE IF NOT EXISTS org_brain (
    id SERIAL PRIMARY KEY,
    source_doc_id INT,
    chunk_text TEXT NOT NULL,
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_org_brain_source ON org_brain(source_doc_id);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_org_brain_embedding_hnsw') THEN
        BEGIN
            EXECUTE 'CREATE INDEX idx_org_brain_embedding_hnsw ON org_brain USING hnsw (embedding vector_cosine_ops)';
        EXCEPTION WHEN OTHERS THEN
            -- HNSW not available (older pgvector); fallback ivfflat or skip
            NULL;
        END;
    END IF;
END $$;

-- Brain Trainer: log of unanswered/low-confidence Copilot questions
CREATE TABLE IF NOT EXISTS brain_unanswered (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    session_id INT,
    asked_at TIMESTAMPTZ DEFAULT NOW(),
    addressed BOOLEAN DEFAULT FALSE,
    addressed_at TIMESTAMPTZ,
    addressed_by_id INT
);
CREATE INDEX IF NOT EXISTS idx_brain_unanswered_addressed ON brain_unanswered(addressed, asked_at DESC);

-- Doc Ingestor: queue of admin-uploaded HR policy documents
CREATE TABLE IF NOT EXISTS org_brain_uploads (
    id SERIAL PRIMARY KEY,
    file_path TEXT NOT NULL,
    uploaded_by_id INT,
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'pending',
    chunks_created INT DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_org_brain_uploads_status ON org_brain_uploads(status, uploaded_at);

-- Q&A Suggester: queue of recruiter-opened candidate-position drawer pairs
CREATE TABLE IF NOT EXISTS qa_suggestion_queue (
    id SERIAL PRIMARY KEY,
    candidate_id INT NOT NULL,
    position_id INT NOT NULL,
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    fulfilled BOOLEAN DEFAULT FALSE,
    suggestions JSONB
);
CREATE INDEX IF NOT EXISTS idx_qa_queue_pending ON qa_suggestion_queue(fulfilled, requested_at);
CREATE INDEX IF NOT EXISTS idx_qa_queue_pair ON qa_suggestion_queue(candidate_id, position_id, requested_at DESC);

-- FAQ Builder: clustered canonical FAQs
CREATE TABLE IF NOT EXISTS faq_entries (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    cluster_size INT DEFAULT 1,
    last_built_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_faq_built ON faq_entries(last_built_at DESC);
