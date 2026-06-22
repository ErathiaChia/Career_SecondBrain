# Era Vault Indexer

Local, offline-capable RAG indexer for your Synology knowledge base. Walks a
directory of documents and audio files, runs them through Docling (documents)
or MLX Whisper (audio transcription on Apple Silicon), chunks the text, embeds
it via Ollama, and stores everything in PostgreSQL with pgvector.

Everything runs on your Mac. Postgres lives on the Synology. After a one-time
model download, the whole pipeline works offline.

## Architecture

```
   Synology Vault (network mount)
         │
         ▼
   discover ─► file_registry + processing_queue   (Postgres on Synology)
                       │
                       ▼
               ┌───────┴────────┐
               │                │
            audio?          document?
               │                │
               ▼                ▼
        MLX Whisper          Docling
       (transcribe;         (PDF/DOCX/PPTX/
        no diarize)           XLSX → MD)
               │                │
               ▼                │
       speaker_segments         │
               │                │
               └───────┬────────┘
                       ▼
                 chunk text
                       ▼
              Ollama embeddings (bge-m3)
                       ▼
              child chunks (vector(1024))
                       │
                       ▼
              parent chunks for context
```

## Prerequisites

1. **Python 3.11+** on the Mac.
2. **Ollama** installed and running on the Mac:
   ```bash
   ollama pull bge-m3            # embeddings, 1024-dim, EN+ZH
   ollama pull gemma4:12b-mlx    # document image descriptions
   ollama pull qwen3.5:35b       # graph extraction pilot
   ollama serve   # if not already running as a daemon
   ```
3. **PostgreSQL 14+** on the Synology with `pgvector` extension installed.
   Create a database and user:
   ```sql
   CREATE DATABASE era_vault;
   CREATE USER era WITH PASSWORD '...';
   GRANT ALL ON DATABASE era_vault TO era;
   \c era_vault
   CREATE EXTENSION vector;
   ```
4. **FFmpeg** for audio decoding: `brew install ffmpeg`. No HuggingFace token
   is required — audio transcription uses MLX Whisper and there is no
   diarization step.

## Setup

```bash
# Clone or copy this directory, then:
cd era_indexer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.yaml.example config.yaml
# Edit config.yaml: set connection_string, source_directories.
# Optional: set document_images.descriptions_enabled=true to caption images
# through the local Ollama OpenAI-compatible endpoint.

# One-time setup
python -m era.cli init             # apply schema.sql
python -m era.cli bootstrap        # download MLX Whisper + Docling models
```

After `bootstrap` succeeds you can disconnect from the network entirely if you
want.

## Pre-Reindex Foundation

Do not restart the full corpus reindex until these foundations are in place.
They change the schema and retrieval behavior, so doing them after a full run
would force another expensive re-embed.

Current decisions:

- Embeddings: `bge-m3`, `1024` dimensions. Pull it on both the Mac indexer and
  the NAS/Ollama used by `era_mcp`.
- Vector index: `HNSW` over `document_chunks.embedding vector(1024)`.
- Chunking: parent-child retrieval is enabled. Small child chunks are embedded
  for precise matching; larger parent chunks are returned for context.
- Conversion: Docling markdown is cached in `processing_artifacts`, keyed by
  file hash and conversion version, so future re-embeds skip OCR/vision work.
- Document images: image captioning concurrency is `3`; OCR is disabled by
  default because it dominated runtime on digital PDFs.

Runbook:

```bash
# Mac indexer host
cd /Users/erathiachia/GitHub/Career_SecondBrain/era_indexer
ollama pull bge-m3
python -m era.cli migrate

# NAS Ollama host
ollama pull bge-m3

# First pilot only, not full corpus yet
python -m era.cli reindex-documents --folder "14. ST-Engg" --limit 5
python -m era.cli update-documents --folder "14. ST-Engg" --limit 5
python -m era.cli status --folder "14. ST-Engg"
```

Expected pilot checks:

```sql
SELECT embedding_content_version, COUNT(*)
  FROM document_chunks
 GROUP BY embedding_content_version;

SELECT COUNT(*) AS parents FROM parent_chunks;

SELECT COUNT(*) AS linked_children
  FROM document_chunks
 WHERE parent_chunk_id IS NOT NULL;

SELECT vector_dims(embedding), COUNT(*)
  FROM document_chunks
 WHERE embedding IS NOT NULL
 GROUP BY vector_dims(embedding);
```

Only after the pilot shows `markdown-headings-ctx-v1`, `1024`-dim embeddings,
non-zero parent chunks, and linked children should you reindex the rest of the
corpus.

## Document Image Descriptions

The document converter can ask a local Ollama vision model to describe images
and figures found in PDFs and supported Office files. These descriptions are
exported into the markdown that gets chunked and embedded, so diagrams,
screenshots, charts, and scanned visuals become searchable text.

Enable this in `config.yaml`:

```yaml
document_images:
  descriptions_enabled: true
  api_url: "http://localhost:11434/v1/chat/completions"
  model: "gemma4:12b-mlx"
  max_completion_tokens: 200
  concurrency: 3
  ocr_enabled: false
```

For your current Mac setup, `gemma4:12b-mlx` is the practical local option for
document image descriptions. If conversion is still too slow, lower image
captioning quality before re-enabling OCR; OCR was the main source of the
`RapidOCR returned empty result` slowdown on digital PDFs.

## Daily usage

```bash
# Update everything (discover + process all changed files)
python -m era.cli update

# Update only documents
python -m era.cli update-documents

# Update only audio/video meeting files
python -m era.cli update-meetings

# Update one folder
python -m era.cli update --folder Meetings

# Process up to 5 files this run (good for testing)
python -m era.cli update --folder Meetings --limit 5

# Split runs also support folder + limit
python -m era.cli update-documents --folder Research --limit 5
python -m era.cli update-meetings --folder Meetings --limit 5

# Reprocess already-indexed documents, then rebuild them with current settings
python -m era.cli reindex-documents
python -m era.cli update-documents

# Continuously sync new/changed files using the same safe update flow
python -m era.cli sync --interval 300

# Run one sync cycle and exit, useful for cron/system schedulers
python -m era.cli sync --once

# Just see what's pending
python -m era.cli status
python -m era.cli status --folder Meetings

# Retry failed items
python -m era.cli retry
python -m era.cli retry --folder Meetings
```

## How "update" works

`era update` is `discover` followed by `run`. It uses the default run settings
from `era.config.run_everything()`, so it still handles both documents and
audio/video files. `era update-documents` uses `era.config.run_documents()`;
`era update-meetings` uses `era.config.run_meetings_audio()`.

1. **discover** walks every directory listed in `source_directories`, hashes
   each file, and inserts/updates rows in `file_registry`. Unchanged files
   (matching SHA-256) are skipped. Changed and new files get enqueued as
   `pending` in `processing_queue`. Files that no longer exist on disk are
   removed from the registry (cascading to their chunks and segments).
2. **run** pulls pending items and pushes each through its pipeline stages,
   committing state after each stage. If the process dies mid-stage, the next
   `run` picks up where it left off.

`era sync` is a continuous wrapper around the same discover + run flow. It does
not introduce a separate indexing path; each cycle still hashes files, enqueues
only new or changed files, and resumes from `processing_queue`.

Status moves through:
- Audio: `pending` → `transcribing` → `chunking` → `embedding` → `done`
- Documents: `pending` → `converting` → `chunking` → `embedding` → `done`
- On exception: → `failed` with error message and incremented attempt count

## Schema notes

- `document_chunks.embedding` is `vector(1024)` to match `bge-m3`. If you
  change the embedding model, update the dimension in `schema.sql`, add a
  migration, and re-embed everything.
- The vector index is `HNSW` with cosine distance.
- `parent_chunks` stores larger context windows for parent-child retrieval.
  `document_chunks.parent_chunk_id` links each embedded child to its returned
  parent context.
- `processing_artifacts` stores cached converted markdown. This is what keeps
  future re-embeds from paying Docling/OCR/vision conversion cost again.
- `speaker_segments.known_speaker_id` and the `known_speakers` table are
  empty placeholders for a future global speaker-identification pipeline.
  There is no diarization in the MLX Whisper pipeline, so every audio segment
  is attributed to a single placeholder `speaker_label = "SPEAKER_00"`.
- `document_chunks.metadata` is JSONB; the runner stores `{"kind": "audio",
  "speaker": "SPEAKER_00"}` for audio chunks and `{"kind": "document"}` for
  document chunks, so RAG queries can filter on these.
- V2 schema changes are additive migrations. `era init` applies `schema.sql`
  and then any unapplied files in `migrations/`; `era migrate` can apply only
  pending migrations later. Rollback is explicit via `era migrate-rollback`
  and matching `.rollback.sql` files.
- Structure-aware, contextual, and parent-child document indexing are controlled
  by `v2.structure_aware_chunking_enabled`,
  `v2.contextual_embeddings_enabled`, and
  `v2.parent_child_retrieval_enabled`. Keep the full corpus run blocked until a
  small folder has been validated.

## Configuration knobs

In `config.yaml`:

- `models.whisper_model`: `large-v3` (best), `medium`, `small` (faster). Used
  only to derive the MLX repo when `whisper_mlx_repo` is unset.
- `models.whisper_mlx_repo`: explicit MLX Community repo, e.g.
  `mlx-community/whisper-large-v3-mlx`. MLX Whisper runs on the Mac GPU (Metal).
- `models.whisper_condition_on_previous_text`: `false` (default) stops the
  decoder from getting stuck in repetition/hallucination loops.
- `models.whisper_compression_ratio_threshold`: `1.8` (stricter than the 2.4
  default) re-rolls repetitive "stuck" segments more aggressively.
- `processing.chunk_size` / `chunk_overlap`: tune for your retrieval task.

## Troubleshooting

**Audio transcription import/runtime error**: ensure `mlx-whisper` is installed
(`pip install mlx-whisper`) and `ffmpeg` is on PATH (`brew install ffmpeg`). MLX
Whisper requires Apple Silicon; it will not run on Intel/x86 or inside a
non-Apple Docker host.

**`could not connect to server` from Postgres**: check that pgvector is
installed (`CREATE EXTENSION vector;` in the database), connection string is
right, and that the Mac can reach the Synology on port 5432.

**Ollama warmup failed**: run `ollama serve` and `ollama pull bge-m3`.

**Files get marked `failed`**: run `python -c "from era import config, db;
config.load(); print(db.pending_files())"` to inspect, or query
`processing_queue.error_message` directly. After fixing, `era retry` to
re-enqueue.

## Next step: RAG + MCP

This indexer is the "write" half. The "read" half is a separate small
service that:
1. Takes a query, embeds it with the same Ollama model (`bge-m3`).
2. Runs hybrid vector + full-text retrieval over child chunks.
3. Collapses child hits to `parent_chunks` for larger context when available.
4. Pulls back top-K results with their `file_registry` and (for audio)
   `speaker_segments` metadata, so attribution travels with the answer.

That service can sit behind an MCP server exposing `search_vault` and
`indexing_status` as tools. The CLI commands here become the operator
interface for the same data.
