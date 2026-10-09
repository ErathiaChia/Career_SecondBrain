import asyncio

import pytest

from era_mcp import agent_tools  # noqa: F401 — registers the tools
from era_mcp.agent_tools import registry
from era_mcp.agent_tools.registry import ToolResult, ToolSpec, validate_args
from era_mcp.agent_tools.sources import Source
from era_mcp.budget import estimate_tokens

REQUIRED = {"search_knowledge", "search_documents", "search_by_project", "search_by_topic", "search_by_date",
            "get_document", "get_document_metadata", "read_file", "read_section",
            "find_evidence", "compare_documents", "find_conflicts", "trace_decision", "find_latest_version",
            "get_project_history", "get_achievement", "get_kpi", "get_role_history", "build_timeline",
            "find_career_evidence"}


def test_brief_section_11_capabilities_present():
    assert REQUIRED <= set(registry.REGISTRY)


def test_catalog_is_compact_and_hides_internal_tools():
    cat = registry.catalog()
    assert estimate_tokens(cat) < 1400
    assert "get_project_brief" not in cat and "whats_happening" not in cat
    assert "get_project_brief" in registry.catalog(judge_only=False)
    assert "## career" in cat and "search_knowledge(" in cat


def test_validate_args_drops_unknown_coerces_and_requires():
    spec = registry.get("get_project_facts")
    clean, errors = validate_args(spec, {"project": "X", "limit": "5", "open_only": "true", "kinds": "risk, decision", "bogus": 1})
    assert clean == {"project": "X", "limit": 5, "open_only": True, "kinds": ["risk", "decision"]} and errors == []
    clean, errors = validate_args(spec, {"limit": "abc"})
    assert "project: required" in errors and any(e.startswith("limit") for e in errors)


def test_call_never_raises(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("db down")
    registry.REGISTRY["_boom"] = ToolSpec("_boom", "knowledge", "x", {"type": "object", "properties": {}}, boom)
    try:
        r = asyncio.run(registry.call("_boom", {}))
        assert r.ok is False and "RuntimeError" in r.summary and r.error == "RuntimeError"
        r2 = asyncio.run(registry.call("nope", {}))
        assert r2.ok is False and r2.error == "unknown_tool"
        r3 = asyncio.run(registry.call("get_project_facts", {}))
        assert r3.ok is False and r3.error == "invalid_args"
    finally:
        del registry.REGISTRY["_boom"]


def test_call_times_out(monkeypatch):
    async def slow(**kw):
        await asyncio.sleep(1)
        return ToolResult(ok=True, summary="late")
    registry.REGISTRY["_slow"] = ToolSpec("_slow", "knowledge", "x", {"type": "object", "properties": {}}, slow)
    try:
        r = asyncio.run(registry.call("_slow", {}, timeout=0.05))
        assert r.ok is False and r.error == "timeout"
    finally:
        del registry.REGISTRY["_slow"]


def test_summary_is_capped(monkeypatch):
    async def chatty(**kw):
        return ToolResult(ok=True, summary="x" * 20000, sources=[Source(kind="passage", text="t")])
    registry.REGISTRY["_chatty"] = ToolSpec("_chatty", "knowledge", "x", {"type": "object", "properties": {}}, chatty,
                                            max_result_tokens=100)
    try:
        r = asyncio.run(registry.call("_chatty", {}))
        assert estimate_tokens(r.summary) <= 110 and r.summary.endswith("…")
    finally:
        del registry.REGISTRY["_chatty"]


def test_phase5_career_tools_registered():
    assert {"build_star_examples", "compare_projects", "capability_evidence", "career_timeline"} <= set(registry.REGISTRY)
    assert "build_star_examples(" in registry.catalog() and "career_timeline(" not in registry.catalog()
