-- Career Intelligence Phase 1: pipeline run tracking + run-scoped provenance.
-- pipeline_runs: one row per weekly/manual/catch-up run so clients can ask how
-- current the knowledge is (/pipeline/status) and the weekly report can scope
-- "new this week" by run instead of by wall-clock guesses.

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id            SERIAL PRIMARY KEY,
    run_id        TEXT UNIQUE NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('weekly', 'manual', 'catchup', 'weekday_sync')),
    host          TEXT,
    git_sha       TEXT,
    started_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMP,
    deadline_at   TIMESTAMP,
    heartbeat_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    status        TEXT NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running', 'finished', 'partial', 'failed', 'aborted')),
    stage         TEXT,
    stages        JSONB NOT NULL DEFAULT '{}'::jsonb,
    counts        JSONB NOT NULL DEFAULT '{}'::jsonb,
    errors        JSONB NOT NULL DEFAULT '[]'::jsonb,
    digest_id     INTEGER REFERENCES digests(id) ON DELETE SET NULL,
    model_config  JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started ON pipeline_runs(started_at DESC);

-- Provenance: which run produced a row. knowledge_facts already has created_at.
ALTER TABLE digests        ADD COLUMN IF NOT EXISTS kind   TEXT NOT NULL DEFAULT 'attention';
ALTER TABLE digests        ADD COLUMN IF NOT EXISTS run_id TEXT;
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS run_id TEXT;
ALTER TABLE fact_conflicts ADD COLUMN IF NOT EXISTS run_id TEXT;        -- first seen
ALTER TABLE stale_flags    ADD COLUMN IF NOT EXISTS run_id TEXT;        -- first seen
ALTER TABLE stale_flags    ADD COLUMN IF NOT EXISTS last_seen_run TEXT; -- for upsert-preserving refresh

CREATE INDEX IF NOT EXISTS idx_knowledge_facts_run ON knowledge_facts(run_id);
CREATE INDEX IF NOT EXISTS idx_digests_kind ON digests(kind, created_at DESC);
