DROP VIEW IF EXISTS chunks;
DROP VIEW IF EXISTS sections;
DROP TABLE IF EXISTS graph_metadata;
DROP TABLE IF EXISTS community_members;
DROP TABLE IF EXISTS communities;

ALTER TABLE relationships DROP COLUMN IF EXISTS evidence_count;
ALTER TABLE relationships DROP COLUMN IF EXISTS edge_weight;

ALTER TABLE entities DROP COLUMN IF EXISTS node_weight;
ALTER TABLE entities DROP COLUMN IF EXISTS mention_count;

ALTER TABLE document_chunks DROP COLUMN IF EXISTS contextual_content;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS raw_content;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS subsection_title;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS heading_path;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS page_number;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS document_id;
