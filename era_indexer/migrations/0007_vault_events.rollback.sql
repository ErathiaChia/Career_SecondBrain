DROP TABLE IF EXISTS vault_events;
DROP INDEX IF EXISTS idx_file_registry_live;
ALTER TABLE file_registry DROP COLUMN IF EXISTS deleted_at;
