-- Document-level state is recomputable (extract-documents re-runs); the
-- detached chunk_id links are not restored.
DROP TABLE IF EXISTS document_extraction_state;
ALTER TABLE file_registry DROP COLUMN IF EXISTS size_bytes;
ALTER TABLE file_registry DROP COLUMN IF EXISTS parser_version;
ALTER TABLE file_registry DROP COLUMN IF EXISTS embedding_model;
ALTER TABLE file_registry DROP COLUMN IF EXISTS embedding_version;
ALTER TABLE file_registry DROP COLUMN IF EXISTS intelligence_version;
ALTER TABLE file_registry DROP COLUMN IF EXISTS indexed_at;
