-- Roll back Era Vault V2 foundation objects.
-- Explicit rollback only; normal operational rollback should prefer config flags.

DROP TABLE IF EXISTS relationship_evidence;
DROP TABLE IF EXISTS relationships;
DROP TABLE IF EXISTS entity_mentions;
DROP TABLE IF EXISTS entities;
DROP TABLE IF EXISTS section_summaries;
DROP TABLE IF EXISTS document_summaries;
DROP TABLE IF EXISTS processing_artifacts;

DROP INDEX IF EXISTS idx_chunks_search_vector;
DROP INDEX IF EXISTS idx_chunks_metadata_gin;
DROP INDEX IF EXISTS idx_chunks_section;

ALTER TABLE document_chunks
    DROP COLUMN IF EXISTS search_vector;

ALTER TABLE document_chunks
    DROP COLUMN IF EXISTS token_estimate;

ALTER TABLE document_chunks
    DROP COLUMN IF EXISTS embedding_content_version;

ALTER TABLE document_chunks
    DROP COLUMN IF EXISTS content_contextual;

ALTER TABLE document_chunks
    DROP COLUMN IF EXISTS content_raw;

ALTER TABLE document_chunks
    DROP COLUMN IF EXISTS chunk_type;

ALTER TABLE document_chunks
    DROP COLUMN IF EXISTS section_id;

DROP TABLE IF EXISTS document_sections;
DROP TABLE IF EXISTS documents;
