import asyncio
import os

import pytest

os.environ.setdefault("ERA_VAULT_DB_PASSWORD", "test")
pytest.importorskip("mcp")

from era_mcp import mcp_server  # noqa: E402


def test_mcp_exposes_exactly_three_tools():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert {t.name for t in tools} == {"ask_vault", "search_vault", "pipeline_status"}
    ask = next(t for t in tools if t.name == "ask_vault")
    assert "mode" in ask.inputSchema["properties"] and "project" in ask.inputSchema["properties"]


def test_ask_vault_passes_mode_and_project_through(monkeypatch):
    seen = {}

    async def fake_run_ask(req):
        seen.update(query=req.query, mode=req.mode, project=req.project)
        return {"answer": "ok"}
    from era_mcp import agent
    monkeypatch.setattr(agent, "run_ask", fake_run_ask)
    out = asyncio.run(mcp_server.ask_vault("q", mode="investigate", project="P"))
    assert out == {"answer": "ok"} and seen == {"query": "q", "mode": "investigate", "project": "P"}
