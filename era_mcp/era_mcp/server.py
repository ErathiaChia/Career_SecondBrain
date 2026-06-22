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

from era_mcp import config, retrieval

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
