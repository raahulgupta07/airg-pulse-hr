-- Agno agent long-term memory store. Per-tenant key/value with
-- optional 1536-dim embedding for semantic recall. UNIQUE(tenant_id,
-- key) enables UPSERT semantics. ivfflat cosine index for fast
-- top-k retrieval. Requires pgvector extension (already enabled in
-- init.sql for HyPE/context embeddings).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS agent_memory (
  id BIGSERIAL PRIMARY KEY,
  tenant_id INT NOT NULL,
  key TEXT NOT NULL,
  value JSONB NOT NULL,
  embedding vector(1536),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  updated_by INT,
  UNIQUE (tenant_id, key)
);
CREATE INDEX IF NOT EXISTS agent_memory_embedding_idx
  ON agent_memory USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
