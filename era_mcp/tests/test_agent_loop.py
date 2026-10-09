"""Orchestration tests for the bounded agent: every LLM / DB / tool boundary
is monkeypatched so these assert the CONTROL LOGIC (routing, gate, caps,
early stops, 503) and nothing else."""
import asyncio
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("ERA_VAULT_DB_PASSWORD", "test")

from era_mcp import agent, llm  # noqa: E402
from era_mcp.agent_tools.registry import ToolResult  # noqa: E402
from era_mcp.agent_tools.sources import Source  # noqa: E402
from era_mcp.schemas import AskRequest  # noqa: E402


def _chunk(fid, score):
    return {"content": f"passage from file {fid} " * 5, "file_id": fid, "file_name": f"f{fid}.md",
            "file_path": f"/v/f{fid}.md", "folder": "P", "rerank_score": score, "similarity": 0.4,
            "matched_chunk_index": 0}


@pytest.fixture
def wired(monkeypatch):
    """Returns a dict the test mutates to script behaviour; records calls."""
    state = {"chunks": [_chunk(1, 0.9)], "verdicts": [], "tool_sources": "unique", "calls": [], "judge_calls": 0,
             "synth": "FACT: answer [1]", "digest": None}
    monkeypatch.setenv("RERANK_KIND", "infinity")
    monkeypatch.setenv("STRONG_RERANK_THRESHOLD", "0.8")
    monkeypatch.setenv("AGENT_MAX_ITERS", "3")
    monkeypatch.setenv("AGENT_TIME_BUDGET", "600")
    monkeypatch.setenv("LLM_NUM_CTX", "32768")
    monkeypatch.setattr(agent.projects, "resolve_project", lambda ref: None)
    monkeypatch.setattr(agent.projects, "project_state", lambda pid: None)

    async def rewrite(q):
        return {"search_query": q, "sub_queries": [], "complexity": "moderate", "hyde_doc": None}
    monkeypatch.setattr(agent.query_understanding, "rewrite_query", rewrite)

    async def embed(t):
        return [0.0]
    monkeypatch.setattr(agent.retrieval, "embed_query", embed)
    monkeypatch.setattr(agent.cards_mod, "project_file_ids", lambda pid: [])
    monkeypatch.setattr(agent.cards_mod, "search_cards", lambda *a, **k: [])
    monkeypatch.setattr(agent.cards_mod, "latest_weekly_digest", lambda: state["digest"])
    monkeypatch.setattr(agent.structural, "project_inventory", lambda q, p: {"scope": "/v", "count": 2, "folders": [{"name": "a", "file_count": 1}, {"name": "b", "file_count": 2}]})

    async def multi(**kw):
        return list(state["chunks"])
    monkeypatch.setattr(agent.retrieval, "multi_search_async", multi)

    async def decide(question, phase, phase_no, max_phases, catalog, trajectory, digest, budget, project=None,
                     seed_tools=None, timeout=None):
        state["judge_calls"] += 1
        v = state["verdicts"][min(state["judge_calls"] - 1, len(state["verdicts"]) - 1)]
        if state.get("vary_args"):  # distinct args per round so calls are not duplicates
            v = {**v, "tool_calls": [{**c, "args": {k: f"{val}-r{state['judge_calls']}" for k, val in c["args"].items()}}
                                     for c in v.get("tool_calls", [])]}
        return agent.judge.normalize_verdict(v)
    monkeypatch.setattr(agent.judge, "decide", decide)

    async def call(name, args, timeout=None):
        state["calls"].append((name, dict(args)))
        n = len(state["calls"])
        if state["tool_sources"] == "none":
            return ToolResult(ok=True, summary="nothing", sources=[])
        return ToolResult(ok=True, summary=f"found {n}", sources=[Source(kind="fact", text=f"fact {n}", file_id=100 + n,
                                                                             file_name=f"g{n}.md", fact_id=n, relevance=0.9)])
    monkeypatch.setattr(agent.registry, "call", call)

    async def chat(messages, **kw):
        if isinstance(state["synth"], Exception):
            raise state["synth"]
        return state["synth"]
    monkeypatch.setattr(agent.llm, "chat", chat)
    return state


def _ask(**kw):
    kw.setdefault("use_graph", False)
    return asyncio.run(agent.run_ask(AskRequest(**kw)))


def test_fast_path_is_one_pass(wired):
    out = _ask(query="when is go-live?")
    assert out["route"] == "fast" and out["iterations"] == 0 and out["tools_used"] == []
    assert out["llm_calls"] == 2            # rewrite + synthesis
    assert wired["judge_calls"] == 0
    assert out["citations"] and out["citations"][0]["file_name"] == "f1.md"
    assert out["budget"]["stop_reason"] is None and out["sufficient"] is True


def test_investigate_caps_tool_calls_and_records_invalid_ones(wired):
    wired["chunks"] = [_chunk(1, 0.2)]
    wired["verdicts"] = [
        {"action": "tools", "tool_calls": [
            {"tool": "get_project_facts", "args": {"project": "P"}},
            {"tool": "no_such_tool", "args": {}},
            {"tool": "get_project_facts", "args": {"project": "P"}},   # duplicate
            {"tool": "find_evidence", "args": {"claim": "x"}},
            {"tool": "find_conflicts", "args": {"project": "P"}},      # 5th: beyond the per-round cap
        ], "sufficient": False, "confidence": 0.4, "missing": "evidence"},
        {"action": "answer", "sufficient": True, "confidence": 0.9},
    ]
    out = _ask(query="what did we decide about pricing?")
    assert out["route"] == "investigate"
    names = [c[0] for c in wired["calls"]]
    # unknown + duplicate are dropped WITHOUT eating the per-round cap of 3 valid calls
    assert names == ["get_project_facts", "find_evidence", "find_conflicts"]
    step = out["trajectory"][1]
    errors = [(c["tool"], c.get("error")) for c in step["tool_calls"] if c.get("error")]
    assert ("no_such_tool", "unknown_tool") in errors and ("get_project_facts", "duplicate_call") in errors
    assert out["iterations"] == 2 and out["tool_calls"] == 3 and out["sufficient"] is True
    assert out["budget"]["stop_reason"] == "judge_answer" and out["llm_calls"] == 4   # rewrite + 2 judge + synth


def test_max_iterations_is_a_hard_cap(wired):
    wired["chunks"] = [_chunk(1, 0.2)]
    wired["vary_args"] = True
    wired["verdicts"] = [{"action": "tools", "tool_calls": [{"tool": "find_evidence", "args": {"claim": f"c{i}"}}
                                                            for i in range(3)], "sufficient": False, "missing": "more"}] * 10
    out = _ask(query="exhaust it")
    assert out["iterations"] == 3 and out["tool_calls"] == 9 and wired["judge_calls"] == 3
    assert out["max_iters_reached"] is True and out["budget"]["stop_reason"] == "max_iterations"
    assert out["sufficient"] is False and out["gaps"]
    assert len(out["trajectory"]) == 4  # first pass + 3 rounds


def test_no_new_evidence_stops_early(wired):
    wired["chunks"] = [_chunk(1, 0.2)]
    wired["tool_sources"] = "none"
    wired["verdicts"] = [{"action": "tools", "tool_calls": [{"tool": "find_evidence", "args": {"claim": "c"}}]}] * 5
    out = _ask(query="anything?")
    assert out["iterations"] == 1 and out["budget"]["stop_reason"] == "no_new_evidence"


def test_document_cap_enforced_across_tools(wired, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_DOCUMENTS", "3")
    wired["chunks"] = [_chunk(1, 0.2), _chunk(2, 0.1)]
    wired["vary_args"] = True
    wired["verdicts"] = [{"action": "tools", "tool_calls": [{"tool": "find_evidence", "args": {"claim": f"c{i}"}} for i in range(3)]}] * 3
    out = _ask(query="lots of docs")
    assert out["budget"]["documents_used"] <= 3
    assert out["budget"]["rejected_documents"] > 0


def test_mode_overrides(wired):
    wired["chunks"] = [_chunk(1, 0.1)]
    wired["verdicts"] = [{"action": "answer", "sufficient": True}]
    assert _ask(query="x", mode="fast")["route"] == "fast" and wired["judge_calls"] == 0
    wired["chunks"] = [_chunk(1, 0.99)]
    out = _ask(query="x", mode="investigate")
    assert out["route"] == "investigate" and wired["judge_calls"] == 1


def test_llm_down_is_503_but_sources_only_still_works(wired):
    wired["synth"] = llm.LLMUnavailable("primary(ConnectError)")
    with pytest.raises(HTTPException) as e:
        _ask(query="x")
    assert e.value.status_code == 503 and e.value.detail["error"] == "llm_unavailable"
    out = _ask(query="x", synthesize=False)
    assert out["answer"] is None and out["sources"] and out["sources"][0]["file_name"] == "f1.md"


def test_structural_and_digest_routes_use_no_llm(wired):
    out = _ask(query="how many projects are under 2026?")
    assert out["route"] == "structural" and out["llm_calls"] == 0 and "2 folder" in out["answer"]
    wired["digest"] = {"id": 1, "markdown": "CAREER INTELLIGENCE WEEKLY UPDATE\nNEW FILES\n3", "kind": "weekly", "run_id": "r", "created_at": "x"}
    out = _ask(query="what changed this week?")
    assert out["route"] == "digest" and out["llm_calls"] == 0 and out["answer"].startswith("CAREER")
    wired["digest"] = None
    out = _ask(query="what changed this week?")
    assert out["route"] == "fast" and out["degraded_reason"] == "no_weekly_digest_yet"
