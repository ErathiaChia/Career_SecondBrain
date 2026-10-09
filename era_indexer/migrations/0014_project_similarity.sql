-- Era Vault project intelligence, Phase 3: cross-project similarity.
-- project_embeddings: mean of a project's chunk embeddings (same 1024-dim space
-- as document_chunks, so a query embedding can be compared directly).
-- project_similarity: top neighbours, score = 0.7 * cosine + 0.3 * entity Jaccard.

CREATE TABLE IF NOT EXISTS project_embeddings (
    project_id          INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    embedding           vector(1024) NOT NULL,
    chunk_count         INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS project_similarity (
    project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    other_project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    score               NUMERIC NOT NULL,
    cosine              NUMERIC,
    entity_overlap      NUMERIC,
    shared_entities     JSONB NOT NULL DEFAULT '[]'::jsonb,
    computed_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (project_id, other_project_id)
);
