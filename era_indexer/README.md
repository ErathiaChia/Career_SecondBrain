# Era Vault Indexer

Local, offline-capable RAG indexer for your Synology knowledge base. Walks a
directory of documents and audio files, runs them through Docling (documents)
or MLX Whisper (audio transcription on Apple Silicon), chunks the text, embeds
it via Ollama, and stores everything in PostgreSQL with pgvector.

Everything runs on your Mac. Postgres lives on the Synology. After a one-time
model download, the whole pipeline works offline.

The Python package in this folder is `career_history` (CLI:
`python -m career_history.cli`). See the [repo masterplan](../README.md) for how
all four Era Vault components fit together.

## Ecosystem

| Component | Role |
|-----------|------|
| **era_indexer** (this) | Write — discover, convert, chunk, embed, graph extract |
| [`era_mcp`](../era_mcp) | Read — hybrid search, `/ask` agent, OpenAPI tools |
| [`era_auditor`](../era_auditor) | Steward — vault hygiene, semantic dupes, Librarian training |
| [`era_graph_web`](../era_graph_web) | Visualize — Sigma.js graph viewer at `/graph` |

Indexer populates Postgres; MCP reads it; auditor scans the same vault roots
and optionally reads indexer embeddings; graph web displays snapshots served by MCP.

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
               ▼                ▼
       speaker_segments    vision captions
               │           (optional Ollama)
               └───────┬────────┘
                       ▼
           structure-aware chunking
           + contextual headers (v2)
                       ▼
              Ollama embeddings (qwen3-embedding:0.6b)
                       ▼
              child chunks (vector(1024))
                       │
                       ▼
              parent chunks for context
```

## Prerequisites

1. **Python 3.11+** on the Mac.
2. **Ollama** installed and running on the Mac. Pull the models referenced in
   your `config.yaml` (see [Configuration](#configuration) below). At minimum:
   ```bash
   ollama pull qwen3-embedding:0.6b   # embeddings, 1024-dim, EN+ZH, 32k context
   ollama pull gemma4:12b-mlx         # document image descriptions (when enabled)
   ollama pull qwen3.5:35b            # graph extraction (when v2 graph flags on)
   ollama serve                       # if not already running as a daemon
   ```
   Pull `qwen3-embedding:0.6b` on **both** the Mac indexer host and any NAS/Ollama
   host used by `era_mcp` so query embeddings match indexed vectors.
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
   is required for transcription — MLX Whisper handles audio and there is no
   diarization step.

## Setup

```bash
cd era_indexer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.yaml.example config.yaml
# Edit config.yaml: source_directories, models, v2 flags, etc.
# Database: prefer ERA_VAULT_DB_* values in .env; connection_string is fallback.

python -m career_history.cli init       # apply schema.sql + pending migrations
python -m career_history.cli bootstrap  # download MLX Whisper + Docling models
```

After `bootstrap` succeeds you can disconnect from the network entirely if you
want.

## Configuration

All knobs live in `config.yaml` (copy from `config.yaml.example`). The tables
below mirror the current checked-in defaults.

### `database`

| Key | Value | Notes |
|-----|-------|-------|
| `connection_string` | Postgres URL | Fallback only. The app prefers `ERA_VAULT_DB_*` from `.env`. |

### `paths.source_directories`

List of vault roots on the network mount. Each directory is walked recursively.
Add as many roots as you need.

### `models`

| Key | Default | Notes |
|-----|---------|-------|
| `embedding_model` | `qwen3-embedding:0.6b` | Multilingual (EN+ZH), 1024-dim, 32k context. |
| `embedding_dim` | `1024` | Must match `vector(1024)` in `schema.sql`. |
| `graph_extraction_model` | `qwen3.5:35b` | Entity/relationship JSON extraction (`graph.py`). Favors quality; switch to a smaller MLX model if pilot throughput is too slow. |
| `whisper_model` | `large-v3-turbo` | Used only to derive the MLX repo when `whisper_mlx_repo` is unset. |
| `whisper_mlx_repo` | `mlx-community/whisper-large-v3-mlx` | MLX Whisper runs on the Mac GPU (Metal). |
| `whisper_language` | `null` | `null` = auto-detect per file. |
| `allowed_languages` | `["en", "zh"]` | Only index audio in these languages. |
| `whisper_condition_on_previous_text` | `false` | Stops repetition/hallucination loops. |
| `whisper_compression_ratio_threshold` | `1.8` | Stricter than the 2.4 default; re-rolls stuck segments. |

### `processing`

| Key | Default | Notes |
|-----|---------|-------|
| `chunk_size` / `chunk_overlap` | `1000` / `200` | Flat (non-structured) documents and audio. |
| `parent_chunk_size` / `parent_chunk_overlap` | `10000` / `400` | Parent context returned at retrieval time. |
| `child_chunk_size` / `child_chunk_overlap` | `2000` / `200` | Children are embedded for precise matching. |
| `max_retries` | `3` | Per-file retry limit before `failed`. |

Sizes are in characters (~4 chars/token).

### `document_images`

Docling can caption images and figures via a local Ollama vision model. Captions
are folded into the converted markdown, chunked, and embedded.

| Key | Default | Notes |
|-----|---------|-------|
| `descriptions_enabled` | `true` | Set `false` to skip vision calls entirely. |
| `formats` | `.pdf`, `.docx`, `.pptx`, `.xlsx` | |
| `api_url` | `http://localhost:11434/v1/chat/completions` | Local Ollama OpenAI-compatible endpoint. |
| `model` | `gemma4:12b-mlx` | Vision model for image descriptions. |
| `max_completion_tokens` | `200` | Per-image caption length cap. |
| `timeout_seconds` | `180` | |
| `concurrency` | `3` | Parallel caption requests during first conversion. |
| `ocr_enabled` | `false` | RapidOCR dominates runtime on digital PDFs; enable only for scans. |
| `images_scale` | `2.0` | |
| `generate_picture_images` | `true` | |

Converted markdown is cached in `processing_artifacts`, so re-embeds skip Docling
and vision work. Concurrency mainly helps the first conversion of each file.

### `v2` rollout flags

Phase 1 (structure-aware chunking, contextual headers, parent-child retrieval)
is enabled. Later phases stay off until validated on a small folder.

| Key | Default | Notes |
|-----|---------|-------|
| `structure_aware_chunking_enabled` | `true` | Heading-aware chunks from Docling markdown. |
| `contextual_embeddings_enabled` | `true` | Prepends a compact context header (filename fields, folder, title, section path, chunk type) to embedded text. Built in code — see `structure._context_header`. |
| `parent_child_retrieval_enabled` | `true` | Embed children; return linked parents for context. |
| `hybrid_search_enabled` | `false` | |
| `reranker_enabled` | `false` | |
| `entity_extraction_enabled` | `false` | Knowledge graph — all three graph flags must be on for sync auto-refresh. |
| `relationship_extraction_enabled` | `false` | |
| `graph_retrieval_enabled` | `false` | |
| `sync_interval_seconds` | `300` | Default interval for `sync` when `--interval` is omitted. |
| `graph_ollama_base_url` | `http://localhost:11434` | Override for graph extraction LLM calls. |

Expected `embedding_content_version` with contextual headers enabled:
`markdown-headings-ctx-qwen3-v1`.

### `v3`

| Key | Default | Notes |
|-----|---------|-------|
| `knowledge_os_enabled` | `false` | |
| `summaries_enabled` | `false` | |
| `communities_enabled` | `false` | |
| `graph_metadata_enabled` | `false` | |
| `knowledge_retrieval_enabled` | `false` | |
| `graph_export_enabled` | `true` | Snapshot export for `era_graph_web`. |
| `summary_model` | `extractive-local` | |
| `community_algorithm` | `relationship-neighborhood` | |

### `extensions`

- **audio:** `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.mp4`, `.mov`
- **documents:** `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.txt`

### `huggingface.token`

Used only for first-time model downloads (MLX Whisper repo). After `bootstrap`
caches models locally you can run fully offline. Prefer the `HF_TOKEN` env var
over storing a token in the file.

## Fresh-Index Foundation

For a clean rebuild, clear the Era Vault index tables, then run a small pilot
before indexing the full corpus. This keeps the `era_vault` database, schema,
indexes, pgvector extension, and `schema_migrations` intact while removing old
registry rows, queue state, chunks, embeddings, graph data, and conversion cache.
Because `processing_artifacts` is cleared too, the first full run will pay
Docling, vision-caption, and conversion costs again.

Current decisions (matching `config.yaml`):

- Embeddings: `qwen3-embedding:0.6b`, `1024` dimensions, `32k` context.
- Vector index: `HNSW` over `document_chunks.embedding vector(1024)`.
- Chunking: parent-child retrieval on. Children `2000` chars; parents `10000` chars.
- Context: structure-aware chunking + code-built contextual headers (`v2`).
- Document images: captions on (`gemma4:12b-mlx`), concurrency `3`, OCR off.
- Graph extraction model is configured (`qwen3.5:35b`) but v2 graph flags are off.

Clean-reset runbook:

```bash
cd era_indexer

# Optional but strongly recommended: backup era_vault before clearing data.
pg_dump -h 192.168.50.75 -p 15432 -U era -d era_vault \
  -Fc -f ~/era_vault_backup_$(date +%Y%m%d).dump

# Destructive reset of Era Vault indexed data only.
# Refuses to run unless current_database() is era_vault and the confirm string matches.
python -m truncate_all_career_history --confirm TRUNCATE_ERA_VAULT_DATA
```

```bash
ollama pull qwen3-embedding:0.6b   # Mac indexer host
ollama pull qwen3-embedding:0.6b   # NAS Ollama host (era_mcp)
ollama pull gemma4:12b-mlx         # if document_images.descriptions_enabled

# First pilot only. With the current config, source_directories already points
# at /Volumes/homes/Erathia/Career/13. VisionTech, so do not pass
# --folder "13. VisionTech" or the path will be doubled.
python -m career_history.cli update-documents --limit 10
python -m career_history.cli status
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

Only after the pilot shows `markdown-headings-ctx-qwen3-v1`, `1024`-dim
embeddings, non-zero parent chunks, and linked children should you index the
rest of the corpus.

## Daily usage

```bash
# Update everything (discover + process all changed files)
python -m career_history.cli update

# Update only documents
python -m career_history.cli update-documents

# Update only audio/video meeting files
python -m career_history.cli update-meetings

# Update one folder (name must match a path segment under source_directories)
python -m career_history.cli update --folder "13. VisionTech"

# Process up to 5 files this run (good for testing)
python -m career_history.cli update --folder Meetings --limit 5

# Split runs also support folder + limit
python -m career_history.cli update-documents --folder Research --limit 5
python -m career_history.cli update-meetings --folder Meetings --limit 5

# Reprocess already-indexed documents, then rebuild with current settings
python -m career_history.cli reindex-documents
python -m career_history.cli update-documents

# Continuously sync new/changed files (default interval from v2.sync_interval_seconds)
python -m career_history.cli sync --interval 300

# Run one sync cycle and exit — useful for cron/system schedulers
python -m career_history.cli sync --once

# Just see what's pending
python -m career_history.cli status
python -m career_history.cli status --folder Meetings

# Retry failed items
python -m career_history.cli retry
python -m career_history.cli retry --folder Meetings
```

## Layer 1: entities, facts & seeding (additive — no re-embed)

Layer 1 builds the **entity substrate** the agent reasons over (people, projects,
relationships, and **decisions/commitments/events**). It reads already-indexed
chunks and writes new rows — **it never re-embeds or re-chunks**.

```bash
# Deterministic project entities from the folder taxonomy (no LLM, fast).
# Configure seed.project_roots in config.yaml first. Also runs inside `discover`.
python -m career_history.cli seed-entities --folder "14. ST-Engg"

# DOCUMENT-LEVEL extraction (recommended at scale): ONE LLM call per FILE, not
# per chunk. For an 81k-chunk vault that's ~hundreds of calls instead of tens of
# thousands. Folder-scoped, incremental (resumable), rebuilds the snapshot.
python -m career_history.cli extract-documents --folder "14. ST-Engg"

# CHUNK-LEVEL extraction (per chunk → finest granularity, but infeasible on a
# large corpus — one LLM call per chunk). Use only on small/targeted scopes.
python -m career_history.cli graph-refresh --folder "14. ST-Engg" --limit 50
python -m career_history.cli graph-status        # per-chunk extraction progress
```

> **Pick the right granularity.** `extract-documents` extracts entities/
> relationships/facts once per file (chunks concatenated, capped at
> `MAX_DOC_CHARS`) — the same entities recur across a file's chunks, so this
> captures them at a fraction of the cost. Use a **non-thinking** model
> (`graph_extraction_model`: gemma/llama; reasoning models return empty under
> forced JSON) and raise `graph_extraction_timeout` for long local calls.

Notes:

- **`graph-refresh` extracts regardless of the `v2` flags.** `entity_extraction_enabled` /
  `relationship_extraction_enabled` / `graph_retrieval_enabled` only gate (a)
  auto-refresh during `update`/`sync` (all three must be true) and (b) whether
  retrieval *uses* the graph. To populate data you just run the command.
- **One pass, not three.** Entities, relationships, and facts come from a single
  LLM call per chunk (`graph.py`, `EXTRACTOR_VERSION = entity-rel-facts-v2`).
- **Incremental.** `graph_extraction_state` tracks per-chunk version+hash, so
  re-runs skip done chunks; `--force` re-extracts.
- **Cost.** ~15–40s/chunk on the local model — pilot a folder, validate quality,
  then roll out. Point `models.graph_extraction_model` at your reasoning model
  (e.g. `gemma4:31b-mlx`).
- **Read side.** `era_mcp` serves the result via `/entities/*`, `/relationships/search`,
  `/facts/search`, `graph_only`, and `/knowledge/search` — no MCP change needed
  to see entities/relationships; facts get their own endpoints.

## How "update" works

`python -m career_history.cli update` is `discover` followed by `run`. It uses
the default run settings from `career_history.config`, so it still handles both
documents and audio/video files. `update-documents` and `update-meetings` use
their respective run profiles.

1. **discover** walks every directory listed in `source_directories`, hashes
   each file, and inserts/updates rows in `file_registry`. Unchanged files
   (matching SHA-256) are skipped. Changed and new files get enqueued as
   `pending` in `processing_queue`. Files that no longer exist on disk are
   removed from the registry (cascading to their chunks and segments).
2. **run** pulls pending items and pushes each through its pipeline stages,
   committing state after each stage. If the process dies mid-stage, the next
   `run` picks up where it left off.

`python -m career_history.cli sync` is a continuous wrapper around the same
discover + run flow. It does not introduce a separate indexing path; each cycle
still hashes files, enqueues only new or changed files, and resumes from
`processing_queue`.

Status moves through:

- Audio: `pending` → `transcribing` → `chunking` → `embedding` → `done`
- Documents: `pending` → `converting` → `chunking` → `embedding` → `done`
- On exception: → `failed` with error message and incremented attempt count

## Schema notes

- `document_chunks.embedding` is `vector(1024)` to match
  `models.embedding_model` / `models.embedding_dim`. If you change dimension,
  update `schema.sql`, add a migration, and re-embed everything.
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
- V2 schema changes are additive migrations. `python -m career_history.cli init`
  applies `schema.sql` and then any unapplied files in `migrations/`;
  `migrate` can apply only pending migrations later. Rollback is explicit via
  `migrate-rollback` and matching `.rollback.sql` files.
- Structure-aware, contextual, and parent-child document indexing are controlled
  by `v2.structure_aware_chunking_enabled`,
  `v2.contextual_embeddings_enabled`, and
  `v2.parent_child_retrieval_enabled`. Keep the full corpus run blocked until a
  small folder has been validated.

## Troubleshooting

**Audio transcription import/runtime error**: ensure `mlx-whisper` is installed
(`pip install mlx-whisper`) and `ffmpeg` is on PATH (`brew install ffmpeg`). MLX
Whisper requires Apple Silicon; it will not run on Intel/x86 or inside a
non-Apple Docker host.

**`could not connect to server` from Postgres**: check that pgvector is
installed (`CREATE EXTENSION vector;` in the database), `ERA_VAULT_DB_*` or
`database.connection_string` is correct, and that the Mac can reach the
Synology on port 15432.

**Ollama warmup failed**: run `ollama serve` and
`ollama pull qwen3-embedding:0.6b`.

**Slow document conversion on digital PDFs**: keep `document_images.ocr_enabled`
at `false`. OCR was the main source of `RapidOCR returned empty result` spam.
If captions are still too slow, lower `concurrency` or switch to a smaller vision
model before re-enabling OCR.

**Files get marked `failed`**: run `python -c "from career_history import config, db;
config.load(); print(db.pending_files())"` to inspect, or query
`processing_queue.error_message` directly. After fixing,
`python -m career_history.cli retry` to re-enqueue.

## Related components

This indexer is the **write** half of Era Vault. The other components read or
visualize the same data:

- [`era_mcp`](../era_mcp) — read half: embeds queries with the same Ollama model
  (`qwen3-embedding:0.6b`), hybrid vector + FTS retrieval, parent-chunk context,
  and OpenAPI tools (`search_vault`, `ask_vault`, `indexing_status`).
- [`era_auditor`](../era_auditor) — Knowledge Steward: scans the same vault
  roots, reads indexer embeddings for semantic dupes and placement simulation.
- [`era_graph_web`](../era_graph_web) — graph viewer at `/graph`, fed by
  `graph-refresh` snapshots served through MCP.

See the [repo masterplan](../README.md) for the full architecture.
