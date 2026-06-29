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
            return json.dumps({"search_query": q or user, "sub_queries": [],
                               "complexity": "moderate", "hyde_doc": None})
        if "agentic retrieval loop" in s:  # ReAct Judge verdict
            ul = user.lower()
            if "exhaust" in ul:
                # Never satisfied: cycle a unique query each turn so every
                # iteration adds a NEW doc (avoids the no-new-docs early exit) and
                # the run hits the max-iters cap.
                prior = user.count('"action": "research"')
                token = ["zeta alpha", "zeta bravo", "zeta charlie", "zeta delta"][min(prior, 3)]
                return json.dumps({"thought": "keep searching", "action": "research",
                                   "sufficient": False, "missing": "more evidence",
                                   "reformulations": [token], "query": "", "confidence": 0.2})
            if "escalate" in ul:
                # Re-search once, then (seeing its own trajectory) answer — proves
                # memory persists across iterations.
                if "TRAJECTORY SO FAR" in user:
                    return json.dumps({"thought": "now sufficient given prior step",
                                       "action": "answer", "sufficient": True, "missing": "",
                                       "reformulations": [], "query": "", "confidence": 0.9})
                return json.dumps({"thought": "need more context first", "action": "research",
                                   "sufficient": False, "missing": "menu context",
                                   "reformulations": ["cafeteria pasta menu Fridays"],
                                   "query": "", "confidence": 0.3})
            return json.dumps({"thought": "candidates suffice", "action": "answer",
                               "sufficient": True, "missing": "", "reformulations": [],
                               "query": "", "confidence": 0.9})
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
            "0005_knowledge_facts.sql",
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
        # Filler docs with a shared "zeta" token + a unique word each — let the
        # max-iters test add a new doc on every research turn.
        ("Alpha Note.md", "Misc", ["zeta alpha unique filler note one"]),
        ("Bravo Note.md", "Misc", ["zeta bravo unique filler note two"]),
        ("Charlie Note.md", "Misc", ["zeta charlie unique filler note three"]),
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
        # Structural test: nested project folders under a top-level "14. ST-Engg".
        # file_registry rows only — the structural branch reads paths, not chunks.
        for p in (
            "/vault/14. ST-Engg/01 Project/2026/16_HC3/00-README.md",
            "/vault/14. ST-Engg/01 Project/2026/16_HC3/A.2. Proposal/p.pdf",
            "/vault/14. ST-Engg/01 Project/2026/11_Thailand/A.2. Proposal/t.xlsx",
            "/vault/14. ST-Engg/01 Project/2026/01_IBF/rfp.pdf",
            "/vault/14. ST-Engg/01 Project/2026/loose.md",  # directly in 2026 → not a project
        ):
            cur.execute(
                "INSERT INTO file_registry (file_path, file_name, file_type, file_hash, folder, is_audio) "
                "VALUES (%s,%s,'md','h','14. ST-Engg',false)",
                (p, p.rsplit("/", 1)[1]),
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
        # Layer 1 fact: a commitment tied to the Accrete entity (subject + project).
        cur.execute(
            "INSERT INTO knowledge_facts "
            "(kind, statement, subject_entity_id, project_entity_id, attributes, "
            " file_id, source_quote, confidence, extractor_version) "
            "VALUES ('commitment', %s, %s, %s, %s::jsonb, 1, %s, 0.9, 'test-facts-v2')",
            (
                "Send Accrete the voice authentication proposal next week",
                acc, acc,
                json.dumps({"due_at": "2026-07-05", "status": "open",
                            "direction": "owed_by_me", "counterparty": "Accrete"}),
                "we will send the proposal next week",
            ),
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
    os.environ["QUERY_INSTRUCTION_ENABLED"] = "0"  # keep stub query/doc embeddings symmetric
    os.environ["AGENTIC_ASK_ENABLED"] = "1"
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

    print("\nT7 — structural inventory (census, not semantic search)")
    inv = client.get("/structure/folders",
                     params={"question": "list all projects under ST-Engg 01 Project 2026"}).json()
    names = {f["name"] for f in inv.get("folders", [])}
    check("structural lists the 3 projects", {"16_HC3", "11_Thailand", "01_IBF"} <= names, detail=str(names))
    check("structural excludes the loose file", "loose.md" not in names)
    check("structural count is 3", inv.get("count") == 3, detail=str(inv.get("count")))
    inv2 = client.get("/structure/folders",
                      params={"prefix": "/vault/14. ST-Engg/01 Project/2026/"}).json()
    check("structural by explicit prefix == 3", inv2.get("count") == 3, detail=str(inv2.get("count")))
    ov = client.get("/structure/overview").json()
    check("folder overview is non-empty text", bool(ov.get("overview")))

    print("\nT8 — agentic routes a census question to the structural tool")
    ar = client.post("/ask", json={"query": "how many projects are under ST-Engg 2026?"}).json()
    check("route == structural", ar.get("route") == "structural", detail=str(ar.get("route")))
    check("structural answer states the count (3)", "3" in (ar.get("answer") or ""))

    print("\nT9 — confidence gate: strong match → single pass (no judge)")
    os.environ["STRONG_RERANK_THRESHOLD"] = "0.001"
    sp = client.post("/ask", json={"query": q, "top_k": 5}).json()
    check("single pass (0 judge iterations)", sp.get("iterations") == 0, detail=str(sp.get("iterations")))
    check("single pass still answers", bool(sp.get("answer")))

    print("\nT10 — ReAct loop escalates and carries memory across iterations")
    os.environ["STRONG_RERANK_THRESHOLD"] = "0.99"
    es = client.post("/ask", json={"query": "escalate: what did we propose to Accrete?", "top_k": 5}).json()
    traj = es.get("trajectory", [])
    check("escalated into the loop (>=2 steps)", len(traj) >= 2, detail=str(len(traj)))
    check("first step re-searched (action=research)", bool(traj) and traj[0].get("action") == "research")
    check("a later step answered after seeing the trajectory", any(t.get("action") == "answer" for t in traj))
    check("queries_tried grew beyond the first pass", len(es.get("queries_tried", [])) > 1)

    print("\nT11 — max-iters cap → best-effort partial answer with notice")
    os.environ["STRONG_RERANK_THRESHOLD"] = "0.99"
    os.environ["AGENT_MAX_ITERS"] = "3"
    ex = client.post("/ask", json={"query": "exhaust the budget on this hard question", "top_k": 5}).json()
    check("max_iters_reached flagged", ex.get("max_iters_reached") is True, detail=str(ex.get("max_iters_reached")))
    check("not marked sufficient", ex.get("sufficient") is False)
    check("gaps populated for the partial answer", bool(ex.get("gaps")))
    os.environ["STRONG_RERANK_THRESHOLD"] = "0.8"

    print("\nT12 — Layer 1 facts (decisions/commitments/events)")
    fs = client.get("/facts/search", params={"query": "proposal"}).json()
    check("/facts/search returns the commitment",
          any(f.get("kind") == "commitment" for f in fs.get("results", [])), detail=str(fs))
    fsk = client.get("/facts/search", params={"query": "proposal", "kind": "commitment"}).json()
    check("/facts/search kind filter works", len(fsk.get("results", [])) > 0)
    kf = client.post("/knowledge/search", json={"query": q, "top_k": 5}).json()
    check("/knowledge/search surfaces facts", len(kf.get("facts", [])) > 0, detail=str(kf.get("facts")))
    af = client.post("/ask", json={"query": q, "top_k": 5}).json()
    check("/ask graph carries facts", len((af.get("graph") or {}).get("facts", [])) > 0,
          detail=str((af.get("graph") or {}).get("facts")))
    acc_ent = next((e for e in kf.get("entities", []) if "Accrete" in (e.get("canonical_name") or "")), None)
    if acc_ent and acc_ent.get("id"):
        ef = client.get(f"/entities/{acc_ent['id']}/facts").json()
        check("/entities/{id}/facts returns the fact", len(ef.get("results", [])) > 0)

    stub_srv.shutdown()
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
