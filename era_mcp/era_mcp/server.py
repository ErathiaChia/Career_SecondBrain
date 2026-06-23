"""Era Vault tool server — OpenAPI-compatible for Open WebUI.

Exposes semantic search over your knowledge base as REST endpoints
with auto-generated OpenAPI spec that Open WebUI discovers at /openapi.json.

Run directly:
    python -m era_mcp.server
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from era_mcp import config, llm, query_understanding, retrieval

app = FastAPI(
    title="Era Vault",
    description="Semantic search over your personal knowledge base.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Resolved once at import so the value appears as a concrete default in the
# generated OpenAPI schema (Open WebUI reads that default; default_factory would
# leave it absent and the model would invent its own, usually 5).
_DEFAULT_TOP_K = config.default_top_k()


class SearchRequest(BaseModel):
    query: str = Field(description="Natural-language search query.")
    top_k: int = Field(
        default=_DEFAULT_TOP_K,
        description="Number of results to return.",
    )
    folder: Optional[str] = Field(default=None, description="Folder name to restrict search to.")
    kind: Optional[str] = Field(default=None, description='Filter by "document" or "audio".')
    context_window: int = Field(
        default=3,
        description="Number of surrounding chunks (before and after) to include for broader context. 0 = matched chunk only.",
    )


class KnowledgeSearchRequest(SearchRequest):
    """Knowledge-first search request."""


@app.post("/search", operation_id="search_vault")
async def search_vault(req: SearchRequest) -> dict:
    """Search the Era Vault knowledge base using semantic similarity.

    Embeds the query and finds the most relevant chunks from your
    indexed documents and audio transcripts. Surrounding chunks are
    automatically included for broader context.
    """
    embedding = await retrieval.embed_query(req.query)
    results = retrieval.search(
        query=req.query,
        query_embedding=embedding,
        top_k=req.top_k,
        folder=req.folder,
        kind=req.kind,
        context_window=req.context_window,
    )
    return {"results": results}


@app.post("/knowledge/search", operation_id="search_vault_v3")
async def search_vault_v3(req: KnowledgeSearchRequest) -> dict:
    """Search across summaries, entities, relationships, communities, and chunks."""
    embedding = await retrieval.embed_query(req.query)
    return retrieval.knowledge_search(
        query=req.query,
        query_embedding=embedding,
        top_k=req.top_k,
        folder=req.folder,
    )


class AskRequest(BaseModel):
    query: str = Field(description="Natural-language question to answer.")
    top_k: int = Field(default=_DEFAULT_TOP_K, description="Chunks to retrieve and cite.")
    folder: Optional[str] = Field(default=None, description="Restrict to a folder.")
    use_graph: bool = Field(default=True, description="Augment with graph entities/relationships.")
    rewrite: bool = Field(default=True, description="LLM query rewriting before retrieval.")
    rerank: bool = Field(default=True, description="Cross-encoder rerank of candidates.")
    synthesize: bool = Field(
        default=True,
        description="Return an LLM-synthesized answer. False = reranked chunks only.",
    )


_SYNTH_SYSTEM = (
    "You are a precise assistant answering from a personal knowledge base. Use "
    "ONLY the numbered sources to answer. Cite sources inline as [n] immediately "
    "after the claim they support. If the sources do not contain the answer, say "
    "so plainly rather than guessing. Be concise and concrete — prefer names, "
    "dates, and specifics over generalities."
)


async def _synthesize(question: str, chunks: list[dict], graph: Optional[dict]) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        content = (c.get("content") or "").strip()[:1500]
        blocks.append(
            f"[{i}] {c.get('file_name', '?')} (folder: {c.get('folder', '?')}):\n{content}"
        )
    context = "\n\n".join(blocks)
    graph_note = ""
    if graph and graph.get("entities"):
        ents = ", ".join(
            e.get("canonical_name", "")
            for e in graph["entities"][:10]
            if e.get("canonical_name")
        )
        if ents:
            graph_note = f"\n\nRelated entities in the knowledge graph: {ents}"
    user = f"Question: {question}\n\nSources:\n{context}{graph_note}"
    return await llm.chat(
        [{"role": "system", "content": _SYNTH_SYSTEM},
         {"role": "user", "content": user}]
    )


@app.post("/ask", operation_id="ask_vault")
async def ask_vault(req: AskRequest) -> dict:
    """Answer a question over the vault, end to end.

    Pipeline: query rewrite -> hybrid retrieve -> rerank -> optional graph
    augmentation -> synthesized answer with [n] citations. Always returns the
    supporting chunks; if the Mac LLM (and OpenAI fallback) are unavailable it
    degrades to returning reranked chunks with ``answer=null`` and
    ``degraded=true`` instead of failing.
    """
    from fastapi.concurrency import run_in_threadpool

    degraded = False
    degraded_reason: Optional[str] = None

    # 1) Query understanding (degrade-safe: identity rewrite on any failure).
    understanding = (
        await query_understanding.rewrite_query(req.query)
        if req.rewrite else query_understanding.identity(req.query)
    )
    search_query = understanding["search_query"]
    embed_text = understanding.get("hyde_doc") or search_query

    # 2) Embed + hybrid retrieve + rerank.
    embedding = await retrieval.embed_query(embed_text)
    chunks = await retrieval.search_async(
        query=search_query,
        query_embedding=embedding,
        top_k=req.top_k,
        folder=req.folder,
        rerank_enabled=req.rerank,
    )

    # 3) Optional graph augmentation (best-effort; empty if not yet populated).
    graph = None
    if req.use_graph:
        graph = await run_in_threadpool(retrieval.graph_only, search_query, req.top_k)

    # 4) Citations mirror the supporting chunks 1:1.
    citations = [
        {
            "n": i,
            "file_name": c.get("file_name"),
            "file_path": c.get("file_path"),
            "folder": c.get("folder"),
            "matched_chunk_index": c.get("matched_chunk_index"),
            "similarity": c.get("similarity"),
            "rerank_score": c.get("rerank_score"),
        }
        for i, c in enumerate(chunks, start=1)
    ]

    # 5) Synthesis — degrade to chunks-only if the LLM is unavailable.
    answer = None
    if req.synthesize and chunks:
        try:
            answer = await _synthesize(req.query, chunks, graph)
        except llm.LLMUnavailable as e:
            degraded = True
            degraded_reason = f"llm_unavailable: {e}"
    elif req.synthesize and not chunks:
        degraded = True
        degraded_reason = "no_results"

    return {
        "query": req.query,
        "rewritten_query": search_query if search_query != req.query else None,
        "sub_queries": understanding.get("sub_queries", []),
        "answer": answer,
        "citations": citations,
        "chunks": chunks,
        "graph": graph,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "provider": llm.provider_status(),
    }


@app.get("/entities/search", operation_id="search_entities")
async def search_entities(
    query: str = Query(description="Entity name, alias, or fragment."),
    limit: int = Query(default=10, ge=1, le=100),
) -> dict:
    """Search canonical graph entities."""
    return {"results": retrieval.search_entities(query=query, limit=limit)}


@app.get("/relationships/search", operation_id="search_relationships")
async def search_relationships(
    query: str = Query(description="Entity, relationship type, or evidence text."),
    limit: int = Query(default=10, ge=1, le=100),
) -> dict:
    """Search typed relationships and evidence."""
    return {"results": retrieval.search_relationships(query=query, limit=limit)}


@app.get("/communities/search", operation_id="search_communities")
async def search_communities(
    query: str = Query(description="Community name, summary, or member entity."),
    limit: int = Query(default=10, ge=1, le=100),
) -> dict:
    """Search graph communities."""
    return {"results": retrieval.search_communities(query=query, limit=limit)}


@app.get("/documents/summary", operation_id="get_document_summary")
async def get_document_summary(
    file_id: Optional[int] = Query(default=None),
    file_name: Optional[str] = Query(default=None),
) -> dict:
    """Return the latest document summary."""
    summary = retrieval.get_document_summary(file_id=file_id, file_name=file_name)
    if summary is None:
        raise HTTPException(status_code=404, detail="Document summary not found")
    return summary


@app.get("/sections/{section_id}/summary", operation_id="get_section_summary")
async def get_section_summary(section_id: int) -> dict:
    """Return the latest section summary."""
    summary = retrieval.get_section_summary(section_id=section_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Section summary not found")
    return summary


@app.get("/entities/{entity_id}/neighbors", operation_id="get_entity_neighbors")
async def get_entity_neighbors(
    entity_id: int,
    limit: int = Query(default=25, ge=1, le=100),
) -> dict:
    """Return graph neighbors for one entity."""
    result = retrieval.get_entity_neighbors(entity_id=entity_id, limit=limit)
    if result["entity"] is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return result


@app.get("/graph/subgraph", operation_id="get_graph_subgraph")
async def get_graph_subgraph(
    entity_id: Optional[int] = Query(default=None),
    scope: str = Query(default="all"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """Return graph export data, optionally scoped to one entity neighborhood."""
    return retrieval.get_graph_subgraph(
        entity_id=entity_id,
        scope=scope,
        limit=limit,
    )


@app.get("/status", operation_id="indexing_status")
async def indexing_status(
    folder: Optional[str] = Query(default=None, description="Folder to scope status check."),
) -> dict:
    """Check the current indexing status of the Era Vault pipeline.

    Returns a count of files in each processing stage.
    """
    summary = retrieval.status_summary(folder=folder)
    return {"folder": folder, "summary": summary}


@app.get("/folders", operation_id="list_folders")
async def list_folders() -> dict:
    """List all top-level folders in the Era Vault knowledge base."""
    folders = retrieval.list_folders()
    return {"folders": folders}


@app.get("/graph/snapshot", operation_id="graph_snapshot")
async def graph_snapshot(
    scope: str = Query(default="all", description='Snapshot scope, e.g. "all" or "folder:Research".'),
) -> dict:
    """Return the latest Sigma.js-compatible graph snapshot."""
    snapshot = retrieval.graph_snapshot(scope=scope)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"No current graph snapshot for scope: {scope}",
        )
    return snapshot


@app.get("/graph/status", operation_id="graph_status")
async def graph_status(
    scope: str = Query(default="all", description='Snapshot scope, e.g. "all" or "folder:Research".'),
) -> dict:
    """Return graph extraction and snapshot status."""
    return retrieval.graph_status(scope=scope)


def _mount_graph_viewer() -> None:
    candidates = [
        Path(__file__).resolve().parents[2] / "era_graph_web" / "dist",
        Path("/app/era_graph_web/dist"),
    ]
    for dist in candidates:
        if dist.exists():
            app.mount(
                "/graph",
                StaticFiles(directory=dist, html=True),
                name="graph-viewer",
            )
            return


_mount_graph_viewer()


def main():
    uvicorn.run(app, host="0.0.0.0", port=8808)


if __name__ == "__main__":
    main()
