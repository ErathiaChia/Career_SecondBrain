from tools import scorecard as sc

API = {
    "/projects/CL89": {"client": "CL89", "status": "DORMANT", "project_type": "proposal"},
    "/projects/CL89/entities": {"entities": [{"canonical_name": "CL88", "aliases": ["Development Bank"]},
                                            {"canonical_name": "Kafka", "aliases": []}]},
    "/projects/CL89/facts": {"facts": [{"statement": "Host the portal on Azure", "source_quote": "use Azure"}]},
    "/projects/CL89/conflicts": {"conflicts": [{"fact_a": "Go-live 1 Nov", "fact_b": "Go-live 15 Dec",
                                               "explanation": "dates differ"}]},
    "/projects/CL89/documents": {"families": [{"family_key": "ibf proposal", "latest": "CL89 Proposal v3.docx",
                                              "versions": [{"file_name": "CL89 Proposal v2.docx"},
                                                           {"file_name": "CL89 Proposal v3.docx"}]}]},
    "/projects/CL89/stale": {"stale": [{"statement": "Go-live 1 Nov"}]},
    "/projects/CL89/state": {"state": {"phase": {"value": "build"},
                                      "blockers": {"value": [{"statement": "Vendor API delay"}]}}},
    "/projects/CL89/brief": {"markdown": "## Brief\n- a [F1, x]\n- b [F2, y]\n- c\n"},
}


def fetch(path, params):
    return API[path]


def _run(check):
    return sc.score_check({"project": "CL89", **check}, fetch)


def test_project_fields_partial():
    r = _run({"type": "project_fields", "expect": {"client": "CL89", "status": "ACTIVE"}})
    assert r["score"] == 0.5 and "status" in r["detail"][0]


def test_recall_checks():
    assert _run({"type": "entities", "expect": ["development bank", "Kafka", "Alice"]})["score"] == 2 / 3
    assert _run({"type": "facts", "kind": "decision", "expect": [["portal", "azure"]]})["score"] == 1.0
    assert _run({"type": "conflicts", "expect": [["go-live", "1 nov"]]})["score"] == 1.0
    assert _run({"type": "stale", "expect": ["Go-live 1 Nov", "Budget 200k"]})["score"] == 0.5


def test_latest_version_state_and_attribution():
    assert _run({"type": "latest_version", "family_contains": "proposal",
                 "expect_latest_contains": "v3"})["score"] == 1.0
    assert _run({"type": "latest_version", "family_contains": "sow",
                 "expect_latest_contains": "v3"})["score"] == 0.0
    assert _run({"type": "state", "field": "phase", "expect_contains": "build"})["score"] == 1.0
    assert _run({"type": "state", "field": "blockers", "expect_contains": "vendor api"})["score"] == 1.0
    assert abs(_run({"type": "attribution"})["score"] - 2 / 3) < 1e-9


def test_summarize():
    s = sc.summarize_project_suite([{"type": "facts", "score": 1.0}, {"type": "facts", "score": 0.0},
                                    {"type": "state", "score": 1.0}])
    assert s["per_type"] == {"facts": 0.5, "state": 1.0} and s["overall"] == 0.75
