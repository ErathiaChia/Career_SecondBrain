"""Document tools (brief §11): card/metadata lookups and bounded reads."""
from __future__ import annotations

from fastapi.concurrency import run_in_threadpool

from era_mcp import cards as cards_mod
from era_mcp import docdiff, projects, retrieval
from era_mcp.agent_tools import _common
from era_mcp.agent_tools.registry import ToolResult, tool
from era_mcp.agent_tools.sources import from_card, from_document
from era_mcp.budget import estimate_tokens


async def _card_for(file_id: int | None, file_name: str | None):
    if file_id is not None:
        return await run_in_threadpool(cards_mod.get_card, file_id)
    if file_name:
        return await run_in_threadpool(cards_mod.card_by_name, file_name)
    return None


@tool("get_document", "document",
      "A document's intelligence card (summary, topics, decisions, outcomes, dates) and its version chain. Use before reading the file.",
      {"type": "object", "properties": {"file_id": {"type": "integer"}, "file_name": {"type": "string"}}})
async def get_document(file_id: int | None = None, file_name: str | None = None) -> ToolResult:
    card = await _card_for(file_id, file_name)
    fid = card["file_id"] if card else file_id
    sources, data = [], {}
    if card:
        sources.append(from_card(card, relevance=1.0))
        data["card"] = {k: card.get(k) for k in ("file_id", "title", "doc_type", "doc_date", "topics", "projects")}
    else:
        summary = await run_in_threadpool(retrieval.get_document_summary, fid, file_name)
        if summary:
            fid = summary["file_id"]
            sources.append(from_document(fid, summary.get("file_name"), summary.get("summary") or "",
                                         relevance=0.8, folder=summary.get("folder")))
    if fid is None:
        return ToolResult(ok=False, summary=f"no document matches {file_name or file_id!r}", error="not_found")
    versions = await run_in_threadpool(projects.document_versions, fid)
    chain = versions.get("chain") or []
    latest = next((v for v in chain if v.get("is_latest")), None)
    data["versions"] = [{"file_id": v["file_id"], "file_name": v["file_name"], "label": v.get("version_label"),
                         "is_latest": v.get("is_latest")} for v in chain]
    summary = (f"{(card or {}).get('title') or file_name or fid}: {len(chain) or 1} version(s)"
               + (f", latest = {latest['file_name']}" if latest else ""))
    return ToolResult(ok=True, summary=summary, sources=sources, data=data)


@tool("get_document_metadata", "document",
      "File metadata: path, type, dates, chunk and fact counts, card headline.",
      {"type": "object", "properties": {"file_id": {"type": "integer"}}, "required": ["file_id"]}, judge_visible=False)
async def get_document_metadata(file_id: int) -> ToolResult:
    meta = await run_in_threadpool(cards_mod.file_meta, file_id)
    if meta is None:
        return ToolResult(ok=False, summary=f"file {file_id} not found", error="not_found")
    card = await run_in_threadpool(cards_mod.get_card, file_id)
    text = (f"{meta['file_name']} ({meta['file_type']}) in {meta['folder']}; modified {str(meta.get('last_modified_at'))[:10]}; "
            f"{meta['chunks']} chunk(s), {meta['facts']} fact(s)" + (f"; {card['doc_type']}: {card['summary'][:200]}" if card else ""))
    return ToolResult(ok=True, summary=text, sources=[from_document(file_id, meta["file_name"], text, relevance=0.5,
                                                                    file_path=meta.get("file_path"), folder=meta.get("folder"))],
                      data=meta)


@tool("read_file", "document",
      "Read a document's converted text (bounded by max_tokens). Counts toward the 10-document budget; prefer read_section.",
      {"type": "object", "properties": {"file_id": {"type": "integer"}, "max_tokens": {"type": "integer"}}, "required": ["file_id"]})
async def read_file(file_id: int, max_tokens: int = 3000) -> ToolResult:
    meta = await run_in_threadpool(cards_mod.file_meta, file_id)
    if meta is None:
        return ToolResult(ok=False, summary=f"file {file_id} not found", error="not_found")
    text = await run_in_threadpool(docdiff._current_text, file_id, meta.get("file_hash"))
    if not text:
        return ToolResult(ok=False, summary=f"{meta['file_name']}: no text available", error="empty")
    cut = text[: int(max_tokens * 3.6)]
    src = from_document(file_id, meta["file_name"], cut, relevance=0.9, file_path=meta.get("file_path"),
                        folder=meta.get("folder"), date=str(meta.get("last_modified_at") or "")[:10])
    return ToolResult(ok=True, summary=f"{meta['file_name']}: {estimate_tokens(cut)} token(s) read"
                                       f"{' (truncated)' if len(cut) < len(text) else ''}; starts: {cut[:160]!r}",
                      sources=[src], data={"truncated": len(cut) < len(text), "chars": len(text)})


@tool("read_section", "document",
      "Read one section of a document by section_id or a heading fragment (bounded). The precise way to pull evidence.",
      {"type": "object", "properties": {"file_id": {"type": "integer"}, "section_id": {"type": "integer"},
                                        "heading": {"type": "string"}, "max_tokens": {"type": "integer"}},
       "required": ["file_id"]})
async def read_section(file_id: int, section_id: int | None = None, heading: str | None = None,
                       max_tokens: int = 1500) -> ToolResult:
    sec = await run_in_threadpool(cards_mod.section_text, file_id, section_id, heading, int(max_tokens * 3.6))
    if sec is None:
        return ToolResult(ok=False, summary=f"no section matches in file {file_id} ({heading or section_id})", error="not_found")
    src = from_document(file_id, sec["file_name"], sec["text"], kind="section", relevance=0.9,
                        file_path=sec.get("file_path"), folder=sec.get("folder"), section=sec.get("section"),
                        page=sec.get("page"), date=sec.get("date"))
    return ToolResult(ok=True, summary=f"{sec['file_name']} § {sec.get('section') or section_id}: "
                                       f"{sec['chunks']} chunk(s); {sec['text'][:160]!r}", sources=[src])
