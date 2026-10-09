"""Structural tools: live project / folder inventory (no LLM, no embeddings)."""
from __future__ import annotations

from fastapi.concurrency import run_in_threadpool

from era_mcp import deliverables, projects
from era_mcp import structural as structural_mod
from era_mcp.agent_tools import _common
from era_mcp.agent_tools.registry import ToolResult, tool
from era_mcp.agent_tools.sources import Source, from_project


@tool("list_projects", "structural", "Registered projects (id, key, name, client, status), optionally filtered.",
      {"type": "object", "properties": {"status": {"type": "string"}, "client": {"type": "string"}}})
async def list_projects(status: str | None = None, client: str | None = None) -> ToolResult:
    rows = await run_in_threadpool(projects.list_projects, status, client)
    names = [f"{r.get('name')} ({r.get('client') or '-'}, {r.get('status')})" for r in rows]
    return ToolResult(ok=True, summary=f"{len(rows)} project(s): " + _common.head(names, 12),
                      sources=[Source(kind="project", text="Projects: " + "; ".join(names[:40]), relevance=0.5)] if rows else [],
                      data={"projects": [{"id": r["id"], "key": r.get("project_key"), "name": r.get("name")} for r in rows]})


@tool("resolve_project", "structural", "Resolve a name / key / alias / fragment to one project (with suggestions when ambiguous).",
      {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]})
async def resolve_project(ref: str) -> ToolResult:
    p = await _common.resolve(ref)
    if p is None:
        return _common.not_found(ref)
    return ToolResult(ok=True, summary=f"{ref!r} -> {p['name']} (key {p.get('project_key')}, client {p.get('client')}, status {p.get('status')})",
                      sources=[from_project(p, f"Project {p['name']}: key {p.get('project_key')}, client {p.get('client')}, "
                                              f"type {p.get('project_type')}, status {p.get('status')}", 0.6)], data=p)


@tool("folder_inventory", "structural", "Complete folder / project listing under a path (a census, not a search).",
      {"type": "object", "properties": {"question": {"type": "string"}, "prefix": {"type": "string"}}}, judge_visible=False)
async def folder_inventory(question: str | None = None, prefix: str | None = None) -> ToolResult:
    inv = await run_in_threadpool(structural_mod.project_inventory, question, prefix)
    names = [f.get("name") for f in inv.get("folders", [])]
    return ToolResult(ok=True, summary=f"{inv.get('count', 0)} folder(s) under {inv.get('scope')}: " + _common.head(names, 15), data=inv)


@tool("whats_happening", "structural", "Portfolio view: notable changes by project, amber/red projects, what is due soon.",
      {"type": "object", "properties": {"since_days": {"type": "integer"}}}, judge_visible=False, max_result_tokens=1500)
async def whats_happening(since_days: int = 7) -> ToolResult:
    data = await run_in_threadpool(deliverables.portfolio, since_days)
    md = deliverables.render_whats_happening(data["changes"], data["health"], data["upcoming"], since_days)
    return ToolResult(ok=True, summary=md[:1500], sources=[Source(kind="project", text=md[:4000], relevance=0.7)], data={"markdown": md})
