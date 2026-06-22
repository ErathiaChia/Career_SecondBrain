-- Era Vault graph visualization support.
-- Stores per-chunk extraction state and iframe-ready graph snapshots.

CREATE TABLE IF NOT EXISTS graph_extraction_state (
    chunk_id            INTEGER PRIMARY KEY REFERENCES document_chunks(id) ON DELETE CASCADE,
    content_hash        TEXT NOT NULL,
    extractor_version   TEXT NOT NULL,
    status              TEXT NOT NULL,
    error_message       TEXT,
    extracted_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_extraction_state_status
    ON graph_extraction_state(status);

CREATE TABLE IF NOT EXISTS graph_snapshots (
    id                  SERIAL PRIMARY KEY,
    scope               TEXT NOT NULL DEFAULT 'all',
    source_hash         TEXT NOT NULL,
    extraction_version  TEXT NOT NULL,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    node_count          INTEGER NOT NULL DEFAULT 0,
    edge_count          INTEGER NOT NULL DEFAULT 0,
    is_current          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_snapshots_scope_current
    ON graph_snapshots(scope, is_current, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_snapshots_one_current_per_scope
    ON graph_snapshots(scope)
    WHERE is_current;
