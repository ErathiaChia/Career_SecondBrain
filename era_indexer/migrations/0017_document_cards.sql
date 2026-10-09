-- Career Intelligence Phase 2: Document Intelligence Cards (brief §6 Layer 4, §7).
-- One compact, searchable record per document, assembled from the typed facts,
-- entity mentions, project assignment and version chain (no LLM) plus the
-- summary/keywords/topics/doc_type the extraction call now returns in the same
-- pass. The agent searches cards BEFORE loading passages.

CREATE TABLE IF NOT EXISTS document_cards (
    file_id              INTEGER PRIMARY KEY REFERENCES file_registry(id) ON DELETE CASCADE,
    source_hash          TEXT NOT NULL,                  -- file_registry.file_hash at build
    intelligence_version TEXT NOT NULL,                  -- cards.INTELLIGENCE_VERSION
    inputs_hash          TEXT NOT NULL,                  -- deterministic inputs (facts, mentions, project, versions)
    title                TEXT,
    doc_type             TEXT,
    summary              TEXT NOT NULL DEFAULT '',
    keywords             JSONB NOT NULL DEFAULT '[]'::jsonb,
    topics               JSONB NOT NULL DEFAULT '[]'::jsonb,
    entities             JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{id, name, type}]
    projects             JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{id, name, project_key}]
    people               JSONB NOT NULL DEFAULT '[]'::jsonb,
    customers            JSONB NOT NULL DEFAULT '[]'::jsonb,
    products             JSONB NOT NULL DEFAULT '[]'::jsonb,
    technologies         JSONB NOT NULL DEFAULT '[]'::jsonb,
    dates                JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{date, label, source}]
    doc_date             DATE,
    decisions            JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{fact_id, statement, status}]
    risks                JSONB NOT NULL DEFAULT '[]'::jsonb,
    actions              JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcomes             JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{fact_id|null, statement, metric}]
    "references"         JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{text, file_id|null}]
    related_file_ids     JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{file_id, relation, score}]
    card_text            TEXT NOT NULL DEFAULT '',
    search_vector        TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', card_text)) STORED,
    embedding            vector(1024),
    model                TEXT,
    llm_card             JSONB NOT NULL DEFAULT '{}'::jsonb,   -- raw merged card object (provenance)
    built_at             TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_cards_fts       ON document_cards USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_document_cards_embedding ON document_cards USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_document_cards_topics    ON document_cards USING GIN (topics jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_document_cards_keywords  ON document_cards USING GIN (keywords jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_document_cards_doc_type  ON document_cards (doc_type);
CREATE INDEX IF NOT EXISTS idx_document_cards_doc_date  ON document_cards (doc_date);

-- Document -> Document edges (brief §14). related_file_ids above is the
-- denormalised top-10; this table is the source of truth.
CREATE TABLE IF NOT EXISTS document_relations (
    file_id          INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    related_file_id  INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    relation         TEXT NOT NULL,      -- version | project | similar | reference
    score            NUMERIC,
    computed_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (file_id, related_file_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_document_relations_related ON document_relations (related_file_id);

-- Document -> Topic as a view over cards (no extra write path).
CREATE OR REPLACE VIEW document_topics AS
SELECT dc.file_id, t.topic
  FROM document_cards dc, jsonb_array_elements_text(dc.topics) AS t(topic);
