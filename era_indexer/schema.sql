-- Era Vault: schema for incremental document + audio indexing.
-- Idempotent: safe to apply multiple times.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- file_registry: one row per indexed file on disk
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS file_registry (
    id                  SERIAL PRIMARY KEY,
    file_path           TEXT UNIQUE NOT NULL,
    file_name           TEXT NOT NULL,
    file_type           TEXT NOT NULL,
    file_hash           TEXT NOT NULL,
    folder              TEXT NOT NULL,         -- top-level subdir under source_directory
    is_audio            BOOLEAN NOT NULL DEFAULT FALSE,
    last_modified_at    TIMESTAMP,
    last_processed_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_registry_folder ON file_registry(folder);

-- ---------------------------------------------------------------------------
-- processing_queue: per-file state machine
--   pending -> transcribing/converting -> chunking -> embedding -> done
--                                                                ↘ failed
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processing_queue (
    id              SERIAL PRIMARY KEY,
    file_id         INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    discovered_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    stage_timings   JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {"transcribing": 142.3, ...}
    UNIQUE(file_id)
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON processing_queue(status);

-- ---------------------------------------------------------------------------
-- known_speakers: voice profiles for future global identification
-- Empty for now; populated by a separate enrichment pipeline later.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS known_speakers (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    embedding       vector(512),     -- pyannote/embedding output dim
    sample_count    INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- speaker_segments: per-file diarization output
-- speaker_label is the per-file pyannote label (SPEAKER_00, SPEAKER_01, ...).
-- known_speaker_id stays NULL until the future global-ID pipeline fills it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS speaker_segments (
    id                  SERIAL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    speaker_label       TEXT NOT NULL,
    known_speaker_id    INTEGER REFERENCES known_speakers(id) ON DELETE SET NULL,
    start_time          NUMERIC NOT NULL,
    end_time            NUMERIC NOT NULL,
    text                TEXT,
    confidence          NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_segments_file ON speaker_segments(file_id);

-- ---------------------------------------------------------------------------
-- document_chunks: text chunks + embeddings.
-- speaker_segment_id is NULL for non-audio files; links audio chunks back to
-- the diarized segment so RAG queries can attribute results to a speaker.
--
-- NOTE: vector(1024) matches Ollama's bge-m3. If you change the embedding
-- model, change this dimension AND add a migration to ALTER the column, then
-- re-embed everything.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_chunks (
    id                  SERIAL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES file_registry(id) ON DELETE CASCADE,
    chunk_index         INTEGER NOT NULL,
    content             TEXT NOT NULL,
    embedding           vector(1024),
    speaker_segment_id  INTEGER REFERENCES speaker_segments(id) ON DELETE SET NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_chunks_file ON document_chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
