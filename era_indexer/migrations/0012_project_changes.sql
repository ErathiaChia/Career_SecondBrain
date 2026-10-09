-- Era Vault project intelligence, Phase 3: what changed, and why it matters.
-- change_type: file_added | file_modified | file_deleted | file_restored |
-- version_added | fact_added | fact_removed | fact_changed.
-- `impact` is filled by `detect-changes` (LLM impact card per project batch).

CREATE TABLE IF NOT EXISTS project_changes (
    id                  BIGSERIAL PRIMARY KEY,
    project_id          INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    file_id             INTEGER REFERENCES file_registry(id) ON DELETE SET NULL,
    change_type         TEXT NOT NULL,
    summary             TEXT NOT NULL,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    impact              JSONB,
    batch_id            TEXT,
    severity            TEXT NOT NULL DEFAULT 'info',
    detected_at         TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_changes_project ON project_changes(project_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_project_changes_pending ON project_changes(project_id) WHERE impact IS NULL;
