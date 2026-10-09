-- Era Vault project intelligence, Phase 1: first-class projects.
-- Additive only. vault_manifest and vault_reusable_assets are the neutral
-- hand-off tables written by era_auditor (`manifest export`) and read by the
-- indexer and era_mcp, so neither side has to read auditor_* tables.

CREATE TABLE IF NOT EXISTS vault_manifest (
    path                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    kind                TEXT,
    parent              TEXT,
    project_key         TEXT,
    customer_code       TEXT,
    customer_name       TEXT,
    status              TEXT,
    lifecycle           TEXT,
    initiative_type     TEXT,
    year                INTEGER,
    tags                JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    manifest_version    INTEGER NOT NULL DEFAULT 1,
    generated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vault_manifest_kind ON vault_manifest(kind);

CREATE TABLE IF NOT EXISTS vault_reusable_assets (
    asset_key           TEXT PRIMARY KEY,
    asset_name          TEXT NOT NULL,
    file_type           TEXT,
    reuse_score         INTEGER NOT NULL DEFAULT 0,
    copy_count          INTEGER NOT NULL DEFAULT 1,
    paths               JSONB NOT NULL DEFAULT '[]'::jsonb,
    projects            JSONB NOT NULL DEFAULT '[]'::jsonb,
    customers           JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical_location  TEXT,
    generated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projects (
    id                  SERIAL PRIMARY KEY,
    project_key         TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    client              TEXT,
    project_type        TEXT,
    status              TEXT,
    lifecycle           TEXT,
    owner               TEXT,
    source_folder       TEXT NOT NULL,
    entity_id           INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    first_activity      TIMESTAMP,
    last_activity       TIMESTAMP,
    file_count          INTEGER NOT NULL DEFAULT 0,
    confidence          NUMERIC,
    field_sources       JSONB NOT NULL DEFAULT '{}'::jsonb,
    aliases             JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_client ON projects(client);

CREATE TABLE IF NOT EXISTS project_files (
    project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_id             INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, file_id)
);

CREATE INDEX IF NOT EXISTS idx_project_files_file ON project_files(file_id);

-- Entities and facts scoped to a project through the files they came from.
CREATE OR REPLACE VIEW project_entities AS
SELECT pf.project_id,
       em.entity_id,
       COUNT(*) AS mention_count,
       COUNT(DISTINCT em.file_id) AS file_count
  FROM project_files pf
  JOIN entity_mentions em ON em.file_id = pf.file_id
 GROUP BY pf.project_id, em.entity_id;

CREATE OR REPLACE VIEW project_facts AS
SELECT pf.project_id, kf.*
  FROM knowledge_facts kf
  JOIN project_files pf ON pf.file_id = kf.file_id;
