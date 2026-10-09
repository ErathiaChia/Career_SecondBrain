-- Era Vault project intelligence, Phases 4-5.
-- proposed_actions: agent-suggested actions awaiting human approval. The only
-- table era_mcp writes to; nothing is executed until a person approves it.
-- digests: the monitoring pipeline's attention-thresholded output.

CREATE TABLE IF NOT EXISTS proposed_actions (
    id                  SERIAL PRIMARY KEY,
    project_id          INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    action_type         TEXT NOT NULL,
    title               TEXT NOT NULL,
    detail              TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_fact_ids     JSONB NOT NULL DEFAULT '[]'::jsonb,
    proposed_by         TEXT NOT NULL DEFAULT 'era_mcp',
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected', 'done')),
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    decided_at          TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_proposed_actions_status ON proposed_actions(status, created_at DESC);

CREATE TABLE IF NOT EXISTS digests (
    id                  SERIAL PRIMARY KEY,
    items               JSONB NOT NULL DEFAULT '[]'::jsonb,
    markdown            TEXT NOT NULL DEFAULT '',
    stats               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);
