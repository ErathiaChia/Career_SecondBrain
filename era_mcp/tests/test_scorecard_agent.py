from tools import scorecard as sc


def _resp(**over):
    base = {"answer": "FACT: yes [1].", "route": "fast", "llm_calls": 2, "iterations": 0, "tool_calls": 0,
            "budget": {"documents_used": 3, "max_documents": 10, "elapsed_s": 12.0}, "sufficient": True, "gaps": "",
            "tools_used": [], "provider": {"fallback": "disabled (policy)"},
            "citations": [{"n": 1, "label": "[1]", "file_id": 1, "file_name": "a.md"}]}
    base.update(over)
    return base


def test_fast_investigate_digest_insufficient_kinds():
    assert sc.score_agent_question({"id": "f", "kind": "fast"}, _resp(), 12.0)["ok"] == 1.0
    assert sc.score_agent_question({"id": "f", "kind": "fast"}, _resp(llm_calls=3), 12.0)["ok"] == 0.0
    inv = _resp(route="investigate", iterations=2, tool_calls=5, tools_used=["compare_documents"])
    assert sc.score_agent_question({"id": "i", "kind": "investigate", "expect_tools_any": ["compare_documents"]}, inv, 50.0)["ok"] == 1.0
    assert sc.score_agent_question({"id": "i", "kind": "investigate", "expect_tools_any": ["find_conflicts"]}, inv, 50.0)["ok"] == 0.0
    dig = _resp(route="digest", llm_calls=0)
    assert sc.score_agent_question({"id": "d", "kind": "digest"}, dig, 0.3)["ok"] == 1.0
    ins = _resp(sufficient=False, gaps="no data on that")
    assert sc.score_agent_question({"id": "n", "kind": "insufficient"}, ins, 20.0)["ok"] == 1.0
    assert sc.score_agent_question({"id": "n", "kind": "insufficient"}, _resp(), 20.0)["ok"] == 0.0


def test_agent_summary_and_hard_gates():
    rows = [sc.score_agent_question({"id": "f1", "kind": "fast"}, _resp(), 10.0),
            sc.score_agent_question({"id": "f2", "kind": "fast"}, _resp(), 40.0),
            sc.score_agent_question({"id": "i1", "kind": "investigate"}, _resp(route="investigate", iterations=4), 90.0)]
    s = sc.summarize_agent(rows)
    assert s["metrics"]["fast_p50_s"] == 25.0 and s["metrics"]["fast_llm_calls_max"] == 2
    assert s["metrics"]["boundedness"] < 1.0
    s = sc.apply_thresholds("agent", s, {"agent": {"fast_p50_s": 30, "boundedness": 1.0, "hard": ["boundedness"]}})
    assert s["thresholds"]["fast_p50_s"] is True and s["hard_gate_passed"] is False


def test_freshness_scoring():
    hits = [{"file_path": "/v/Z. AI_Notebook/_eval/freshness_probe.md"}]
    assert sc.score_freshness(hits, "weekly-1", "freshness_probe")["score"] == 1.0
    assert sc.score_freshness([], "weekly-1", "freshness_probe")["score"] == 0.0
    assert sc.score_freshness(hits, None, "freshness_probe")["score"] == 0.0
