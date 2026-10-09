-- Era Vault project intelligence, Phase 1: entity resolution audit log.
-- `resolve-entities --apply` folds duplicates ("ST Engg" / "ST Engineering")
-- into one canonical entity; each fold is recorded here so it can be reviewed.

CREATE TABLE IF NOT EXISTS entity_merges (
    id                  SERIAL PRIMARY KEY,
    merged_name         TEXT NOT NULL,
    merged_type         TEXT NOT NULL,
    into_entity_id      INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    method              TEXT NOT NULL,
    score               NUMERIC,
    merged_at           TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entity_merges_into ON entity_merges(into_entity_id);
