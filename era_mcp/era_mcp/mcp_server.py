"""The MCP surface: the SAME three tools the OpenAPI surface exposes, served
as an MCP server so Claude Code, Codex and any other MCP client can use the
intelligence layer. Mounted at /mcp (streamable HTTP) inside the FastAPI app;
``python -m era_mcp.mcp_server --stdio`` runs it over stdio.

Claude Code:   claude mcp add --transport http career-intel http://<nas>:8808/mcp \\
                 --header "Authorization: Bearer $ERA_MCP_TOKEN"
"""
from __future__ import annotations

import sys
from typing import Any, Literal, Optional

from mcp.server.fastmcp import FastMCP

from era_mcp import config, retrieval
from era_mcp.schemas import AskRequest

mcp = FastMCP(
    "career-intel",
    instructions=("Career Second Brain over a personal work knowledge base. Call ask_vault for any question "
                  "(it answers with FACT/INFERENCE/UNKNOWN labels and [n]/[F<id>] citations and decides itself "
                  "whether to run a bounded investigation); search_vault for raw passages; pipeline_status to "
                  "learn how current the knowledge is."),
    stateless_http=True,
    json_response=True,
    streamable_http_path=config.mcp_path(),   # mounted at "/" by server.py -> served at /mcp
)


@mcp.tool(name="ask_vault")
async def ask_vault(query: str, mode: Literal["auto", "fast", "investigate"] = "auto",
                    project: Optional[str] = None, folder: Optional[str] = None) -> dict[str, Any]:
    """Answer a question from the knowledge base with cited evidence. mode=auto
    lets the agent choose between a fast single pass and a bounded investigation
    (max 3 tool rounds); investigate forces the loop (compare versions, trace
    decisions, career evidence); fast forces one pass. project scopes to a
    project name/key. "What changed this week" returns the weekly report."""
    from era_mcp import agent
    req = AskRequest(query=query, mode=mode, project=project, folder=folder)
    return await agent.run_ask(req)


@mcp.tool(name="search_vault")
async def search_vault(query: str, top_k: int = 10, folder: Optional[str] = None,
                       kind: Optional[str] = None) -> dict[str, Any]:
    """Raw hybrid passage search (vector + full-text + filename) with surrounding
    context; no LLM answer. kind = document | audio."""
    embedding = await retrieval.embed_query(query)
    results = retrieval.search(query=query, query_embedding=embedding, top_k=top_k, folder=folder, kind=kind,
                               context_window=3)
    return {"results": results}


@mcp.tool(name="pipeline_status")
async def pipeline_status() -> dict[str, Any]:
    """How current the knowledge base is: last pipeline run (status, counts,
    finish time), extraction backlog, stale flag."""
    from era_mcp import pipeline_routes
    return await pipeline_routes.pipeline_status()


def http_app():
    """ASGI app to mount under FastAPI (see server.py)."""
    return mcp.streamable_http_app()


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if "--stdio" in argv or not argv:
        mcp.run(transport="stdio")
    else:
        raise SystemExit("usage: python -m era_mcp.mcp_server --stdio   (HTTP is served by era_mcp.server at /mcp)")


if __name__ == "__main__":
    main()
