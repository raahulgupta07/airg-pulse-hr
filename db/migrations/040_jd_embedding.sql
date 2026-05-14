-- 040: JD body embeddings (semantic search + better CV↔JD matching)
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS jd_embedding vector(1536);
ALTER TABLE jd_repository ADD COLUMN IF NOT EXISTS jd_embed_hash TEXT;
-- HNSW for cosine similarity (fast ANN)
CREATE INDEX IF NOT EXISTS idx_jd_embedding ON jd_repository USING hnsw (jd_embedding vector_cosine_ops);
