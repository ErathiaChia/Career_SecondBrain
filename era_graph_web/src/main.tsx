import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import Graph from "graphology";
import Sigma from "sigma";
import "./styles.css";

type SnapshotNode = {
  key: string;
  label: string;
  type: string;
  x: number;
  y: number;
  size: number;
  color: string;
  metadata?: Record<string, unknown>;
};

type SnapshotEdge = {
  key: string;
  source: string;
  target: string;
  label: string;
  type: string;
  size: number;
  metadata?: Record<string, unknown>;
};

type SnapshotPayload = {
  scope: string;
  version: string;
  nodes: SnapshotNode[];
  edges: SnapshotEdge[];
  metadata: Record<string, unknown>;
};

type SnapshotResponse = {
  id: number;
  scope: string;
  source_hash: string;
  extraction_version: string;
  payload: SnapshotPayload;
  node_count: number;
  edge_count: number;
  created_at: string;
};

const apiBase = import.meta.env.VITE_GRAPH_API_BASE ?? "";

function App() {
  const [scope, setScope] = useState("all");
  const [snapshot, setSnapshot] = useState<SnapshotResponse | null>(null);
  const [selectedNode, setSelectedNode] = useState<SnapshotNode | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetch(`${apiBase}/graph/snapshot?scope=${encodeURIComponent(scope)}`, {
      signal: controller.signal
    })
      .then((response) => {
        if (!response.ok) throw new Error(`Graph snapshot not found (${response.status})`);
        return response.json() as Promise<SnapshotResponse>;
      })
      .then((data) => {
        setSnapshot(data);
        setSelectedNode(null);
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        setError(err.message);
        setSnapshot(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [scope]);

  const filteredNodes = useMemo(() => {
    const nodes = snapshot?.payload.nodes ?? [];
    const normalized = query.trim().toLowerCase();
    if (!normalized) return nodes.slice(0, 80);
    return nodes
      .filter((node) => node.label.toLowerCase().includes(normalized))
      .slice(0, 80);
  }, [snapshot, query]);

  return (
    <main className="app-shell">
      <aside className="panel">
        <div>
          <p className="eyebrow">Era Vault</p>
          <h1>Knowledge Graph</h1>
          <p className="muted">
            Entity and relationship view generated from the indexed KB.
          </p>
        </div>

        <label className="field">
          <span>Scope</span>
          <input value={scope} onChange={(event) => setScope(event.target.value)} />
        </label>

        <label className="field">
          <span>Search nodes</span>
          <input
            placeholder="person, project, technology..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>

        {loading && <p className="muted">Loading graph...</p>}
        {error && <p className="error">{error}</p>}
        {snapshot && (
          <Stats
            createdAt={snapshot.created_at}
            nodes={snapshot.node_count}
            edges={snapshot.edge_count}
            version={snapshot.extraction_version}
          />
        )}

        <div className="node-list">
          {filteredNodes.map((node) => (
            <button
              key={node.key}
              className={selectedNode?.key === node.key ? "node-item active" : "node-item"}
              type="button"
              onClick={() => setSelectedNode(node)}
            >
              <span className="dot" style={{ background: node.color }} />
              <span>
                <strong>{node.label}</strong>
                <small>{node.type}</small>
              </span>
            </button>
          ))}
        </div>
      </aside>

      <section className="graph-stage">
        {snapshot ? (
          <SigmaGraph
            payload={snapshot.payload}
            selectedNode={selectedNode}
            onSelectNode={setSelectedNode}
          />
        ) : (
          <div className="empty-state">
            <h2>No graph loaded</h2>
            <p>Run <code>python -m career_history.cli graph-refresh</code> from <code>era_indexer/</code> to generate the first snapshot.</p>
          </div>
        )}
      </section>

      {selectedNode && <Details node={selectedNode} />}
    </main>
  );
}

function SigmaGraph({
  payload,
  selectedNode,
  onSelectNode
}: {
  payload: SnapshotPayload;
  selectedNode: SnapshotNode | null;
  onSelectNode: (node: SnapshotNode) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<Sigma | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const nodeMap = useMemo(
    () => new Map(payload.nodes.map((node) => [node.key, node])),
    [payload.nodes]
  );

  useEffect(() => {
    if (!containerRef.current) return;
    setGraphError(null);
    try {
      const graph = new Graph();
      for (const node of payload.nodes) {
        graph.addNode(node.key, {
          label: node.label,
          entityType: node.type,
          x: node.x,
          y: node.y,
          size: node.size,
          color: node.color
        });
      }
      for (const edge of payload.edges) {
        if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
        graph.addDirectedEdgeWithKey(edge.key, edge.source, edge.target, {
          label: edge.label,
          size: edge.size,
          color: edge.type === "mentioned_in" ? "#cbd5e1" : "#64748b"
        });
      }

      const renderer = new Sigma(graph, containerRef.current, {
        renderEdgeLabels: false,
        labelDensity: 0.08,
        labelRenderedSizeThreshold: 8,
        defaultEdgeType: "line"
      });
      renderer.on("clickNode", ({ node }) => {
        const match = nodeMap.get(node);
        if (match) onSelectNode(match);
      });
      rendererRef.current = renderer;
      return () => {
        renderer.kill();
        rendererRef.current = null;
      };
    } catch (err) {
      setGraphError(err instanceof Error ? err.message : String(err));
      return undefined;
    }
  }, [payload, nodeMap, onSelectNode]);

  return (
    <div className="sigma-container">
      <div ref={containerRef} className="sigma-canvas" />
      {graphError && (
        <div className="graph-error">
          <h2>Graph render failed</h2>
          <p>{graphError}</p>
        </div>
      )}
    </div>
  );
}

function Stats({
  createdAt,
  nodes,
  edges,
  version
}: {
  createdAt: string;
  nodes: number;
  edges: number;
  version: string;
}) {
  return (
    <dl className="stats">
      <div>
        <dt>Nodes</dt>
        <dd>{nodes}</dd>
      </div>
      <div>
        <dt>Edges</dt>
        <dd>{edges}</dd>
      </div>
      <div>
        <dt>Version</dt>
        <dd>{version}</dd>
      </div>
      <div>
        <dt>Snapshot</dt>
        <dd>{new Date(createdAt).toLocaleString()}</dd>
      </div>
    </dl>
  );
}

function Details({ node }: { node: SnapshotNode }) {
  return (
    <aside className="details">
      <p className="eyebrow">{node.type}</p>
      <h2>{node.label}</h2>
      <dl>
        {Object.entries(node.metadata ?? {}).map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{formatValue(value)}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}

function formatValue(value: unknown) {
  if (Array.isArray(value)) return value.join(", ") || "none";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value === null || value === undefined || value === "") return "none";
  return String(value);
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
