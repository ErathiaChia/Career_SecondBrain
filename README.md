# Career SecondBrain (Era Vault)

Personal knowledge vault with RAG search, knowledge-graph exploration, and
AI-assisted cleanup. Four cooperating components share one Postgres database
(`era_vault`) and the same vault filesystem roots.

## The four agents

| Component | Role | Runs on | README |
|-----------|------|---------|--------|
| [`era_indexer`](era_indexer/) | **Write** — discover, convert, chunk, embed, graph extract | Mac | [era_indexer/README.md](era_indexer/README.md) |
| [`era_mcp`](era_mcp/) | **Read** — hybrid search, `/ask` agent, graph API | NAS Docker (:8808) | [era_mcp/README.md](era_mcp/README.md) |
| [`era_auditor`](era_auditor/) | **Steward** — vault hygiene, semantic dupes, Librarian training | Mac | [era_auditor/README.md](era_auditor/README.md) |
| [`era_graph_web`](era_graph_web/) | **Visualize** — Sigma.js graph viewer at `/graph` | Built into MCP image | [era_graph_web/README.md](era_graph_web/README.md) |

## How they work together

```mermaid
flowchart TB
  subgraph mac [Mac - write and steward]
    Vault[Vault filesystem on NAS mount]
    IDX[era_indexer]
    AUD[era_auditor]
    MacLLM[Ollama qwen3.5:9b-mlx]
    Vault --> IDX
    Vault --> AUD
    IDX --> MacLLM
  end

  subgraph synology [Synology NAS]
    PG[(Postgres era_vault + pgvector)]
    Ollama[Ollama qwen3-embedding:0.6b]
    MCP[era_mcp :8808]
    GraphUI[era_graph_web /graph]
    MCP --> GraphUI
    MCP --> Ollama
  end

  IDX -->|write chunks embeddings graph| PG
  AUD -->|write auditor_* tables| PG
  AUD -->|read embeddings for dupes/placement| PG
  MCP -->|read-only search| PG
  Clients[Open WebUI / browsers] --> MCP
```

**Indexer** (`era_indexer`) walks vault files on the Mac, converts documents and
transcribes audio, chunks text, embeds via Ollama, and optionally extracts
entities and relationships. It writes to `file_registry`, `document_chunks`,
`parent_chunks`, graph tables, and `graph_snapshots`. The Python package inside
this folder is `career_history` (CLI: `python -m career_history.cli`).

**API server** (`era_mcp`) is the read half. It embeds incoming queries with the
same model, runs hybrid vector + full-text retrieval, and exposes OpenAPI tools
(`search_vault`, `ask_vault`, `indexing_status`, …) for Open WebUI. It never
writes chunks or embeddings. When built with the graph frontend, it serves
`era_graph_web` at `/graph`.

**Knowledge Steward** (`era_auditor`) scans the same vault roots read-only,
classifies folders, and writes findings to `auditor_*` tables. It optionally
reads indexer embeddings for semantic-duplicate detection and Librarian placement
simulation. It does not move, rename, or delete files.

**Graph viewer** (`era_graph_web`) is a frontend only. Indexer generates graph
snapshots in Postgres; MCP serves them at `GET /graph/snapshot`; the viewer
renders them with Sigma.js.

## Operational topology

| Where | What runs |
|-------|-----------|
| **Mac** | `era_indexer`, `era_auditor`, heavy LLM (`qwen3.5:9b-mlx` for graph extraction and `/ask` synthesis) |
| **Synology NAS** | Postgres + pgvector, NAS Ollama (`qwen3-embedding:0.6b` for query embeddings), `era_mcp` Docker container |

Schedule heavy indexer work on the Mac from the NAS when needed, e.g.:

```bash
ssh mac "cd ~/GitHub/Career_SecondBrain/era_indexer && \
  python -m career_history.cli update --folder Meetings"
```

## Shared contracts

Copy [`.env.example`](.env.example) to `.env` at the repo root. All four
components read `ERA_VAULT_DB_*` from this file (the auditor auto-builds its
database URL from the same vars).

| Contract | Value | Must match across |
|----------|-------|-------------------|
| Database | `era_vault` on Synology Postgres | indexer, MCP, auditor |
| DB vars | `ERA_VAULT_DB_HOST`, `PORT`, `NAME`, `USER`, `PASSWORD` | `.env` → all services |
| Embedding model | `qwen3-embedding:0.6b` (1024-dim) | Mac indexer, NAS Ollama, MCP `EMBEDDING_MODEL` |
| Vault roots | Same `source_directories` paths | `era_indexer/config.yaml`, `era_auditor/config.yaml` |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` | auditor (classification), MCP (`/ask` fallback) |

## Typical workflows

**Index new or changed files** (Mac):

```bash
cd era_indexer
python -m career_history.cli update
python -m career_history.cli status
```

**Search the vault** (via MCP on NAS, or locally on :8808):

```bash
curl -X POST http://localhost:8808/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"voice authentication proposal","top_k":5}'
```

Or connect [Open WebUI](https://openwebui.com/) to `http://<host>:8808/openapi.json`.

**Refresh and view the knowledge graph**:

```bash
cd era_indexer
python -m career_history.cli graph-refresh
python -m career_history.cli graph-status
```

Then open `http://<host>:8808/graph/` in a browser.

**Project intelligence** (Mac, after `python -m career_history.cli migrate`):

```bash
cd era_auditor && python -m auditor.cli manifest export   # neutral project manifest for the indexer
cd ../era_indexer && python -m career_history.cli monitor  # projects -> changes -> conflicts -> state -> digest
```

Then ask the Open WebUI agent things like "brief me on CL89", "what changed this
week", or "prep me for the HLB meeting with Alice". The `/projects/*` tools are
listed in [`era_mcp/README.md`](era_mcp/README.md#project-intelligence).

**Run the Knowledge Steward** (Mac):

```bash
cd era_auditor
python -m auditor.cli run
python -m auditor.cli report latest
```

## Repo layout

```text
Career_SecondBrain/
├── .env.example          Shared config template (hosts, DB, policy switches)
├── era_indexer/          Write pipeline (package: career_history)
├── era_mcp/              Read API server + Docker deploy
├── era_auditor/          Knowledge Steward agent
├── era_graph_web/        Graph viewer (built into era_mcp image)
├── docs/                 models.md + ADRs (docs/adr/)
└── local/                GIT-IGNORED private data (see below)
```

## Private data, local-first policy and tests

Organisation policy: nothing sensitive (client/project names, vault content)
goes to a cloud service. Concretely:

- **No cloud LLM.** `CLOUD_LLM_OPTIN=0` (default) disables the OpenAI fallback
  in `era_mcp` and the auditor's cloud client; when the Mac LLM is unreachable
  `/ask` returns 503 rather than calling out. See `docs/adr/0001-local-only-llm.md`.
- **`local/` is never committed.** It holds the auditor registries
  (`local/auditor/rules/*.yaml`, pointed to by `AUDITOR_REGISTRY_DIR`), auditor
  reports, eval question sets and runs, and the target brief. Templates with
  synthetic names are committed as `*.example.yaml`.
- **Docs and tests use synthetic names** (`CL89`, `Acme Bank`, `Corp-A`, ...);
  `era_auditor/tests/fixtures/registries/` are scrubbed copies of the real
  registries so unit tests never read real data.
- Hosts are `${NAS_HOST}` / `${MAC_HOST}` from `.env`; no IPs in git.

Tests (no DB, no LLM; ~200 cases across the three packages):

```bash
make test
```

Per package: `make test-mcp`, `make test-indexer`, `make test-auditor`. The
integration harness (`make test-integration`) needs Docker. `make check-models`
verifies the configured model tags on the runtime Mac (`docs/models.md`).

## NAS Docker deployment notes

This repository is developed locally and pushed to GitHub. A sanitized working
copy can also be synced to the Synology NAS for Docker-based services.

Current local paths:
- Local repo: `~/GitHub/Career_SecondBrain`
- NAS mount: `/Volumes/homes/Erathia`
- NAS Docker mirror: `/Volumes/docker/Career_SecondBrain`

Do not sync secrets or machine-local artifacts:
- `.env`, `.env.*`
- real `config.yaml` files
- `.venv/`, `node_modules/`, `dist/`
- caches, `.DS_Store`, `*.tsbuildinfo`, `*.tar.gz`

Dry-run sync before deploying:

```sh
rsync -avhn --delete \
  --exclude ".git/" \
  --exclude ".env" \
  --exclude ".env.*" \
  --exclude "config.yaml" \
  --exclude ".venv/" \
  --exclude "node_modules/" \
  --exclude "__pycache__/" \
  --exclude ".pytest_cache/" \
  --exclude "dist/" \
  --exclude ".DS_Store" \
  --exclude "*.tsbuildinfo" \
  --exclude "*.tar.gz" \
  ~/GitHub/Career_SecondBrain/ \
  /Volumes/homes/Erathia/Career/Career_SecondBrain/
```

Deploy the API server on the NAS from `era_mcp/`:

```bash
cd era_mcp
docker compose up -d --build
```

See [era_mcp/README.md](era_mcp/README.md) for environment variables and Open WebUI setup.
