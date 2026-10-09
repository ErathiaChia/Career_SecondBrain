"""Knowledge tools (brief §11): card-first + hybrid retrieval, by project, by
topic, by date."""
from __future__ import annotations

from typing import Any

from fastapi.concurrency import run_in_threadpool

from era_mcp import cards as cards_mod
from era_mcp import projects, retrieval
from era_mcp.agent_tools import _common
from era_mcp.agent_tools.registry import ToolResult, tool
from era_mcp.agent_tools.sources import from_card, from_chunk, from_document, from_fact


async def _hybrid(query: str, top_k: int, folder: str | None, file_ids: list[int] | None,
                  card_ranks: dict[int, int] | None, kind: str | None = None, embedding: list[float] | None = None):
    emb = embedding if embedding is not None else await retrieval.embed_query(query)
    chunks = await retrieval.multi_search_async([(query, emb)], rerank_query=query, top_k=top_k, folder=folder,
                                                kind=kind, file_ids=file_ids, card_ranks=card_ranks)
    return emb, chunks


@tool("search_knowledge", "knowledge",
      "Card-first hybrid search: document cards (summary/topics/decisions) plus the best passages. The default discovery tool.",
      {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"},
                                        "folder": {"type": "string"}, "project": {"type": "string"}},
       "required": ["query"]}, cost="embed")
async def search_knowledge(query: str, top_k: int = 8, folder: str | None = None, project: str | None = None) -> ToolResult:
    p, file_ids = await _common.scope(project)
    if project and p is None:
        return _common.not_found(project)
    emb = await retrieval.embed_query(query)
    card_hits = await run_in_threadpool(cards_mod.search_cards, query, emb, 10, folder, p["id"] if p else None)
    card_ranks = {c["file_id"]: c["card_rank"] for c in card_hits}
    _, chunks = await _hybrid(query, top_k, folder, file_ids, card_ranks, embedding=emb)
    sources = [from_card(c) for c in card_hits[:5]] + [from_chunk(h) for h in chunks]
    files = {s.file_name for s in sources if s.file_name}
    summary = (f"{len(card_hits)} card(s), {len(chunks)} passage(s) across {len(files)} file(s): "
               + _common.head(sorted(files), 6))
    return ToolResult(ok=True, summary=summary, sources=sources,
                      data={"cards": len(card_hits), "passages": len(chunks), "files": sorted(files)})


@tool("search_documents", "knowledge",
      "Hybrid passage search (vector + full-text + filename), optionally scoped to a folder, kind (document|audio) or project.",
      {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"},
                                        "folder": {"type": "string"}, "kind": {"type": "string"}, "project": {"type": "string"}},
       "required": ["query"]}, cost="embed")
async def search_documents(query: str, top_k: int = 8, folder: str | None = None, kind: str | None = None,
                           project: str | None = None) -> ToolResult:
    p, file_ids = await _common.scope(project)
    if project and p is None:
        return _common.not_found(project)
    _, chunks = await _hybrid(query, top_k, folder, file_ids, None, kind=kind)
    sources = [from_chunk(h) for h in chunks]
    files = sorted({s.file_name for s in sources if s.file_name})
    return ToolResult(ok=True, summary=f"{len(chunks)} passage(s) in {len(files)} file(s): {_common.head(files, 6)}",
                      sources=sources, data={"files": files})


@tool("search_by_project", "knowledge",
      "A project's documents (version families) — optionally filtered by a query within that project.",
      {"type": "object", "properties": {"project": {"type": "string"}, "query": {"type": "string"},
                                        "limit": {"type": "integer"}}, "required": ["project"]}, cost="embed")
async def search_by_project(project: str, query: str | None = None, limit: int = 10) -> ToolResult:
    p, file_ids = await _common.scope(project)
    if p is None:
        return _common.not_found(project)
    docs = await run_in_threadpool(projects.project_documents, p["id"], "flat")
    rows = (docs.get("documents") or [])[:limit]
    cards = await run_in_threadpool(cards_mod.cards_for_files, [d["file_id"] for d in rows])
    sources = []
    for d in rows:
        card = cards.get(d["file_id"])
        if card:
            s = from_card(card, relevance=0.8)
            s.version_label, s.is_latest = d.get("version_label"), d.get("is_latest")
            sources.append(s)
        else:
            sources.append(from_document(d["file_id"], d["file_name"],
                                         f"{d['file_name']} ({d.get('version_label') or 'single version'}, "
                                         f"{'latest' if d.get('is_latest', True) else 'older version'})",
                                         relevance=0.6, file_path=d.get("file_path"), version_label=d.get("version_label"),
                                         is_latest=d.get("is_latest"), date=str(d.get("last_modified_at") or "")[:10]))
    if query and file_ids:
        _, chunks = await _hybrid(query, min(limit, 8), None, file_ids, None)
        sources += [from_chunk(h) for h in chunks]
    names = [d["file_name"] for d in rows]
    return ToolResult(ok=True, summary=f"{p['name']}: {len(docs.get('documents') or [])} document(s); "
                                       f"{_common.head(names, 8)}", sources=sources,
                      data={"project": p["name"], "documents": names})


@tool("search_by_topic", "knowledge",
      "Documents whose card topics/keywords/entities match a topic (e.g. 'pricing', 'data migration', a product name).",
      {"type": "object", "properties": {"topic": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["topic"]})
async def search_by_topic(topic: str, limit: int = 10) -> ToolResult:
    rows = await run_in_threadpool(cards_mod.cards_by_topic, topic, limit)
    if not rows:
        ents = await run_in_threadpool(retrieval.search_entities, topic, 5)
        return ToolResult(ok=True, summary=f"no card matches {topic!r}; entities: " +
                          (_common.head([e.get('canonical_name') for e in ents]) or "none"), data={"entities": ents})
    sources = [from_card(c, relevance=0.8) for c in rows]
    return ToolResult(ok=True, summary=f"{len(rows)} document(s) on {topic!r}: " +
                      _common.head([c.get("title") or c.get("file_name") for c in rows], 6), sources=sources)


@tool("search_by_date", "knowledge",
      "Documents and dated facts in a date range (YYYY-MM-DD), optionally within a project.",
      {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"},
                                        "project": {"type": "string"}, "limit": {"type": "integer"}}})
async def search_by_date(start: str | None = None, end: str | None = None, project: str | None = None,
                         limit: int = 15) -> ToolResult:
    p, _ = await _common.scope(project)
    if project and p is None:
        return _common.not_found(project)
    pid = p["id"] if p else None
    cards = await run_in_threadpool(cards_mod.cards_in_range, start, end, pid, limit)
    facts = await run_in_threadpool(cards_mod.facts_in_range, start, end, pid, None, limit * 2)
    sources = [from_card(c, relevance=0.7) for c in cards] + [from_fact(f, 0.9) for f in facts]
    return ToolResult(ok=True, summary=f"{len(cards)} document(s) and {len(facts)} dated fact(s) between "
                                       f"{start or 'start'} and {end or 'now'}", sources=sources)
