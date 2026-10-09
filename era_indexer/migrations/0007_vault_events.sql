-- Era Vault project intelligence, Phase 1: history instead of hard deletes.
-- A file that disappears is soft-deleted (deleted_at set, chunks removed so it
-- leaves retrieval) and every add/modify/delete/restore is appended to
-- vault_events, which change detection consumes.

ALTER TABLE file_registry
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_file_registry_live ON file_registry(id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS vault_events (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('added', 'modified', 'deleted', 'restored', 'version_added')),
    file_id         INTEGER REFERENCES file_registry(id) ON DELETE SET NULL,
    file_path       TEXT NOT NULL,
    old_hash        TEXT,
    new_hash        TEXT,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    detected_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vault_events_unprocessed ON vault_events(detected_at) WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_vault_events_file ON vault_events(file_id);
CREATE INDEX IF NOT EXISTS idx_vault_events_detected ON vault_events(detected_at);
