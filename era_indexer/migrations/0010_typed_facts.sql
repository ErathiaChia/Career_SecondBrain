-- Era Vault project intelligence, Phase 2: typed project facts.
-- Widens knowledge_facts.kind beyond decision/commitment/event and adds the
-- lifecycle columns every project fact carries. Additive: existing rows keep
-- their kind; new columns are nullable.

ALTER TABLE knowledge_facts DROP CONSTRAINT IF EXISTS knowledge_facts_kind_check;
ALTER TABLE knowledge_facts ADD CONSTRAINT knowledge_facts_kind_check CHECK (kind IN (
    'decision', 'commitment', 'event',
    'requirement', 'risk', 'action_item', 'open_question', 'dependency', 'milestone'
));

ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS topic TEXT;
-- open | in_progress | done | blocked | cancelled | proposed | approved | rejected | mitigated
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS status TEXT;
-- high | medium | low (also used as risk severity)
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS priority TEXT;
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS owner_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL;
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS supersedes_fact_id INTEGER REFERENCES knowledge_facts(id) ON DELETE SET NULL;
-- When the source last asserted this fact: occurred_at, else the file's mtime.
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_knowledge_facts_topic ON knowledge_facts(topic);
CREATE INDEX IF NOT EXISTS idx_knowledge_facts_status ON knowledge_facts(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_facts_owner ON knowledge_facts(owner_entity_id);

-- `kf.*` is expanded when a view is created, so recreate it to pick up the new columns.
DROP VIEW IF EXISTS project_facts;
CREATE VIEW project_facts AS
SELECT pf.project_id, kf.*
  FROM knowledge_facts kf
  JOIN project_files pf ON pf.file_id = kf.file_id;
