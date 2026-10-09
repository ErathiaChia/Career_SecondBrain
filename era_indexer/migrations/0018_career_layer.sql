-- Career Intelligence Phase 2: the "me" layer (brief §12, §13).
-- Roles I held per project, achievements with evidence, skill/technology
-- evidence, plus three fact kinds (contribution / outcome / lesson) so the
-- extractor can record what a named person DID and what RESULTED.

ALTER TABLE knowledge_facts DROP CONSTRAINT IF EXISTS knowledge_facts_kind_check;
ALTER TABLE knowledge_facts ADD CONSTRAINT knowledge_facts_kind_check CHECK (kind IN (
    'decision', 'commitment', 'event',
    'requirement', 'risk', 'action_item', 'open_question', 'dependency', 'milestone',
    'contribution', 'outcome', 'lesson'));

CREATE TABLE IF NOT EXISTS role_assignments (
    id                 SERIAL PRIMARY KEY,
    project_id         INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    person_entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    is_me              BOOLEAN NOT NULL DEFAULT FALSE,
    role               TEXT NOT NULL,       -- project_manager|solution_architect|presales|delivery_lead|product_manager|engineer|consultant|stakeholder|sponsor|other
    role_label         TEXT,                -- as stated in the documents, if anywhere
    period_start       DATE,
    period_end         DATE,
    confidence         NUMERIC NOT NULL,
    signals            JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {prior: 0.35, contribution_facts: 0.3, ...}
    sources            JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{fact_id} | {file_id}]
    method             TEXT NOT NULL,       -- prior|inferred|llm|confirmed
    status             TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'confirmed', 'rejected')),
    proposed_action_id INTEGER REFERENCES proposed_actions(id) ON DELETE SET NULL,
    created_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, person_entity_id, role)
);

CREATE INDEX IF NOT EXISTS idx_role_assignments_me ON role_assignments (is_me, status);

CREATE TABLE IF NOT EXISTS achievements (
    id                SERIAL PRIMARY KEY,
    project_id        INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    statement         TEXT NOT NULL,
    metric            JSONB,              -- {name, value, unit, baseline, raw}
    outcome_kind      TEXT,               -- revenue|cost|time|quality|adoption|win|delivery|award|other
    is_me             BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_fact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_file_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence        NUMERIC NOT NULL,
    period_start      DATE,
    period_end        DATE,
    source_hash       TEXT NOT NULL,      -- sha(sorted evidence fact ids): idempotent upsert
    status            TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'confirmed', 'rejected', 'orphaned')),
    run_id            TEXT,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_achievements_me ON achievements (is_me, status);
CREATE INDEX IF NOT EXISTS idx_achievements_run ON achievements (run_id);

CREATE TABLE IF NOT EXISTS skill_evidence (
    id                SERIAL PRIMARY KEY,
    entity_id         INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    skill_kind        TEXT NOT NULL,      -- technology|product|method|domain
    role              TEXT,               -- my role on that project
    mention_count     INTEGER NOT NULL DEFAULT 0,
    evidence_fact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_file_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    strength          NUMERIC NOT NULL,
    first_seen        DATE,
    last_seen         DATE,
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (entity_id, project_id)
);

CREATE INDEX IF NOT EXISTS idx_skill_evidence_entity ON skill_evidence (entity_id);

-- Per-project incremental guard for career.refresh_career.
CREATE TABLE IF NOT EXISTS career_state (
    project_id  INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    source_hash TEXT NOT NULL,
    built_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Decision -> related decision (brief §14): supersedes chain, confirmed
-- conflicts, and same-topic decisions in the same project.
CREATE OR REPLACE VIEW decision_links AS
    SELECT kf.id AS decision_id, kf.supersedes_fact_id AS related_id, 'supersedes' AS relation
      FROM knowledge_facts kf
     WHERE kf.kind = 'decision' AND kf.supersedes_fact_id IS NOT NULL
UNION ALL
    SELECT fc.fact_a_id, fc.fact_b_id, 'conflicts'
      FROM fact_conflicts fc JOIN knowledge_facts a ON a.id = fc.fact_a_id
     WHERE a.kind = 'decision' AND fc.status IN ('needs_confirmation', 'confirmed')
UNION ALL
    SELECT a.id, b.id, 'same_topic'
      FROM project_facts a JOIN project_facts b
        ON a.project_id = b.project_id AND a.topic = b.topic AND a.id < b.id
     WHERE a.kind = 'decision' AND b.kind = 'decision' AND a.topic IS NOT NULL;
