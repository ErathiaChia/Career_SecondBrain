-- Era Vault project intelligence, Phase 1: document version chains.
-- Files in the same scope (project, else parent folder) that share a family key
-- (name minus version/draft/page affixes, same extension) form an ordered chain.
-- Rebuilt by `link-versions` (also run inside `discover`).

CREATE TABLE IF NOT EXISTS document_versions (
    file_id             INTEGER PRIMARY KEY REFERENCES file_registry(id) ON DELETE CASCADE,
    family_key          TEXT NOT NULL,
    scope_key           TEXT NOT NULL,
    project_id          INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    version_label       TEXT,
    version_rank        INTEGER NOT NULL,
    previous_file_id    INTEGER REFERENCES file_registry(id) ON DELETE SET NULL,
    is_latest           BOOLEAN NOT NULL DEFAULT FALSE,
    family_size         INTEGER NOT NULL DEFAULT 1,
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_versions_family ON document_versions(scope_key, family_key);
CREATE INDEX IF NOT EXISTS idx_document_versions_project ON document_versions(project_id);
