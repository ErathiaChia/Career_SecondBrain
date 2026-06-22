-- Era Vault V3 Knowledge Operating System.
-- Additive only: keeps V1/V2 tables and CLI workflows operational.

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS page_number INTEGER;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS heading_path TEXT;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS subsection_title TEXT;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS raw_content TEXT;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS contextual_content TEXT;

CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_heading_path ON document_chunks(file_id, heading_path);

ALTER TABLE entities
    ADD COLUMN IF NOT EXISTS mention_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE entities
    ADD COLUMN IF NOT EXISTS node_weight NUMERIC NOT NULL DEFAULT 1;

ALTER TABLE relationships
    ADD COLUMN IF NOT EXISTS edge_weight NUMERIC NOT NULL DEFAULT 1;

ALTER TABLE relationships
    ADD COLUMN IF NOT EXISTS evidence_count INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS communities (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    summary             TEXT NOT NULL DEFAULT '',
    algorithm           TEXT NOT NULL,
    algorithm_version   TEXT NOT NULL,
    source_hash         TEXT NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(name, algorithm, algorithm_version)
);

CREATE INDEX IF NOT EXISTS idx_communities_algorithm
    ON communities(algorithm, algorithm_version);

CREATE TABLE IF NOT EXISTS community_members (
    id                  SERIAL PRIMARY KEY,
    community_id        INTEGER NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
    entity_id           INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    document_id         INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    section_id          INTEGER REFERENCES document_sections(id) ON DELETE CASCADE,
    member_type         TEXT NOT NULL,
    membership_weight   NUMERIC NOT NULL DEFAULT 1,
    provenance          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (
        entity_id IS NOT NULL
        OR document_id IS NOT NULL
        OR section_id IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_community_members_community
    ON community_members(community_id);
CREATE INDEX IF NOT EXISTS idx_community_members_entity
    ON community_members(entity_id);
CREATE INDEX IF NOT EXISTS idx_community_members_document
    ON community_members(document_id);

CREATE TABLE IF NOT EXISTS graph_metadata (
    id                  SERIAL PRIMARY KEY,
    object_type         TEXT NOT NULL,
    object_id           INTEGER NOT NULL,
    node_type           TEXT,
    node_weight         NUMERIC,
    node_degree         INTEGER,
    edge_weight         NUMERIC,
    edge_confidence     NUMERIC,
    export_eligible     BOOLEAN NOT NULL DEFAULT TRUE,
    metrics             JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(object_type, object_id)
);

CREATE INDEX IF NOT EXISTS idx_graph_metadata_object
    ON graph_metadata(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_graph_metadata_export
    ON graph_metadata(export_eligible);

CREATE OR REPLACE VIEW sections AS
SELECT *
  FROM document_sections;

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
