# Era Graph Web

Sigma.js viewer for the Era Vault knowledge graph.

This app renders the latest graph snapshot generated from the indexed KB. It is
designed to be served by the `era_mcp` FastAPI service and embedded as an
iframe in another knowledge-base website.

See the [repo masterplan](../README.md) for how all four Era Vault components
fit together.

## Ecosystem

| Component | Role |
|-----------|------|
| [`era_indexer`](../era_indexer) | Write — discover, convert, chunk, embed, graph extract |
| [`era_mcp`](../era_mcp) | Read — hybrid search, `/ask` agent, OpenAPI tools |
| [`era_auditor`](../era_auditor) | Steward — vault hygiene, semantic dupes, Librarian training |
| **era_graph_web** (this) | Visualize — Sigma.js graph viewer at `/graph` |

## How it fits

The graph data is generated outside this frontend:

1. `era_indexer` extracts entities and relationships from indexed chunks.
2. Postgres stores canonical graph rows in `entities`, `entity_mentions`, `relationships`, and `relationship_evidence`.
3. `graph_snapshots` stores a Sigma-compatible JSON payload.
4. `era_mcp` exposes the snapshot at `GET /graph/snapshot`.
5. This app loads that endpoint and renders it with Sigma.js.

## Development

From this folder:

```bash
npm install
npm run dev
```

The Vite dev server proxies graph API calls to:

```text
http://localhost:8808
```

So run the MCP/read service separately when developing against real data.

## Build

```bash
npm run build
```

The production output is written to:

```text
dist/
```

The `era_mcp` Dockerfile builds this frontend and copies `dist/` into the FastAPI container.

## API expectations

The viewer expects:

```text
GET /graph/snapshot?scope=all
```

The response should include a `payload` object with:

```json
{
  "nodes": [],
  "edges": [],
  "metadata": {}
}
```

Each node needs `key`, `label`, `type`, `x`, `y`, `size`, and `color`. Each edge needs `key`, `source`, `target`, `label`, `type`, and `size`.

## Iframe embed

Once deployed through `era_mcp`, embed it with:

```html
<iframe
  src="https://your-domain.example/graph/"
  title="Era Knowledge Graph"
  width="100%"
  height="720"
  style="border: 0;"
></iframe>
```

If embedding on a different domain, configure the serving layer to allow that site to frame `/graph/`.

## Regenerating data

Generate or refresh the graph snapshot from the indexer:

```bash
cd era_indexer
python -m career_history.cli graph-refresh
python -m career_history.cli graph-status
```

From the repo root (alternative):

```bash
python -m career_history.cli --config era_indexer/config.yaml graph-refresh
python -m career_history.cli --config era_indexer/config.yaml graph-status
```

The frontend does not extract graph data itself; it only displays the latest persisted snapshot.
