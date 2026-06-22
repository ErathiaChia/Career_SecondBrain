# Era Vault MCP / API Server

The **"read" half** of Era Vault. A lightweight FastAPI service that exposes
semantic search over your indexed knowledge base as REST endpoints with an
auto-generated OpenAPI spec, so [Open WebUI](https://openwebui.com/) (and any
OpenAPI tool client) can discover and call them as tools.

The [`era_indexer`](../era_indexer) is the "write" half: it walks your files,
transcribes/converts them, chunks, embeds via Ollama, and stores everything in
Postgres + pgvector. This server only reads from that same database.

```
  Open WebUI  ──(OpenAPI tools)──►  era_mcp (this server, :8808)
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                            ▼
                  Postgres + pgvector            Ollama (embeddings)
                  (document_chunks, …)           (nomic-embed-text)
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

## Configuration

All configuration is via environment variables (no YAML). On the NAS these are
injected by Docker; locally, export them or use an `.env` file.

| Variable                | Default                     | Notes |
| ----------------------- | --------------------------- | ----- |
| `ERA_VAULT_DB_PASSWORD` | — (**required**)            | Postgres password |
| `ERA_VAULT_DB_HOST`     | `postgres`                  | Postgres host |
| `ERA_VAULT_DB_PORT`     | `5432`                      | Postgres port |
| `ERA_VAULT_DB_NAME`     | `era_vault`                 | Database name |
| `ERA_VAULT_DB_USER`     | `era`                       | Database user |
| `OLLAMA_BASE_URL`       | `http://ollama:11434`       | Ollama endpoint for query embedding |
| `EMBEDDING_MODEL`       | `nomic-embed-text`          | Must match the model the indexer used |
| `DEFAULT_TOP_K`         | `20`                        | Default results when `top_k` omitted |
| `CANDIDATE_POOL`        | `50`                        | Candidates pulled per channel before RRF (≥ `top_k`) |
| `RRF_K`                 | `60`                        | RRF constant; higher dampens high ranks |
| `RRF_VECTOR_WEIGHT`     | `1.0`                       | Weight of the dense-vector channel |
| `RRF_FTS_WEIGHT`        | `0.5`                       | Weight of the full-text channel |

> The embedding model **must** match the one used by the indexer, or query and
> document vectors will be incomparable. Default is `nomic-embed-text` (768-dim),
> matching `document_chunks.embedding vector(768)`.

## Running locally

```bash
cd era_mcp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ERA_VAULT_DB_HOST=192.168.50.50
export ERA_VAULT_DB_PORT=5432
export ERA_VAULT_DB_NAME=era_vault
export ERA_VAULT_DB_USER=era
export ERA_VAULT_DB_PASSWORD=...        # required
export OLLAMA_BASE_URL=http://192.168.50.50:11434
export EMBEDDING_MODEL=nomic-embed-text

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
