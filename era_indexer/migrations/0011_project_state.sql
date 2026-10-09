-- Era Vault project intelligence, Phase 2: project state snapshots.
-- One row per rebuild with changed inputs; is_current marks the latest. `state`
-- holds phase/objectives/blockers/... where every field carries value,
-- confidence, sources and last_verified. `health` holds explainable dimensions.

CREATE TABLE IF NOT EXISTS project_state (
    id                  SERIAL PRIMARY KEY,
    project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    state               JSONB NOT NULL DEFAULT '{}'::jsonb,
    health              JSONB NOT NULL DEFAULT '{}'::jsonb,
    model               TEXT,
    source_hash         TEXT NOT NULL,
    is_current          BOOLEAN NOT NULL DEFAULT TRUE,
    built_at            TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_state_project ON project_state(project_id, built_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_project_state_one_current
    ON project_state(project_id) WHERE is_current;
