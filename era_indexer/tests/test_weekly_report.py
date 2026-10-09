from datetime import datetime

from career_history import monitor

INPUTS = {
    "run": {"run_id": "weekly-20261010-0100-abc", "kind": "weekly", "status": "finished",
            "counts": {"docs_extracted": 40, "docs_failed": 1, "docs_remaining": 12, "deadline_hit": False}},
    "window": {"since": datetime(2026, 10, 3, 1, 0)},
    "event_counts": {"added": 42, "modified": 130, "version_added": 7, "deleted": 2},
    "deleted": [{"file_path": "/v/x.md", "file_name": "x.md"}],
    "project_info": [{"project": "Acme Credit", "new_docs": 3, "new_facts": 18, "new_decisions": 2}],
    "new_decisions": [{"id": 812, "statement": "Adopt token pricing", "project": "Acme Credit", "file_name": "pricing.docx",
                       "occurred_at": "2026-10-05"}],
    "new_achievements": [{"id": 9, "statement": "Went live with 1,200 users", "metric": {"raw": "1,200 users"},
                          "project": "Acme Credit", "is_me": True}],
    "changed_information": [{"project": "Acme Credit", "summary": "Go-live moved from 1 Mar to 15 Mar",
                             "impact": {"summary": "UAT compressed"}}],
    "conflicts": [{"id": 3, "project": "Acme Credit", "statement_a": "SGD 50k fixed fee", "statement_b": "Token pricing",
                   "conflict_type": "pricing_model", "likely_latest_fact_id": 812}],
    "open_conflicts_total": 4,
    "stale": [{"project": "Orion Portal", "statement": "Old pricing sheet applies", "reason": "contradicted_by_newer",
               "newer_evidence_id": 812}],
    "eval": {"career": "0.81 (prev 0.74)", "agent": "0.9 (prev None) HARD GATE FAILED"},
}


def test_report_has_every_brief_section_in_order():
    md = monitor.render_weekly_report(INPUTS, generated=datetime(2026, 10, 12, 6, 0),
                                      attention="# Project digest — x\n_1 item_\n\n## Acme Credit\n- **[70] Health RED**")
    heads = ["CAREER INTELLIGENCE WEEKLY UPDATE", "NEW FILES", "MODIFIED", "NEW PROJECT INFORMATION", "NEW DECISIONS",
             "NEW ACHIEVEMENTS", "CHANGED INFORMATION", "CONFLICTS", "STALE INFORMATION",
             "DELETED FILES", "PIPELINE", "EVAL TREND", "ATTENTION ITEMS"]
    pos = [md.index(h) for h in heads]
    assert pos == sorted(pos)
    assert "NEW FILES\n──────────────\n42" in md
    assert "MODIFIED\n──────────────\n137" in md            # modified + version_added + restored
    assert "[F812] Adopt token pricing — Acme Credit · pricing.docx · 2026-10-05" in md
    assert "[A9] Went live with 1,200 users [1,200 users] — Acme Credit (mine)" in md
    assert "'SGD 50k fixed fee' vs 'Token pricing' — pricing_model, likely latest [F812] (#3)" in md
    assert "(4 open in total)" in md
    assert "contradicted_by_newer (newer: [F812])" in md
    assert "HARD GATE FAILED" in md and "Health RED" in md
    assert "run weekly-20261010-0100-abc · finished" in md


def test_report_empty_sections_say_none():
    md = monitor.render_weekly_report({"event_counts": {}}, generated=datetime(2026, 10, 12))
    assert md.count("(none)") >= 6 and "NEW FILES\n──────────────\n0" in md
