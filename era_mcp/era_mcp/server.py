"""Era Vault / Career Intelligence read server.

Public surface (what every client sees, as OpenAPI tools for Open WebUI and
as MCP tools at /mcp for Claude Code / Codex):

    POST /ask              ask_vault        bounded agent (fast | investigate)
    POST /search           search_vault     raw hybrid passage search
    GET  /pipeline/status  pipeline_status  how current the knowledge is

Everything else (project tools, facts, entities, graph, structure, digests) is
internal: reachable by the agent through its tool registry and, for debugging,
as hidden HTTP routes (INTERNAL_ROUTES_ENABLED). Nothing here writes to the
vault database except proposed_actions (via the hidden project routes).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from era_mcp import agent, auth, config, retrieval
from era_mcp.pipeline_routes import router as pipeline_router
from era_mcp.schemas import AskRequest, SearchRequest

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    auth.warn_if_open()
    if config.mcp_enabled():
        from era_mcp import mcp_server
        async with mcp_server.mcp.session_manager.run():
            yield
    else:
        yield


app = FastAPI(
    title="Era Vault",
    description="Career Second Brain: cited answers, raw search and pipeline status over your personal knowledge base.",
    version="0.3.0",
    lifespan=_lifespan,
)
app.middleware("http")(auth.bearer_middleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# --- public ----------------------------------------------------------------------

@app.post("/search", operation_id="search_vault")
async def search_vault(req: SearchRequest) -> dict:
    """Raw hybrid passage search (vector + full-text + filename) over your indexed
    documents and transcripts, with surrounding context. No LLM answer — use
    ask_vault for answers."""
    embedding = await retrieval.embed_query(req.query)
    results = retrieval.search(query=req.query, query_embedding=embedding, top_k=req.top_k, folder=req.folder,
                               kind=req.kind, context_window=req.context_window)
    return {"results": results}


@app.post("/ask", operation_id="ask_vault")
async def ask_vault(req: AskRequest) -> dict:
    """Answer a question from the knowledge base with cited evidence.

    The agent routes mechanically first (project census -> structural listing;
    "what changed this week" -> weekly report), runs a card-first hybrid
    retrieval, then either answers in ONE pass (fast) or runs a bounded
    investigation (<= 3 Judge rounds x <= 3 tool calls, <= 10 documents, <= 20k
    context tokens) over project facts, document cards, version diffs,
    conflicts, decisions, achievements and career evidence.

    The answer carries FACT / INFERENCE / UNKNOWN labels with [n] / [F<id>]
    citations; `citations` resolve every label to a file (+ section/page/date/
    version); `sufficient`, `gaps` and `budget.stop_reason` say how complete it
    is; `trajectory` / `tools_used` show what was checked. 503 when the local
    LLM is unreachable (there is no cloud fallback)."""
    return await agent.run_ask(req)


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"ok": True, "version": app.version}


app.include_router(pipeline_router)

# --- internal / hidden ------------------------------------------------------------

if config.internal_routes_enabled():
    from era_mcp.internal_routes import router as internal_router
    from era_mcp.project_routes import router as project_router

    app.include_router(internal_router, include_in_schema=False)
    app.include_router(project_router, include_in_schema=False)


def _mount_graph_viewer() -> None:
    candidates = [Path(__file__).resolve().parents[2] / "era_graph_web" / "dist", Path("/app/era_graph_web/dist")]
    for dist in candidates:
        if dist.exists():
            app.mount("/graph", StaticFiles(directory=dist, html=True), name="graph-viewer")
            return


_mount_graph_viewer()

# MCP (streamable HTTP) — mounted last so FastAPI routes win; served at MCP_PATH.
if config.mcp_enabled():
    from era_mcp import mcp_server

    app.mount("/", mcp_server.http_app(), name="mcp")


def main():
    uvicorn.run(app, host="0.0.0.0", port=8808)


if __name__ == "__main__":
    main()
