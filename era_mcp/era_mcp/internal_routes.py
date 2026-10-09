"""Internal (debug) routes: everything that used to be an Open WebUI tool but
is now reachable only by the bounded agent through its tool registry. They
stay mounted for curl/debugging, hidden from the OpenAPI schema so no client
sees them as tools. Disable entirely with INTERNAL_ROUTES_ENABLED=0."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from era_mcp import agent, cards, llm, rerank, retrieval, structural
from era_mcp.agent_tools import registry
from era_mcp.schemas import KnowledgeSearchRequest

router = APIRouter(include_in_schema=False)


@router.post("/knowledge/search", operation_id="search_vault_v3")
async def search_vault_v3(req: KnowledgeSearchRequest) -> dict:
    """Search across summaries, entities, relationships, communities, and chunks."""
    embedding = await retrieval.embed_query(req.query)
    return retrieval.knowledge_search(query=req.query, query_embedding=embedding, top_k=req.top_k, folder=req.folder)


@router.get("/entities/search", operation_id="search_entities")
async def search_entities(query: str = Query(...), limit: int = Query(default=10, ge=1, le=100)) -> dict:
    return {"results": retrieval.search_entities(query=query, limit=limit)}


@router.get("/relationships/search", operation_id="search_relationships")
async def search_relationships(query: str = Query(...), limit: int = Query(default=10, ge=1, le=100)) -> dict:
    return {"results": retrieval.search_relationships(query=query, limit=limit)}


@router.get("/communities/search", operation_id="search_communities")
async def search_communities(query: str = Query(...), limit: int = Query(default=10, ge=1, le=100)) -> dict:
    return {"results": retrieval.search_communities(query=query, limit=limit)}


@router.get("/facts/search", operation_id="search_facts")
async def search_facts(query: str = Query(...), kind: Optional[str] = Query(default=None),
                       limit: int = Query(default=10, ge=1, le=100)) -> dict:
    return {"results": retrieval.search_facts(query=query, kind=kind, limit=limit)}


@router.get("/documents/summary", operation_id="get_document_summary")
async def get_document_summary(file_id: Optional[int] = Query(default=None),
                               file_name: Optional[str] = Query(default=None)) -> dict:
    summary = retrieval.get_document_summary(file_id=file_id, file_name=file_name)
    if summary is None:
        raise HTTPException(status_code=404, detail="Document summary not found")
    return summary


@router.get("/documents/{file_id}/card", operation_id="get_document_card")
async def get_document_card(file_id: int) -> dict:
    card = await run_in_threadpool(cards.get_card, file_id)
    if card is None:
        raise HTTPException(status_code=404, detail="No card for this file")
    return card


@router.get("/sections/{section_id}/summary", operation_id="get_section_summary")
async def get_section_summary(section_id: int) -> dict:
    summary = retrieval.get_section_summary(section_id=section_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Section summary not found")
    return summary


@router.get("/entities/{entity_id}/neighbors", operation_id="get_entity_neighbors")
async def get_entity_neighbors(entity_id: int, limit: int = Query(default=25, ge=1, le=100)) -> dict:
    result = retrieval.get_entity_neighbors(entity_id=entity_id, limit=limit)
    if result["entity"] is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return result


@router.get("/entities/{entity_id}/facts", operation_id="get_entity_facts")
async def get_entity_facts(entity_id: int, limit: int = Query(default=25, ge=1, le=100)) -> dict:
    return {"results": retrieval.facts_for_entity(entity_id=entity_id, limit=limit)}


@router.get("/graph/subgraph", operation_id="get_graph_subgraph")
async def get_graph_subgraph(entity_id: Optional[int] = Query(default=None), scope: str = Query(default="all"),
                             limit: int = Query(default=100, ge=1, le=500)) -> dict:
    return retrieval.get_graph_subgraph(entity_id=entity_id, scope=scope, limit=limit)


@router.get("/status", operation_id="indexing_status")
async def indexing_status(folder: Optional[str] = Query(default=None)) -> dict:
    """Processing-stage counts plus provider / reranker / prompt diagnostics."""
    summary = retrieval.status_summary(folder=folder)
    return {
        "folder": folder,
        "summary": summary,
        "provider": llm.provider_status(),
        "rerank": rerank.status(),
        # False means the container is running on the inline fallback prompts
        # (prompts/ not copied into the image) — see Dockerfile.
        "prompts_loaded_from_files": agent.prompts_loaded_from_files(),
        "tools": len(registry.REGISTRY),
    }


@router.get("/folders", operation_id="list_folders")
async def list_folders() -> dict:
    return {"folders": retrieval.list_folders()}


@router.get("/structure/folders", operation_id="list_folders_tree")
async def list_folders_tree(prefix: Optional[str] = Query(default=None), question: Optional[str] = Query(default=None)) -> dict:
    return await run_in_threadpool(structural.project_inventory, question, prefix)


@router.get("/structure/overview", operation_id="folder_overview")
async def folder_overview() -> dict:
    return {"overview": await run_in_threadpool(structural.folder_overview)}


@router.get("/graph/snapshot", operation_id="graph_snapshot")
async def graph_snapshot(scope: str = Query(default="all")) -> dict:
    snapshot = retrieval.graph_snapshot(scope=scope)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"No current graph snapshot for scope: {scope}")
    return snapshot


@router.get("/graph/status", operation_id="graph_status")
async def graph_status(scope: str = Query(default="all")) -> dict:
    return retrieval.graph_status(scope=scope)


@router.get("/digest/latest", operation_id="get_latest_digest")
async def get_latest_digest() -> dict:
    d = await run_in_threadpool(cards.latest_weekly_digest)
    if d is None:
        raise HTTPException(status_code=404, detail="No digest yet")
    d["created_at"] = str(d.get("created_at"))
    return d


@router.get("/internal/tools", operation_id="list_internal_tools")
async def list_internal_tools() -> dict:
    """The agent's tool registry (what the Judge can call)."""
    return {"count": len(registry.REGISTRY), "catalog": registry.catalog(judge_only=False),
            "tools": [{"name": s.name, "group": s.group, "cost": s.cost, "judge_visible": s.judge_visible,
                       "signature": s.signature()} for s in registry.REGISTRY.values()]}
