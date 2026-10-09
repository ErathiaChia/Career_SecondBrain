-- Career Intelligence Phase 1: per-FILE extraction state + processing versions.
--
-- Why: document-level extraction stored its state in graph_extraction_state
-- keyed by the file's representative CHUNK, and persisted facts/mentions/
-- evidence against that chunk. Two consequences:
--   1. chunk-level graph-refresh and document-level extract-documents shared one
--      row and deleted each other's rows on every version mismatch;
--   2. db.replace_chunks (any re-embed of a modified file) cascade-deleted the
--      facts BEFORE re-extraction, so the fact diff never saw the old facts.
-- Document-scoped rows now carry chunk_id = NULL (nothing to cascade) and their
-- state lives in document_extraction_state keyed by file_id.

CREATE TABLE IF NOT EXISTS document_extraction_state (
    file_id              INTEGER PRIMARY KEY REFERENCES file_registry(id) ON DELETE CASCADE,
    content_hash         TEXT NOT NULL,          -- md5 of the concatenated chunk text
    extractor_version    TEXT NOT NULL,          -- facts/entities prompt version
    intelligence_version TEXT,                   -- document card version; NULL = no card yet
    status               TEXT NOT NULL,          -- done | failed
    error_message        TEXT,
    windows              INTEGER,
    extracted_at         TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_extraction_state_status
    ON document_extraction_state(status);

-- Move existing document-level state rows (rep chunk -> file).
INSERT INTO document_extraction_state
    (file_id, content_hash, extractor_version, status, error_message, extracted_at)
SELECT dc.file_id, ges.content_hash, ges.extractor_version, ges.status, ges.error_message, ges.extracted_at
  FROM graph_extraction_state ges
  JOIN document_chunks dc ON dc.id = ges.chunk_id
 WHERE ges.extractor_version LIKE 'doc-%'
ON CONFLICT (file_id) DO NOTHING;

DELETE FROM graph_extraction_state WHERE extractor_version LIKE 'doc-%';

-- Detach document-scoped graph rows from their representative chunk so a
-- re-embed no longer cascades them away. (Chunk-level extraction is off in
-- practice; any chunk-level rows on these files simply re-extract later.)
UPDATE knowledge_facts kf SET chunk_id = NULL
  FROM document_extraction_state des
 WHERE kf.file_id = des.file_id AND kf.chunk_id IS NOT NULL;

UPDATE entity_mentions em SET chunk_id = NULL
  FROM document_extraction_state des
 WHERE em.file_id = des.file_id AND em.chunk_id IS NOT NULL
   AND em.extractor_version <> 'path-seed-v1';

UPDATE relationship_evidence re SET chunk_id = NULL
  FROM document_extraction_state des
 WHERE re.file_id = des.file_id AND re.chunk_id IS NOT NULL;

-- Brief §5: per-file processing state.
ALTER TABLE file_registry ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
ALTER TABLE file_registry ADD COLUMN IF NOT EXISTS parser_version TEXT;
ALTER TABLE file_registry ADD COLUMN IF NOT EXISTS embedding_model TEXT;
ALTER TABLE file_registry ADD COLUMN IF NOT EXISTS embedding_version TEXT;
ALTER TABLE file_registry ADD COLUMN IF NOT EXISTS intelligence_version TEXT;
ALTER TABLE file_registry ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMP;

UPDATE file_registry fr
   SET embedding_version = s.v,
       indexed_at = COALESCE(fr.indexed_at, fr.last_processed_at)
  FROM (SELECT file_id, max(embedding_content_version) AS v
          FROM document_chunks GROUP BY file_id) s
 WHERE s.file_id = fr.id;

UPDATE file_registry fr
   SET parser_version = a.artifact_version
  FROM processing_artifacts a
 WHERE a.file_id = fr.id
   AND a.artifact_type = 'converted_markdown'
   AND a.source_hash = fr.file_hash
   AND fr.parser_version IS NULL;

-- Extractive summaries accumulated one row per content hash; keep the current one.
DELETE FROM document_summaries ds
 USING file_registry fr
 WHERE fr.id = ds.file_id AND ds.source_hash <> fr.file_hash;
