# Era Vault API Server (`era_mcp`)

The **read** half of Era Vault. A lightweight FastAPI service that exposes
semantic search over your indexed knowledge base as REST endpoints with an
auto-generated OpenAPI spec, so [Open WebUI](https://openwebui.com/) (and any
OpenAPI tool client) can discover and call them as tools.

> **Naming note:** the folder is `era_mcp`, but this is an **OpenAPI REST
> server**, not a stdio MCP protocol server. Open WebUI registers each endpoint's
> `operation_id` (`search_vault`, `ask_vault`, …) as a callable tool.

See the [repo masterplan](../README.md) for how all four Era Vault components
fit together.

## Ecosystem

| Component | Role |
|-----------|------|
| [`era_indexer`](../era_indexer) | Write — discover, convert, chunk, embed, graph extract |
| **era_mcp** (this) | Read — hybrid search, `/ask` agent, OpenAPI tools |
| [`era_auditor`](../era_auditor) | Steward — vault hygiene, semantic dupes, Librarian training |
| [`era_graph_web`](../era_graph_web) | Visualize — Sigma.js graph viewer at `/graph` |

The [`era_indexer`](../era_indexer) is the write half: it walks your files,
transcribes/converts them, chunks, embeds via Ollama, and stores everything in
Postgres + pgvector. This server only reads from that same database.

```
  Open WebUI  ──(OpenAPI tools)──►  era_mcp (this server, :8808)
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                            ▼
                  Postgres + pgvector            Ollama (embeddings)
                  (document_chunks, …)           (qwen3-embedding:0.6b)
```

The server is read-only with respect to the vault: it embeds the incoming
query, runs retrieval, and returns results. It never writes chunks or
embeddings — that is the indexer's job.

## Retrieval

`/search` performs **hybrid search** over `document_chunks`:

1. **Dense vector** — cosine nearest neighbors on `embedding` (pgvector).
2. **Lexical full-text** — `ts_rank` over `search_vector` (Postgres FTS,
   `simple` config).

The two candidate pools are fused with **Reciprocal Rank Fusion (RRF)**:
`sum(weight / (rrf_k + rank))`, with the vector channel weighted above FTS.
Surrounding chunks from the same file are merged in (`context_window`) so the
model gets broader context. `/knowledge/search` wraps this with best-effort
graph/summary channels (entities, relationships, communities, document
summaries) that degrade to empty lists until the knowledge graph is populated.

## Endpoints

OpenAPI spec is served at `/openapi.json`; interactive docs at `/docs`.

| Tool (operation_id)      | Method | Path                              | Purpose |
| ------------------------ | ------ | --------------------------------- | ------- |
| `ask_vault`              | POST   | `/ask`                            | **Agentic answer**: rewrite → retrieve → rerank → graph → synthesized answer with `[n]` citations |
| `search_vault`           | POST   | `/search`                         | Hybrid semantic search over chunks |
| `search_vault_v3`        | POST   | `/knowledge/search`               | Knowledge packet: chunks + entities + relationships + communities + summaries |
| `search_entities`        | GET    | `/entities/search`                | Search canonical graph entities |
| `search_relationships`   | GET    | `/relationships/search`           | Search typed relationships + evidence |
| `search_communities`     | GET    | `/communities/search`             | Search graph communities |
| `get_document_summary`   | GET    | `/documents/summary`              | Latest summary for a file (by id or name) |
| `get_section_summary`    | GET    | `/sections/{section_id}/summary`  | Latest summary for a section |
| `get_entity_neighbors`   | GET    | `/entities/{entity_id}/neighbors` | Graph neighbors for one entity |
| `get_graph_subgraph`     | GET    | `/graph/subgraph`                 | Graph export, optionally scoped to one entity |
| `indexing_status`        | GET    | `/status`                         | File counts per processing stage |
| `list_folders`           | GET    | `/folders`                        | All top-level folders in the vault |
| `list_folders_tree`      | GET    | `/structure/folders`              | **Census**: complete list of child folders/projects under a path (or matched from a question), with counts |
| `folder_overview`        | GET    | `/structure/overview`             | Compact live overview of the whole vault folder layout |
| `graph_snapshot`         | GET    | `/graph/snapshot`                 | Latest Sigma.js graph snapshot |
| `graph_status`           | GET    | `/graph/status`                   | Graph extraction + snapshot status |

If a built [`era_graph_web`](../era_graph_web) bundle is present
(`era_graph_web/dist`), the interactive graph viewer is mounted at `/graph`.

### `/search` request body

```json
{
  "query": "voice authentication proposal for Accrete",
  "top_k": 20,
  "folder": null,
  "kind": null,
  "context_window": 3
}
```

- `kind`: `"document"` or `"audio"` to restrict by source type.
- `folder`: restrict to one top-level folder (see `/folders`).
- `context_window`: surrounding chunks to include each side; `0` = matched chunk only.

## Agentic `/ask` (router + ReAct Judge loop)

When `AGENTIC_ASK_ENABLED=1` (default), `/ask` is an **agent**, not a single pass.
See [`docs/agentic_mcp_design.md`](docs/agentic_mcp_design.md) for the full design.

1. **Route** — census/enumeration questions ("how many / list all projects /
   folders") go to the **structural inventory** (a complete `file_registry`
   listing); everything else goes to semantic retrieval. Semantic search can
   never *enumerate*, so this is the fix for "list all my projects".
2. **Confidence gate** — one retrieval pass; if the top (normalized) rerank score
   is ≥ `STRONG_RERANK_THRESHOLD`, answer directly (fast single pass).
3. **ReAct Judge loop** (below the gate) — a **stateful** Judge (`LLM_JUDGE_MODEL`,
   e.g. `gemma4:31b-mlx`, on the Mac) carries a **trajectory** (memory of prior
   thoughts, queries, and what they returned) across **≤ `AGENT_MAX_ITERS`**
   searches. Each turn it knows how many searches remain and picks an action:
   `research` (re-write + re-search), `structural` (switch to the inventory), or
   `answer`. Bounded by `AGENT_TIME_BUDGET` and a no-new-docs early exit.
4. **Synthesis** — answers from the best pool **and** the trajectory. If the cap
   is hit without a confident answer it returns a **best-effort partial answer**
   and says so plainly.

The response adds: `route`, `confidence`, `sufficient`, `gaps`, `iterations`,
`queries_tried`, `max_iters_reached`, and `trajectory` (the ReAct steps) — so the
Open WebUI agent can relay partial answers, surface gaps, or ask a follow-up.
Always degrades to reranked chunks (`degraded: true`) if the judge LLM is down.
Set `AGENTIC_ASK_ENABLED=0` for the legacy single-pass `/ask` below.

> **Load the Open WebUI side too:** [`prompts/ai_secondbrain_agent.md`](prompts/ai_secondbrain_agent.md)
> is the system prompt for the front-facing **AI Second Brain Agent** — it tells
> that agent how to call these tools and act on the structured JSON, and has a
> `{{FOLDER_STRUCTURE}}` block you fill in yourself (fetch the current text from
> `/structure/overview`).

### Legacy single-pass `/ask`

`/ask` turns the server from a chunk-returner into an agent. One request runs the
full pipeline server-side:

1. **Query rewrite** — an LLM normalizes the question into a keyword-rich search
   string (+ optional sub-queries / HyDE).
2. **Hybrid retrieve** — the same RRF search as `/search`, pulling the full
   candidate pool.
3. **Rerank** — a cross-encoder re-scores the pool on the precise child text
   before parent expansion.
4. **Graph augmentation** — best-effort entities/relationships from the graph
   tables (empty until the indexer populates them).
5. **Synthesis** — an LLM writes an answer that cites sources inline as `[n]`,
   mapped 1:1 to the returned `citations`/`chunks`.

```json
{ "query": "what did we propose to Accrete for voice auth?",
  "top_k": 20, "folder": null,
  "use_graph": true, "rewrite": true, "rerank": true, "synthesize": true }
```

The response always includes `chunks` + `citations`; `answer` is `null` with
`degraded: true` when the LLM is unavailable (see below). `provider` echoes which
LLM/fallback is wired.

### Where the models run (NAS ↔ Mac)

era_mcp runs on the always-on NAS, but the heavy LLM does **not** — the NAS
Ollama (~6 GB) only serves `qwen3-embedding:0.6b` embeddings (and optionally a
small reranker). The synthesis/query-rewrite LLM runs on the **M1 Max**
(`LLM_PRIMARY_BASE_URL`), with **OpenAI as fallback** (`OPENAI_API_KEY`).

**Graceful degradation** (the agent never hard-fails on LLM issues):

| Condition | Result |
| --- | --- |
| Mac LLM down | falls back to OpenAI |
| Mac down + no OpenAI key | `answer: null`, `degraded: true`, **reranked `chunks` still returned** |
| Reranker down / `RERANK_ENABLED=0` | original RRF order |
| Query rewrite fails | original query used |
| Graph tables empty | empty graph channels |

A short (~3 s) connect timeout means an asleep/off Mac fails fast instead of
hanging. Keep the Mac warm with `caffeinate -di` for consistent latency.

### NAS → Mac background refresh

Because the Mac is a reachable server, schedule heavy indexer work on it from the
NAS rather than the tiny NAS Ollama — e.g. a cron entry:

```bash
ssh mac "cd ~/GitHub/Career_SecondBrain/era_indexer && \
  python -m career_history.cli v3-refresh --folder 'Meetings'"
```

## Configuration

All configuration is via environment variables (no YAML). On the NAS these are
injected by Docker; locally, export them or use an `.env` file.

| Variable                | Default                     | Notes |
| ----------------------- | --------------------------- | ----- |
| `ERA_VAULT_DB_PASSWORD` | — (**required**)            | Postgres password |
| `ERA_VAULT_DB_HOST`     | `postgres`                  | Postgres host |
| `ERA_VAULT_DB_PORT`     | `15432`                     | Postgres port (NAS-mapped) |
| `ERA_VAULT_DB_NAME`     | `era_vault`                 | Database name |
| `ERA_VAULT_DB_USER`     | `era`                       | Database user |
| `OLLAMA_BASE_URL`       | `http://ollama:11434`       | Ollama endpoint for query embedding |
| `EMBEDDING_MODEL`       | `qwen3-embedding:0.6b`    | Must match the model the indexer used |
| `DEFAULT_TOP_K`         | `20`                        | Default results when `top_k` omitted |
| `CANDIDATE_POOL`        | `50`                        | Candidates pulled per channel before RRF (≥ `top_k`) |
| `RRF_K`                 | `60`                        | RRF constant; higher dampens high ranks |
| `RRF_VECTOR_WEIGHT`     | `1.0`                       | Weight of the dense-vector channel |
| `RRF_FTS_WEIGHT`        | `0.5`                       | Weight of the full-text channel |

> The embedding model **must** match the one used by the indexer, or query and
> document vectors will be incomparable. Default is `qwen3-embedding:0.6b`
> (1024-dim), matching `document_chunks.embedding vector(1024)`.

### V3 retrieval relevance

Four changes that improve *which* chunks come back, all read-side (no re-embed):

1. **Query instruction (qwen3).** `qwen3-embedding` is instruction-tuned: the
   query is embedded with a task instruction while the indexer embeds documents
   raw. This asymmetry matches the model's training. Turn off for a
   non-instruction model like `bge-m3`.
2. **Filename / folder / path search.** The lexical (FTS) channel also matches
   `file_name` + `folder` + `file_path`, so short queries — acronyms (`IBF`),
   customer names, RFP numbers — hit the path a file was filed under even when
   the body never spells them out (`01_IBF` is normalized to `01 IBF`).
3. **Multi-query fusion.** `/ask` runs the rewritten query **and** the
   rewriter's sub-queries, merges the candidate pools, and reranks once against
   the original question (previously the sub-queries were generated then
   discarded).
4. **Adaptive breadth.** The rewriter classifies each question `simple` /
   `moderate` / `complex`; `/ask` sizes how many chunks to retrieve+cite
   accordingly (default `8` / `20` / `40`), bounded for a ~9B synthesis model.
   Send `"adaptive_k": false` to use the request's `top_k` instead.
5. **Document-first assembly.** `/ask` groups the reranked passages by document
   and emits them document-by-document (in reading order) rather than as a flat
   scattered list, so the model sees coherent documents. Bounded by
   `DOC_FIRST_MAX_DOCS` / `DOC_FIRST_MAX_PARENTS_PER_DOC` (not "every chunk").
   Results carry a `doc_rank`; synthesis presents sources under per-document
   headers. `/search` is unchanged.

| Variable                  | Default | Notes |
| ------------------------- | ------- | ----- |
| `QUERY_INSTRUCTION_ENABLED` | `1`   | Wrap queries with the instruction prefix (qwen3). `0` for bge-m3. |
| `QUERY_INSTRUCTION`       | _(built-in)_ | The task instruction text. |
| `FILENAME_SEARCH_ENABLED` | `1`     | Match FTS against file_name/folder/path. `0` if too slow on a huge corpus. |
| `LEXICAL_PATH_WEIGHT`     | `0.5`   | ts_rank multiplier for a path match vs a body match. |
| `MULTI_QUERY_ENABLED`     | `1`     | Retrieve for sub-queries too and fuse the pools. |
| `ADAPTIVE_TOPK_ENABLED`   | `1`     | Size top_k to question complexity. |
| `TOPK_SIMPLE` / `TOPK_MODERATE` / `TOPK_COMPLEX` | `8` / `20` / `40` | Per-complexity chunk counts. |
| `DOC_FIRST_ASSEMBLY_ENABLED` | `1` | Group `/ask` passages by document (vs flat list). |
| `DOC_FIRST_MAX_DOCS`      | `8`     | Max distinct documents in the assembled context. |
| `DOC_FIRST_MAX_PARENTS_PER_DOC` | `3` | Max passages kept per document. |

**Measuring it.** [`tools/scorecard.py`](tools/scorecard.py) scores whether the
right document is retrieved, and at what rank, across a list of real questions —
use it to compare before/after. Copy `tools/scorecard_questions.example.json` to
`tools/scorecard_questions.json`, fill in your questions, start the server, then:

```bash
cd era_mcp
python -m tools.scorecard --endpoint ask     # full /ask pipeline (needs the Mac LLM)
python -m tools.scorecard --endpoint search  # pure retrieval, no LLM required
```

### Agent layer (`/ask`) variables

| Variable                | Default                          | Notes |
| ----------------------- | -------------------------------- | ----- |
| `LLM_PRIMARY_BASE_URL`  | `http://host.docker.internal:11434` | Mac LLM endpoint (set to the Mac LAN IP from the NAS) |
| `LLM_PRIMARY_KIND`      | `ollama`                         | `ollama` or `openai_compat` (mlx_lm.server / llama.cpp) |
| `LLM_PRIMARY_MODEL`     | `qwen3.5:9b-mlx`                 | Synthesis + query-rewrite model on the Mac |
| `LLM_PRIMARY_TIMEOUT`   | `30`                             | Read timeout (s); connect timeout is fixed at ~3 s |
| `LLM_FALLBACK_ENABLED`  | `1`                              | Use OpenAI when the Mac is unreachable |
| `OPENAI_API_KEY`        | _(unset)_                        | Unset = fallback disabled (never required) |
| `OPENAI_BASE_URL`       | `https://api.openai.com/v1`      | OpenAI-compatible base URL |
| `OPENAI_MODEL`          | `gpt-4.1-mini`                   | Fallback model |
| `LLM_MAX_TOKENS`        | `1024`                           | Max completion tokens |
| `LLM_TEMPERATURE`       | `0.1`                            | Sampling temperature |
| `RERANK_ENABLED`        | `1`                              | Cross-encoder rerank of the candidate pool |
| `RERANK_KIND`           | `llm_score`                      | `infinity` (TEI server) / `llm_score` (no extra server) / `none` |
| `RERANK_BASE_URL`       | `http://host.docker.internal:7997`  | Infinity/TEI endpoint (when `RERANK_KIND=infinity`) |
| `RERANK_MODEL`          | `BAAI/bge-reranker-v2-m3`        | Reranker model name |
| `RERANK_TIMEOUT`        | `15`                             | Rerank request timeout (s) |
| `QUERY_REWRITE_ENABLED` | `1`                              | LLM query rewriting before retrieval |
| `HYDE_ENABLED`          | `0`                              | Add a hypothetical-answer doc to the dense query |
| `QUERY_REWRITE_TIMEOUT` | `12`                             | Query-rewrite request timeout (s) |
| `AGENTIC_ASK_ENABLED`   | `1`                              | Router + ReAct Judge loop on `/ask`; `0` = legacy single pass |
| `LLM_JUDGE_MODEL`       | `gemma4:31b-mlx`                 | Reasoning model (Judge + synthesis) on the Mac |
| `AGENT_MAX_ITERS`       | `3`                              | Max Judge searches before a best-effort partial answer |
| `AGENT_TIME_BUDGET`     | `60`                             | Whole-run wall-clock budget (s) |
| `STRONG_RERANK_THRESHOLD` | `0.8`                          | Confidence gate (0-1): ≥ answers single-pass, < escalates to the loop |

### Enabling the cross-encoder reranker (Fix 4)

The default `RERANK_KIND=llm_score` reuses the synthesis LLM to score candidates —
cheap, but weaker. A real cross-encoder (`bge-reranker-v2-m3`) is the single
biggest retrieval-quality lever. Run one on the Mac and point era_mcp at it:

```bash
# On the Mac, once:
pip install "infinity-emb[all]"
# Start it (serves POST /rerank on :7997). Keep the Mac awake (caffeinate -di):
era_mcp/tools/run_reranker.sh
```

Then set on era_mcp (NAS container env / `.env`):

```
RERANK_KIND=infinity
RERANK_BASE_URL=http://<mac-lan-ip>:7997
RERANK_MODEL=BAAI/bge-reranker-v2-m3
```

**Confirm it's actually used** (it silently falls back to RRF order if the server
is unreachable): the `/ask` response now includes `"reranked": true` and
`"rerank_backend": {"kind": "infinity", ...}`, and chunks carry a `rerank_score`.
Re-run `tools/scorecard.py` before/after — expect the largest single jump in
"right doc at rank #1–3".

## Running locally

```bash
cd era_mcp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ERA_VAULT_DB_HOST=192.168.50.50
export ERA_VAULT_DB_PORT=15432
export ERA_VAULT_DB_NAME=era_vault
export ERA_VAULT_DB_USER=era
export ERA_VAULT_DB_PASSWORD=...        # required
export OLLAMA_BASE_URL=http://192.168.50.50:11434
export EMBEDDING_MODEL=qwen3-embedding:0.6b

python -m era_mcp            # or: python -m era_mcp.server
```

The server listens on `0.0.0.0:8808`. Verify:

```bash
curl http://localhost:8808/status
curl -X POST http://localhost:8808/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"voice authentication","top_k":5}'
```

Requirements are intentionally light (`fastapi`, `uvicorn`, `sqlalchemy`,
`psycopg2-binary`, `httpx`) — no `torch`, `whisperx`, or `docling`.

## Running on the NAS (Docker)

The [`Dockerfile`](Dockerfile) is a two-stage build: it compiles the
`era_graph_web` front-end (Node) and copies the bundle into the Python image so
`/graph` is served from the same container.

```bash
# from era_mcp/ (build context is the repo root)
docker compose up -d --build
```

[`docker-compose.yml`](docker-compose.yml) only manages this container; Postgres
and Ollama run as separate existing NAS containers, reached over their published
ports (e.g. DB on `192.168.50.50:15432`, Ollama on `192.168.50.50:11434`).
Adjust the `environment` block and the `../.env` file for your setup. The
container publishes port `8808`.

## Connecting Open WebUI

Add the server as an OpenAPI tool provider pointing at:

```
http://<host>:8808/openapi.json
```

Open WebUI reads the spec and registers each endpoint's `operation_id`
(`search_vault`, `indexing_status`, …) as a callable tool.

## Use cases — north-star capability map

The long-term target is 35 use cases across six clusters. They all read from a
**shared substrate**: *Engagements · People · Artifacts · Commitments · Decisions
· Events*. **Today the system has only ~1.5 of those six** — **Artifacts**
(indexed files/chunks, fully) and a thin **Engagements** layer (folder/project
enumeration via the structural tool). **People, Commitments, Decisions, and
Events do not exist as structured data yet** (the entity/graph tables exist but
extraction is off), and there is **no proactive ("push") layer** at all. So what
ships today is a strong *retrieval + agentic Q&A engine over documents*; most of
the list below is still aspirational. Status is honest, not optimistic:

- ✅ **works today** — supported by the shipped retrieval / agentic / structural layer
- 🟡 **partial** — approximable on demand via retrieval+synthesis (or partly in `era_auditor`), but not a built feature and missing the structured/stateful version
- ❌ **not yet** — needs substrate (People/Commitments/Decisions/Events/project-state) and/or a proactive scheduler that does not exist

**Continuity & synthesis**
| # | Use case | Status |
|---|---|---|
| 1 | Re-entry briefs (30-sec catch-up) | 🟡 doc-synthesis only; no real state/blockers/owed |
| 2 | Meeting debriefs (transcript → actions) | 🟡 transcripts indexed; extraction not built |
| 3 | Cross-project pattern matching | ✅ semantic search across projects |
| 4 | Question / clarification builder | 🟡 on-demand synthesis, not a feature |
| 5 | "What changed since X" diffs | ❌ needs an Events/version model |
| 6 | Next-best-action suggestion | ❌ needs cross-engagement state |

**Relationship & stakeholder**
| # | Use case | Status |
|---|---|---|
| 7 | Commitment tracking / slippage | ❌ no Commitments substrate, no watcher |
| 8 | Meeting prep briefs | 🟡 topic/person retrieval; no interaction history |
| 9 | Stakeholder profiles | ❌ no People entities |
| 10 | Entity disambiguation (the "Iris" problem) | ❌ entity layer empty |
| 11 | Contact-owed ledger | ❌ needs Commitments |
| 12 | Networking surfacing | ❌ needs People + relationships |

**Time & attention** (entirely *push* — we have no proactive layer)
| # | Use case | Status |
|---|---|---|
| 13 | Dependency / blocker watch | ❌ |
| 14 | Deadline proximity alerts | ❌ |
| 15 | Stale-thread nudges | ❌ |
| 16 | Time / leverage audit | ❌ no activity data captured |
| 17 | Scope-creep detection | ❌ needs scope baseline + compare |

**Drafting & communication**
| # | Use case | Status |
|---|---|---|
| 18 | Standup generator | ❌ no activity capture |
| 19 | Email triage + draft replies | ❌ email not ingested; no drafting |
| 20 | Follow-up drafting | 🟡 feasible from transcripts; not built |
| 21 | Status report generation | 🟡 synthesizable; not built |
| 22 | Onboarding pack generator | 🟡 like re-entry brief; not built |
| 23 | Proposal / SOW drafting | 🟡 retrieval scaffold via #29; not full draft |

**Governance & audit**
| # | Use case | Status |
|---|---|---|
| 24 | Decision log with rationale | ❌ no Decisions substrate |
| 25 | Risk register maintenance | ❌ |
| 26 | Knowledge gap detection | 🟡 folder-level in `era_auditor`; not content-level |
| 27 | Contradiction detection | ❌ needs decisions + reasoning |
| 28 | Document version reconciliation | 🟡 `era_auditor` detects version families; no diffing |

**Career positioning & reuse**
| # | Use case | Status |
|---|---|---|
| 29 | Prior-artifact surfacing | ✅ semantic search + reuse registry |
| 30 | Accomplishment logging | ❌ no ongoing capture |
| 31 | Estimation calibration | ❌ needs estimates + actuals |
| 32 | Reusable template extraction | 🟡 `era_auditor`-adjacent; not built |
| 33 | Win / loss capture | ❌ |
| 34 | Skill / experience inventory | ❌ (weakly synthesizable from docs) |
| 35 | Personal retrospective prompts | ❌ push + events |

**Tally: ~2 ✅ · ~11 🟡 · ~22 ❌.** The two that truly work (#3, #29) are pure
retrieval. To reach the rest, four things must be built — none exist today:

1. **Substrate / extraction** — populate **People, Commitments, Decisions,
   Events** (and project *state/timeline*) from documents + meeting transcripts.
   This is the entity/graph layer (currently switched off) *plus* new extractors
   for commitments/decisions/events. Unlocks ~20 of the ❌ items. The single
   biggest lever.
2. **Proactive ("push") layer** — a scheduler/watcher that runs without being
   asked and notifies on slippage, deadlines, stale threads, scope drift. Unlocks
   the entire Time & attention cluster + commitment tracking + nudges.
3. **Drafting features** — turn retrieval + state into drafts (standup, status
   report, follow-up, SOW). Synthesis exists; these specific workflows don't.
4. **New ingestion sources** — email (for triage/drafting) and activity/time
   data (for audits) — the vault is files-only today.

This is the natural next horizon after the agentic MCP, and it is exactly the
"project/entity brain" direction in [`docs/agentic_mcp_design.md`](docs/agentic_mcp_design.md)
and the project memory. **Scope note:** populating People/Decisions/Events is
substrate work that belongs in the indexer; the proactive layer is new. Neither
overlaps the Auditor/Librarian (vault cleanup).
