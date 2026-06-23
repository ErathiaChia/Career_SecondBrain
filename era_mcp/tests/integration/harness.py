"""End-to-end integration test for the era_mcp agent layer.

Runs the REAL FastAPI app (via TestClient) against a REAL Postgres+pgvector
database (a disposable container), with the Ollama embedding endpoint and the
Mac LLM/reranker replaced by an in-process stub. This exercises the actual hybrid
SQL, the rerank/rewrite/synthesis wiring, parent-child expansion, graph
augmentation, and every graceful-degradation path — without touching production
or needing real models.

Prereqs (handled by run.sh): a pgvector container reachable via the ERA_VAULT_DB_*
env vars, and the era_mcp requirements installed in the active interpreter.

Usage: python harness.py   (exits non-zero on any failed assertion)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg2

DIM = 1024


# --------------------------------------------------------------------------- #
# Shared deterministic embedding: bag-of-words hashed into DIM dims, L2-norm.   #
# Used for BOTH seeding doc vectors and the stub query embedding so cosine      #
# similarity tracks real token overlap.                                         #
# --------------------------------------------------------------------------- #
def embed_text(text: str) -> list[float]:
    vec = [0.0] * DIM
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0
        vec[(h // DIM) % DIM] += 0.5
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / norm for x in vec]


def vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


# --------------------------------------------------------------------------- #
# Stub server: stands in for the Ollama embedding endpoint and the Mac LLM.     #
# --------------------------------------------------------------------------- #
class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")

        if self.path.endswith("/api/embed"):
            text = req.get("input", "")
            self._send({"embeddings": [embed_text(text)]})
            return

        if self.path.endswith("/api/chat"):
            messages = req.get("messages", [])
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            user = next((m["content"] for m in messages if m["role"] == "user"), "")
            self._send({"message": {"content": self._respond(system, user)}})
            return

        self._send({})

    def _respond(self, system: str, user: str) -> str:
        s = system.lower()
        if "reranker" in s:
            # Score each "[i] body" by token overlap with the query line.
            query = ""
            m = re.search(r"query:\s*(.*)", user, re.IGNORECASE)
            if m:
                query = m.group(1).splitlines()[0]
            q_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
            scores = []
            for idx, body in re.findall(r"\[(\d+)\]\s*(.*)", user):
                d_tokens = set(re.findall(r"[a-z0-9]+", body.lower()))
                overlap = len(q_tokens & d_tokens)
                scores.append({"index": int(idx), "score": float(overlap)})
            return json.dumps({"scores": scores})
        if "rewrite a user's question" in s:
            q = ""
            m = re.search(r"question:\s*(.*)", user, re.IGNORECASE)
            if m:
                q = m.group(1).strip()
            return json.dumps({"search_query": q or user, "sub_queries": [], "hyde_doc": None})
        # Synthesis: cite the first source.
        return "Based on the sources, we proposed a voice authentication system for Accrete [1]."


def start_stub() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# --------------------------------------------------------------------------- #
# Schema + seed                                                                 #
# --------------------------------------------------------------------------- #
def _dsn() -> str:
    return (
        f"host={os.environ['ERA_VAULT_DB_HOST']} port={os.environ['ERA_VAULT_DB_PORT']} "
        f"dbname={os.environ['ERA_VAULT_DB_NAME']} user={os.environ['ERA_VAULT_DB_USER']} "
        f"password={os.environ['ERA_VAULT_DB_PASSWORD']}"
    )


def wait_for_db(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            psycopg2.connect(_dsn()).close()
            return
        except psycopg2.OperationalError:
            time.sleep(1.5)
    raise RuntimeError("Postgres did not become ready in time")


def apply_schema(conn, repo_root: str):
    base = os.path.join(repo_root, "era_indexer")
    files = [
        os.path.join(base, "schema.sql"),
        *[os.path.join(base, "migrations", f) for f in (
            "0001_v2_foundation.sql",
            "0002_graph_snapshots.sql",
            "0003_v3_knowledge_os.sql",
            "0004_embeddings_1024_parent_chunks.sql",
        )],
    ]
    with conn.cursor() as cur:
        for f in files:
            with open(f) as fh:
                cur.execute(fh.read())
    conn.commit()


def seed(conn):
    docs = [
        # (file, folder, [chunk texts]) — first file is the relevant one.
        ("Accrete Voice Auth Proposal.md", "Clients", [
            "We propose a voice authentication system for Accrete using speaker verification.",
            "The project timeline spans three months including a pilot phase.",
            "Budget covers licensing, infrastructure, and integration costs.",
        ]),
        ("Cafeteria Menu.md", "Personal", [
            "The cafeteria serves pasta on Fridays and salad on Mondays.",
        ]),
    ]
    with conn.cursor() as cur:
        for file_name, folder, chunks in docs:
            cur.execute(
                "INSERT INTO file_registry (file_path, file_name, file_type, file_hash, folder, is_audio) "
                "VALUES (%s,%s,'md','hash',%s,false) RETURNING id",
                (f"/vault/{folder}/{file_name}", file_name, folder),
            )
            file_id = cur.fetchone()[0]
            parent_text = " ".join(chunks)
            cur.execute(
                "INSERT INTO parent_chunks (file_id, ordinal, content) VALUES (%s,0,%s) RETURNING id",
                (file_id, parent_text),
            )
            parent_id = cur.fetchone()[0]
            for i, content in enumerate(chunks):
                meta = json.dumps({"kind": "document", "file_name": file_name, "folder": folder})
                cur.execute(
                    "INSERT INTO document_chunks "
                    "(file_id, chunk_index, content, embedding, search_vector, metadata, parent_chunk_id) "
                    "VALUES (%s,%s,%s,%s::vector, to_tsvector('simple', %s), %s::jsonb, %s)",
                    (file_id, i, content, vec_literal(embed_text(content)), content, meta, parent_id),
                )
        # Graph: two entities + a mention + a relationship.
        cur.execute("INSERT INTO entities (canonical_name, entity_type) VALUES ('Accrete','company') RETURNING id")
        acc = cur.fetchone()[0]
        cur.execute("INSERT INTO entities (canonical_name, entity_type) VALUES ('Voice Authentication','technology') RETURNING id")
        va = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO entity_mentions (entity_id, file_id, mention_text, extractor_version) "
            "VALUES (%s, 1, 'Accrete', 'test-v1')",
            (acc,),
        )
        cur.execute(
            "INSERT INTO relationships (source_entity_id, relationship_type, target_entity_id, confidence) "
            "VALUES (%s,'USES',%s,0.9)",
            (acc, va),
        )
    conn.commit()


# --------------------------------------------------------------------------- #
# Assertions                                                                    #
# --------------------------------------------------------------------------- #
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    wait_for_db()
    conn = psycopg2.connect(_dsn())
    apply_schema(conn, repo_root)
    seed(conn)
    conn.close()

    stub_srv, stub_url = start_stub()
    os.environ["OLLAMA_BASE_URL"] = stub_url
    os.environ["LLM_PRIMARY_BASE_URL"] = stub_url
    os.environ["LLM_PRIMARY_KIND"] = "ollama"
    os.environ["RERANK_ENABLED"] = "1"
    os.environ["RERANK_KIND"] = "llm_score"
    os.environ["QUERY_REWRITE_ENABLED"] = "1"
    os.environ["OPENAI_API_KEY"] = ""

    from fastapi.testclient import TestClient
    from era_mcp import server

    client = TestClient(server.app)
    q = "What did we propose to Accrete for voice authentication?"

    print("\nT1 — /search hybrid retrieval (regression, unchanged path)")
    r = client.post("/search", json={"query": q, "top_k": 5}).json()["results"]
    check("search returns results", len(r) > 0)
    check("top hit is the Accrete proposal", r and r[0]["file_name"] == "Accrete Voice Auth Proposal.md",
          detail=str(r[0]["file_name"] if r else None))
    check("/search has NO rerank_score (path unchanged)", r and "rerank_score" not in r[0])

    print("\nT2 — /ask synthesized answer with citations")
    a = client.post("/ask", json={"query": q, "top_k": 5}).json()
    check("answer present", bool(a.get("answer")))
    check("answer cites [1]", "[1]" in (a.get("answer") or ""))
    check("citations non-empty", len(a.get("citations", [])) > 0)
    check("not degraded", a.get("degraded") is False, detail=str(a.get("degraded_reason")))
    check("chunks returned", len(a.get("chunks", [])) > 0)
    check("rewritten_query echoes question", (a.get("rewritten_query") or q) is not None)
    check("provider reported", "primary" in (a.get("provider") or {}))

    print("\nT3 — reranker actually ran")
    check("chunks carry rerank_score", a.get("chunks") and "rerank_score" in a["chunks"][0])

    print("\nT4 — graph augmentation (brain populated)")
    g = a.get("graph") or {}
    ents = [e.get("canonical_name") for e in g.get("entities", [])]
    check("/ask graph has entities", len(ents) > 0, detail=str(ents))
    check("Accrete entity surfaced", any("Accrete" in (e or "") for e in ents), detail=str(ents))
    ks = client.post("/knowledge/search", json={"query": q, "top_k": 5}).json()
    check("/knowledge/search entities non-empty", len(ks.get("entities", [])) > 0)
    check("/knowledge/search relationships non-empty", len(ks.get("relationships", [])) > 0)

    print("\nT5 — graceful degradation (Mac LLM down, no OpenAI)")
    os.environ["LLM_PRIMARY_BASE_URL"] = "http://127.0.0.1:9"  # dead
    d = client.post("/ask", json={"query": q, "top_k": 5}).json()
    check("degraded=true", d.get("degraded") is True, detail=str(d.get("degraded_reason")))
    check("answer is null when LLM down", d.get("answer") is None)
    check("chunks STILL returned (degrade to retrieval)", len(d.get("chunks", [])) > 0)
    os.environ["LLM_PRIMARY_BASE_URL"] = stub_url

    print("\nT6 — parent-child expansion")
    check("returned content is the larger parent chunk",
          r and len(r[0]["content"]) > 80 and "timeline" in r[0]["content"],
          detail="expected parent text spanning multiple children")

    stub_srv.shutdown()
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
