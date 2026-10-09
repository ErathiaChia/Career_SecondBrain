DROP VIEW IF EXISTS project_facts;
DELETE FROM knowledge_facts
 WHERE kind NOT IN ('decision', 'commitment', 'event');
ALTER TABLE knowledge_facts DROP CONSTRAINT IF EXISTS knowledge_facts_kind_check;
ALTER TABLE knowledge_facts ADD CONSTRAINT knowledge_facts_kind_check
    CHECK (kind IN ('decision', 'commitment', 'event'));
DROP INDEX IF EXISTS idx_knowledge_facts_topic;
DROP INDEX IF EXISTS idx_knowledge_facts_status;
DROP INDEX IF EXISTS idx_knowledge_facts_owner;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS last_verified_at;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS supersedes_fact_id;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS owner_entity_id;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS priority;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS status;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS topic;
CREATE VIEW project_facts AS
SELECT pf.project_id, kf.*
  FROM knowledge_facts kf
  JOIN project_files pf ON pf.file_id = kf.file_id;
