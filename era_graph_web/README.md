# Era Graph Web

Sigma.js viewer for the Era Vault knowledge graph.

This app renders the latest graph snapshot generated from the indexed KB. It is designed to be served by the `era_mcp` FastAPI service and embedded as an iframe in another knowledge-base website.

## How It Fits

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

## API Expectations

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

## Iframe Embed

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

## Regenerating Data

Generate or refresh the graph snapshot from the indexer:

```bash
python -m career_history.cli --config era_indexer/config.yaml graph-refresh
```

Check graph status:

```bash
python -m career_history.cli --config era_indexer/config.yaml graph-status
```

The frontend does not extract graph data itself; it only displays the latest persisted snapshot.
