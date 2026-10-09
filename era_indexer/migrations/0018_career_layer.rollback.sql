DROP VIEW IF EXISTS decision_links;
DROP TABLE IF EXISTS career_state;
DROP TABLE IF EXISTS skill_evidence;
DROP TABLE IF EXISTS achievements;
DROP TABLE IF EXISTS role_assignments;
-- Facts of the new kinds are left in place; restore the old CHECK only if none exist:
-- ALTER TABLE knowledge_facts DROP CONSTRAINT knowledge_facts_kind_check;
-- ALTER TABLE knowledge_facts ADD CONSTRAINT knowledge_facts_kind_check CHECK (kind IN (
--   'decision','commitment','event','requirement','risk','action_item','open_question','dependency','milestone'));
