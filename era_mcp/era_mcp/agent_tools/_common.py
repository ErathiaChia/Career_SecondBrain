"""Shared helpers for the tool modules."""
from __future__ import annotations

from typing import Any

from fastapi.concurrency import run_in_threadpool

from era_mcp import cards as cards_mod
from era_mcp import projects
from era_mcp.agent_tools.registry import ToolResult


async def resolve(project: str | int | None) -> dict[str, Any] | None:
    if project is None or project == "":
        return None
    return await run_in_threadpool(projects.resolve_project, project)


async def scope(project: str | int | None) -> tuple[dict[str, Any] | None, list[int] | None]:
    """(project row, file ids) for a project reference; (None, None) when unscoped."""
    p = await resolve(project)
    if p is None:
        return None, None
    ids = await run_in_threadpool(cards_mod.project_file_ids, p["id"])
    return p, (ids or None)


def not_found(project: str | int) -> ToolResult:
    try:
        sugg = projects.project_suggestions(str(project))
    except Exception:  # noqa: BLE001
        sugg = []
    names = ", ".join(str(s.get("name") or s.get("project_key")) for s in sugg[:5]) or "none"
    return ToolResult(ok=False, summary=f"No project matches {project!r}. Did you mean: {names}", error="not_found",
                      data={"did_you_mean": sugg})


def head(items: list[Any], n: int = 5) -> str:
    return "; ".join(str(x)[:120] for x in items[:n])
