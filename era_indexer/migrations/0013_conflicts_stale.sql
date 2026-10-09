-- Era Vault project intelligence, Phase 3: contradictions and stale knowledge.
-- fact_conflicts: a pair of facts that disagree. status: needs_confirmation |
-- confirmed | dismissed (user decisions survive re-detection).
-- stale_flags: rebuilt wholesale by `detect-stale`.

CREATE TABLE IF NOT EXISTS fact_conflicts (
    id                      SERIAL PRIMARY KEY,
    project_id              INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    fact_a_id               INTEGER NOT NULL REFERENCES knowledge_facts(id) ON DELETE CASCADE,
    fact_b_id               INTEGER NOT NULL REFERENCES knowledge_facts(id) ON DELETE CASCADE,
    conflict_type           TEXT NOT NULL,
    explanation             TEXT,
    likely_latest_fact_id   INTEGER REFERENCES knowledge_facts(id) ON DELETE SET NULL,
    confidence              NUMERIC,
    status                  TEXT NOT NULL DEFAULT 'needs_confirmation',
    method                  TEXT NOT NULL,
    detected_at             TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (fact_a_id, fact_b_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_conflicts_project ON fact_conflicts(project_id, status);

CREATE TABLE IF NOT EXISTS stale_flags (
    id                  SERIAL PRIMARY KEY,
    object_type         TEXT NOT NULL,
    object_id           INTEGER NOT NULL,
    reason              TEXT NOT NULL,
    detail              TEXT,
    newer_evidence_id   INTEGER,
    flagged_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (object_type, object_id, reason)
);

CREATE INDEX IF NOT EXISTS idx_stale_flags_object ON stale_flags(object_type, object_id);
