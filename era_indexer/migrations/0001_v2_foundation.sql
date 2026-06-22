-- Era Vault V2 foundation.
-- Additive only: V1 tables and existing retrieval columns remain operational.

CREATE TABLE IF NOT EXISTS documents (
    id                  SERIAL PRIMARY KEY,
    file_id             INTEGER NOT NULL UNIQUE REFERENCES file_registry(id) ON DELETE CASCADE,
    title               TEXT,
    structure_version   TEXT,
    parse_metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_file ON documents(file_id);

CREATE TABLE IF NOT EXISTS document_sections (
    id                  SERIAL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    parent_section_id   INTEGER REFERENCES document_sections(id) ON DELETE CASCADE,
    level               INTEGER NOT NULL DEFAULT 1,
    title               TEXT NOT NULL,
    section_path        TEXT NOT NULL,
    ordinal             INTEGER NOT NULL DEFAULT 0,
    start_offset        INTEGER,
    end_offset          INTEGER,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sections_file ON document_sections(file_id);
CREATE INDEX IF NOT EXISTS idx_sections_parent ON document_sections(parent_section_id);
CREATE INDEX IF NOT EXISTS idx_sections_path ON document_sections(file_id, section_path);

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS section_id INTEGER REFERENCES document_sections(id) ON DELETE SET NULL;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS chunk_type TEXT;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS content_raw TEXT;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS content_contextual TEXT;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS embedding_content_version TEXT;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS token_estimate INTEGER;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS search_vector TSVECTOR;

CREATE INDEX IF NOT EXISTS idx_chunks_section ON document_chunks(section_id);
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_gin ON document_chunks USING GIN (metadata);
CREATE INDEX IF NOT EXISTS idx_chunks_search_vector ON document_chunks USING GIN (search_vector);

CREATE TABLE IF NOT EXISTS processing_artifacts (
    id                  SERIAL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    artifact_type       TEXT NOT NULL,
    artifact_version    TEXT NOT NULL,
    source_hash         TEXT NOT NULL,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(file_id, artifact_type, artifact_version, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_file ON processing_artifacts(file_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON processing_artifacts(artifact_type, artifact_version);

CREATE TABLE IF NOT EXISTS document_summaries (
    id                  SERIAL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    summary             TEXT NOT NULL,
    model               TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    source_hash         TEXT NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(file_id, model, prompt_version, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_document_summaries_file ON document_summaries(file_id);

CREATE TABLE IF NOT EXISTS section_summaries (
    id                  SERIAL PRIMARY KEY,
    section_id          INTEGER NOT NULL REFERENCES document_sections(id) ON DELETE CASCADE,
    file_id             INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    summary             TEXT NOT NULL,
    model               TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    source_hash         TEXT NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(section_id, model, prompt_version, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_section_summaries_section ON section_summaries(section_id);
CREATE INDEX IF NOT EXISTS idx_section_summaries_file ON section_summaries(file_id);

CREATE TABLE IF NOT EXISTS entities (
    id                  SERIAL PRIMARY KEY,
    canonical_name      TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    aliases             JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(canonical_name, entity_type)
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_aliases ON entities USING GIN (aliases);

CREATE TABLE IF NOT EXISTS entity_mentions (
    id                  SERIAL PRIMARY KEY,
    entity_id           INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    file_id             INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    chunk_id            INTEGER REFERENCES document_chunks(id) ON DELETE CASCADE,
    section_id          INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
    mention_text        TEXT NOT NULL,
    char_start          INTEGER,
    char_end            INTEGER,
    confidence          NUMERIC,
    extractor_version   TEXT NOT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity ON entity_mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_file ON entity_mentions(file_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_chunk ON entity_mentions(chunk_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_section ON entity_mentions(section_id);

CREATE TABLE IF NOT EXISTS relationships (
    id                  SERIAL PRIMARY KEY,
    source_entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relationship_type   TEXT NOT NULL,
    target_entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    confidence          NUMERIC,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(source_entity_id, relationship_type, target_entity_id)
);

CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type);

CREATE TABLE IF NOT EXISTS relationship_evidence (
    id                  SERIAL PRIMARY KEY,
    relationship_id     INTEGER NOT NULL REFERENCES relationships(id) ON DELETE CASCADE,
    file_id             INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    chunk_id            INTEGER REFERENCES document_chunks(id) ON DELETE CASCADE,
    section_id          INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
    evidence_text       TEXT NOT NULL,
    extractor_version   TEXT NOT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_relationship_evidence_relationship ON relationship_evidence(relationship_id);
CREATE INDEX IF NOT EXISTS idx_relationship_evidence_file ON relationship_evidence(file_id);
CREATE INDEX IF NOT EXISTS idx_relationship_evidence_chunk ON relationship_evidence(chunk_id);
CREATE INDEX IF NOT EXISTS idx_relationship_evidence_section ON relationship_evidence(section_id);
