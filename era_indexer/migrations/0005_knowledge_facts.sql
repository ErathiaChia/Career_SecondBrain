-- Era Vault Layer 1: structured facts (decisions / commitments / events).
-- Additive only: a new table sourced from already-indexed chunks during the
-- same graph extraction pass. No existing table is altered; nothing re-embeds.

CREATE TABLE IF NOT EXISTS knowledge_facts (
    id                  SERIAL PRIMARY KEY,
    kind                TEXT NOT NULL CHECK (kind IN ('decision', 'commitment', 'event')),
    statement           TEXT NOT NULL,
    subject_entity_id   INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    object_entity_id    INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    project_entity_id   INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    -- attributes: {due_at, status, direction ('owed_by_me'|'owed_to_me'), counterparty}
    attributes          JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at         TIMESTAMP,
    file_id             INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    chunk_id            INTEGER REFERENCES document_chunks(id) ON DELETE CASCADE,
    source_quote        TEXT,
    confidence          NUMERIC,
    extractor_version   TEXT NOT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_facts_kind ON knowledge_facts(kind);
CREATE INDEX IF NOT EXISTS idx_knowledge_facts_project ON knowledge_facts(project_entity_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_facts_subject ON knowledge_facts(subject_entity_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_facts_file ON knowledge_facts(file_id);
-- chunk_id index supports clear-by-chunk before re-extraction (idempotent re-runs).
CREATE INDEX IF NOT EXISTS idx_knowledge_facts_chunk ON knowledge_facts(chunk_id);
