"""Investigation tools (brief §11): evidence for a claim, version diffs,
conflicts, decision tracing, latest version."""
from __future__ import annotations

import re
from typing import Any

from fastapi.concurrency import run_in_threadpool

from era_mcp import cards as cards_mod
from era_mcp import docdiff, projects, retrieval
from era_mcp.agent_tools import _common
from era_mcp.agent_tools.registry import ToolResult, tool
from era_mcp.agent_tools.sources import from_chunk, from_document, from_fact


@tool("find_evidence", "investigation",
      "Evidence for or against a specific claim: matching typed facts plus the best passages (optionally within a project).",
      {"type": "object", "properties": {"claim": {"type": "string"}, "project": {"type": "string"}, "top_k": {"type": "integer"}},
       "required": ["claim"]}, cost="embed")
async def find_evidence(claim: str, project: str | None = None, top_k: int = 5) -> ToolResult:
    p, file_ids = await _common.scope(project)
    if project and p is None:
        return _common.not_found(project)
    facts = await run_in_threadpool(retrieval.search_facts, claim, None, top_k)
    emb = await retrieval.embed_query(claim)
    chunks = await retrieval.search_async(claim, emb, top_k=top_k, file_ids=file_ids)
    sources = [from_fact(f, 0.95) for f in facts] + [from_chunk(h) for h in chunks]
    for s in sources:
        s.extra["evidence_for"] = claim
    return ToolResult(ok=True, summary=f"{len(facts)} fact(s) and {len(chunks)} passage(s) bearing on: {claim[:100]}",
                      sources=sources)


@tool("compare_documents", "investigation",
      "What changed between two versions of a document (file_id_b defaults to the previous version in the chain): section-level and line diff.",
      {"type": "object", "properties": {"file_id_a": {"type": "integer"}, "file_id_b": {"type": "integer"},
                                        "max_lines": {"type": "integer"}}, "required": ["file_id_a"]})
async def compare_documents(file_id_a: int, file_id_b: int | None = None, max_lines: int = 120) -> ToolResult:
    pair = await run_in_threadpool(docdiff.resolve_pair, file_id_a, file_id_b)
    if pair.get("error"):
        return ToolResult(ok=False, summary=pair["error"], error="not_found")
    if pair.get("previous") is None or pair.get("old_text") is None:
        return ToolResult(ok=True, summary=f"{pair['current']['file_name']}: no previous version to compare against",
                          data={"basis": pair.get("basis")})
    diff = await run_in_threadpool(docdiff.diff_texts, pair["old_text"], pair["new_text"], max_lines)
    cur, prev = pair["current"], pair["previous"]
    head = (f"{prev.get('file_name')} -> {cur.get('file_name')} ({pair.get('basis')}): "
            f"+{diff.get('lines_added')}/-{diff.get('lines_removed')} lines; "
            f"sections added {diff.get('sections_added') or []}, removed {diff.get('sections_removed') or []}, "
            f"changed {diff.get('sections_changed') or diff.get('changed') or []}")
    body = "\n".join((diff.get("unified") or diff.get("diff") or [])[:max_lines]) if isinstance(diff.get("unified") or diff.get("diff"), list) \
        else str(diff.get("unified") or diff.get("diff") or "")[: max_lines * 80]
    src = from_document(cur.get("id") or file_id_a, cur.get("file_name"), head + "\n" + body, kind="diff", relevance=0.95,
                        file_path=cur.get("file_path"), previous_file_id=prev.get("id"), previous_file_name=prev.get("file_name"))
    return ToolResult(ok=True, summary=head, sources=[src], data={k: v for k, v in diff.items() if k not in ("unified", "diff")})


@tool("find_conflicts", "investigation",
      "Contradicting fact pairs and stale facts for a project, with both sides and which is likely newer.",
      {"type": "object", "properties": {"project": {"type": "string"}}, "required": ["project"]})
async def find_conflicts(project: str) -> ToolResult:
    p = await _common.resolve(project)
    if p is None:
        return _common.not_found(project)
    conflicts = await run_in_threadpool(projects.project_conflicts, p["id"], False, 20)
    stale = await run_in_threadpool(projects.project_stale, p["id"], 30)
    sources = []
    lines = []
    for c in conflicts:
        a, b = c.get("fact_a") or {}, c.get("fact_b") or {}
        for side, f in (("a", a), ("b", b)):
            if f:
                ff = {**f, "conflict_ids": [c.get("id")]}
                sources.append(from_fact(ff, 0.9))
        lines.append(f"#{c.get('id')} {c.get('conflict_type')}: '{(a.get('statement') or '')[:80]}' vs "
                     f"'{(b.get('statement') or '')[:80]}' (likely latest fact {c.get('likely_latest_fact_id')})")
    for s in stale[:10]:
        f = dict(s); f["stale_reasons"] = [s.get("reason")]
        sources.append(from_fact(f, 0.7))
    summary = (f"{p['name']}: {len(conflicts)} conflict(s), {len(stale)} stale fact(s). " + "; ".join(lines[:4])) \
        if (conflicts or stale) else f"{p['name']}: no conflicts or stale facts recorded"
    return ToolResult(ok=True, summary=summary, sources=sources, data={"conflicts": len(conflicts), "stale": len(stale)})


def _topic_tokens(topic: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", topic.lower()) if len(t) > 2}


@tool("trace_decision", "investigation",
      "The chain of decisions about a topic (optionally within a project), oldest to newest, with what each superseded.",
      {"type": "object", "properties": {"topic": {"type": "string"}, "project": {"type": "string"}}, "required": ["topic"]})
async def trace_decision(topic: str, project: str | None = None) -> ToolResult:
    p = await _common.resolve(project)
    if project and p is None:
        return _common.not_found(project)
    toks = _topic_tokens(topic)
    found: dict[int, dict[str, Any]] = {}
    if p:
        for f in await run_in_threadpool(projects.project_facts, p["id"], ["decision"], False, 200):
            hay = f"{f.get('statement')} {f.get('topic')}".lower()
            if any(t in hay for t in toks):
                found[f["id"]] = f
    for f in await run_in_threadpool(retrieval.search_facts, topic, "decision", 15):
        found.setdefault(f["id"], f)
    rows = sorted(found.values(), key=lambda f: (str(f.get("occurred_at") or f.get("last_verified_at") or ""), f["id"]))
    sources = [from_fact(f, 0.9) for f in rows]
    chain = " -> ".join(f"[F{f['id']}] {str(f.get('occurred_at') or '')[:10]} {f.get('statement')[:70]}"
                        + (f" (supersedes F{f['supersedes_fact_id']})" if f.get("supersedes_fact_id") else "")
                        for f in rows[:6])
    return ToolResult(ok=True, summary=f"{len(rows)} decision(s) on {topic!r}: {chain or 'none found'}", sources=sources)


@tool("find_latest_version", "investigation",
      "Which file is the latest version — of a given file, a file name, or every versioned family in a project.",
      {"type": "object", "properties": {"file_id": {"type": "integer"}, "file_name": {"type": "string"},
                                        "project": {"type": "string"}}})
async def find_latest_version(file_id: int | None = None, file_name: str | None = None,
                              project: str | None = None) -> ToolResult:
    if file_id is None and file_name:
        card = await run_in_threadpool(cards_mod.card_by_name, file_name)
        if card:
            file_id = card["file_id"]
    if file_id is not None:
        v = await run_in_threadpool(projects.document_versions, file_id)
        chain = v.get("chain") or []
        if not chain:
            return ToolResult(ok=True, summary=f"file {file_id} has no version family (single version)", data=v)
        latest = next((c for c in chain if c.get("is_latest")), chain[-1])
        sources = [from_document(c["file_id"], c["file_name"], f"{c['file_name']} {c.get('version_label') or ''}"
                                 f"{' (latest)' if c.get('is_latest') else ' (older version)'}", relevance=1.0 if c.get("is_latest") else 0.6,
                                 file_path=c.get("file_path"), version_label=c.get("version_label"), is_latest=c.get("is_latest"),
                                 date=str(c.get("last_modified_at") or "")[:10]) for c in chain]
        return ToolResult(ok=True, summary=f"latest = {latest['file_name']} (file_id {latest['file_id']}) of {len(chain)} version(s): "
                                           + " < ".join(c["file_name"] for c in chain), sources=sources, data=v)
    p = await _common.resolve(project)
    if p is None:
        return _common.not_found(project or file_name or "?")
    docs = await run_in_threadpool(projects.project_documents, p["id"], "version")
    fams = [f for f in (docs.get("families") or []) if f.get("version_count", 1) > 1]
    sources = []
    for fam in fams[:8]:
        lv = fam["versions"][-1]
        sources.append(from_document(lv["file_id"], lv["file_name"], f"{fam['family_key']}: latest {lv['file_name']} of {fam['version_count']}",
                                     relevance=0.9, file_path=lv.get("file_path"), version_label=lv.get("version_label"), is_latest=True))
    return ToolResult(ok=True, summary=f"{p['name']}: {len(fams)} versioned famil(ies); " +
                      _common.head([f"{f['family_key']} -> {f['latest']}" for f in fams], 6), sources=sources)
