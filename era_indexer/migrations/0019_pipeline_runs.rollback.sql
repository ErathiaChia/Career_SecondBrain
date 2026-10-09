DROP TABLE IF EXISTS pipeline_runs;
ALTER TABLE digests         DROP COLUMN IF EXISTS kind;
ALTER TABLE digests         DROP COLUMN IF EXISTS run_id;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS run_id;
ALTER TABLE fact_conflicts  DROP COLUMN IF EXISTS run_id;
ALTER TABLE stale_flags     DROP COLUMN IF EXISTS run_id;
ALTER TABLE stale_flags     DROP COLUMN IF EXISTS last_seen_run;
