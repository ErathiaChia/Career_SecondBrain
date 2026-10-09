from tools import scorecard as sc


def _resp(**over):
    base = {"answer": "FACT: Go-live on 1 Mar [1].\nFACT: Token pricing approved [F12].\nINFERENCE: delivery was on time [1][F12].",
            "citations": [{"n": 1, "label": "[1]", "file_id": 5, "file_name": "plan.xlsx", "file_path": "/v/P/plan.xlsx", "folder": "P"},
                          {"n": 2, "label": "[F12]", "fact_id": 12, "file_id": 6, "file_name": "pricing.docx"}],
            "sources": None, "tools_used": ["find_career_evidence"], "iterations": 2, "tool_calls": 4,
            "budget": {"documents_used": 4, "max_documents": 10, "elapsed_s": 40.0, "stop_reason": "judge_answer"},
            "project": {"name": "Acme Credit", "project_key": "ACME-CREDIT"}, "sufficient": True, "route": "investigate",
            "llm_calls": 4, "provider": {"fallback": "disabled (policy)"}}
    base.update(over)
    return base


def test_traceability_passes_when_every_fact_is_cited_and_resolves():
    score, problems = sc.traceability(_resp())
    assert score == 1.0 and problems == []


def test_traceability_flags_uncited_and_dangling():
    score, problems = sc.traceability(_resp(answer="FACT: nobody knows.\nFACT: cited [9]."))
    assert score == 0.0
    assert any("uncited FACT" in p for p in problems) and any("dangling citation [9]" in p for p in problems)


def test_boundedness_and_local_first():
    assert sc.boundedness(_resp())[0] == 1.0
    assert sc.boundedness(_resp(iterations=4))[0] == 0.0
    assert sc.boundedness(_resp(tool_calls=10))[0] == 0.0
    assert sc.boundedness(_resp(budget={"documents_used": 11, "max_documents": 10}))[0] == 0.0
    assert sc.local_first(_resp())[0] == 1.0
    assert sc.local_first(_resp(provider={"fallback": "openai:gpt-4.1-mini"}))[0] == 0.0


def test_score_career_question_metrics():
    q = {"id": "q1", "expect_projects": ["Acme Credit"], "expect_path_contains": ["plan.xlsx"],
         "expect_fact_contains": [["token", "pricing"]], "expect_tools_any": ["find_career_evidence"], "min_citations": 2}
    r = sc.score_career_question(q, _resp(), 12.3)
    assert r["project_hit"] == 1.0 and r["path_hit"] == 1.0 and r["fact_recall"] == 1.0 and r["evidence"] == 1.0
    assert r["tools_ok"] == 1.0 and r["traceability"] == 1.0 and r["boundedness"] == 1.0 and r["elapsed_s"] == 12.3
    r2 = sc.score_career_question({"id": "q2", "expect_projects": ["Orion"], "min_citations": 4,
                                   "expect_tools_any": ["compare_documents"]}, _resp(), 1.0)
    assert r2["project_hit"] == 0.0 and r2["evidence"] == 0.5 and r2["tools_ok"] == 0.0
    r3 = sc.score_career_question({"id": "q3"}, {"error": "llm_unavailable"}, 0.0)
    assert r3["error"] and r3["traceability"] == 0.0


def test_summaries_and_thresholds():
    rows = [sc.score_career_question({"id": "a", "min_citations": 1}, _resp(), 10.0),
            sc.score_career_question({"id": "b", "min_citations": 1}, _resp(answer="FACT: x."), 30.0)]
    s = sc.summarize_career(rows)
    assert s["questions"] == 2 and s["metrics"]["traceability"] == 0.5 and s["metrics"]["elapsed_p50_s"] == 20.0
    th = {"career": {"traceability": 1.0, "evidence": 0.75, "hard": ["traceability"]}}
    s = sc.apply_thresholds("career", s, th)
    assert s["thresholds"]["traceability"] is False and s["hard_gate_passed"] is False
    s2 = sc.apply_thresholds("career", sc.summarize_career(rows[:1]), th)
    assert s2["hard_gate_passed"] is True
