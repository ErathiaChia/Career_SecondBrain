-- Era Vault: upgrade embeddings to qwen3-embedding:0.6b (1024-dim) with an HNSW
-- add parent-child ("small-to-big") retrieval.
--
-- WARNING: this clears existing 768-dim embeddings (they are incompatible with
-- the new model). A full re-embed is required afterwards; chunk text/rows are
-- preserved but excluded from vector search until re-embedded.

-- The chunks view selects dc.embedding, so it must be dropped before the column
-- type can change, then recreated below.
DROP VIEW IF EXISTS chunks;

DROP INDEX IF EXISTS idx_chunks_embedding;

ALTER TABLE document_chunks
    ALTER COLUMN embedding TYPE vector(1024) USING NULL::vector(1024);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- parent_chunks: the larger "parent" context returned at query time. Children
-- (document_chunks) are embedded for precise matching and point at their parent.
CREATE TABLE IF NOT EXISTS parent_chunks (
    id              SERIAL PRIMARY KEY,
    file_id         INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    section_id      INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
    ordinal         INTEGER NOT NULL DEFAULT 0,
    content         TEXT NOT NULL,
    token_estimate  INTEGER,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parent_chunks_file ON parent_chunks(file_id);

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS parent_chunk_id INTEGER REFERENCES parent_chunks(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_parent ON document_chunks(parent_chunk_id);

CREATE OR REPLACE VIEW chunks AS
SELECT dc.id,
       dc.file_id,
       dc.document_id,
       dc.section_id,
       dc.parent_chunk_id,
       dc.chunk_index,
       COALESCE(dc.raw_content, dc.content_raw, dc.content) AS raw_content,
       COALESCE(dc.contextual_content, dc.content_contextual, dc.content) AS contextual_content,
       dc.content,
       dc.embedding,
       dc.speaker_segment_id,
       dc.metadata,
       dc.chunk_type,
       dc.page_number,
       COALESCE(dc.heading_path, dc.metadata->>'section_path') AS heading_path,
       COALESCE(dc.subsection_title, dc.metadata->>'subsection_title') AS subsection_title,
       dc.token_estimate,
       dc.search_vector
  FROM document_chunks dc;
