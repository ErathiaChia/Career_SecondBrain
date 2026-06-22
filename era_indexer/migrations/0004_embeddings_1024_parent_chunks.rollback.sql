-- Rollback for 0004: revert embeddings to 768-dim + ivfflat and drop
-- parent-child tables. Clears embeddings again (re-embed required).

DROP VIEW IF EXISTS chunks;

DROP INDEX IF EXISTS idx_chunks_parent;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS parent_chunk_id;
DROP TABLE IF EXISTS parent_chunks;

DROP INDEX IF EXISTS idx_chunks_embedding;

ALTER TABLE document_chunks
    ALTER COLUMN embedding TYPE vector(768) USING NULL::vector(768);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE OR REPLACE VIEW chunks AS
SELECT dc.id,
       dc.file_id,
       dc.document_id,
       dc.section_id,
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
