from datetime import date, datetime

from career_history import monitor

TODAY = date(2026, 10, 5)

INPUTS = {
    "changes": [
        {"project_id": 1, "project": "IBF", "batch_id": "b1", "severity": "warning", "summary": "x",
         "impact": {"summary": "Go-live moved to Dec", "impact": ["Timeline slips"], "rationale_found": False}},
        {"project_id": 1, "project": "IBF", "batch_id": "b1", "severity": "info", "summary": "y", "impact": {}},
        {"project_id": 2, "project": "HLB", "batch_id": "b2", "severity": "info", "summary": "z",
         "impact": {"summary": "Doc touched"}},
    ],
    "states": [
        {"project_id": 1, "project": "IBF", "health": {"level": "red", "overall": 35, "headline": "delivery"},
         "overdue": [{"fact_id": 3, "statement": "Send SOW", "due": "2026-09-30"}],
         "upcoming": [{"fact_id": 7, "statement": "UAT start", "due": "2026-10-09"},
                      {"fact_id": 8, "statement": "Go-live", "due": "2026-12-15"}]},
        {"project_id": 2, "project": "HLB", "health": {"level": "green", "overall": 90}, "overdue": [],
         "upcoming": []},
    ],
    "conflicts": [{"id": 5, "project_id": 1, "project": "IBF", "conflict_type": "date_mismatch",
                   "explanation": "Two go-live dates"},
                  {"id": 6, "project_id": 2, "project": "HLB", "conflict_type": "date_mismatch",
                   "explanation": "Two UAT dates"},
                  {"id": 9, "project_id": 2, "project": "HLB", "conflict_type": "status_mismatch",
                   "explanation": "SOW open vs done"}],
    "proposed": [{"id": 1, "title": "Chase vendor", "project": "IBF"}],
    "previous_keys": {"conflict:1:5"},
}


def test_score_items_scores_and_penalises_repeats():
    items = monitor.score_items(INPUTS, today=TODAY)
    by_key = {i["key"]: i for i in items}
    assert by_key["change:b1"]["score"] == 62
    assert by_key["change:b2"]["score"] == 11
    assert by_key["health:1:red"]["score"] == 70
    assert by_key["overdue:1:3"]["score"] == 50
    assert "upcoming:7" in by_key and "upcoming:8" not in by_key
    assert by_key["conflict:1:5"]["score"] == 45 - monitor.REPEAT_PENALTY
    assert by_key["conflict:1:5"]["repeat"] is True
    hlb = by_key["conflict:2:6,9"]
    assert hlb["score"] == 46 and hlb["title"].startswith("2 conflicting fact pair(s)")
    assert "Two UAT dates" in hlb["detail"] and "SOW open vs done" in hlb["detail"]
    assert not any(k.startswith("health:2") for k in by_key)
    assert items[0]["key"] == "health:1:red"


def test_render_digest_applies_threshold():
    items = monitor.score_items(INPUTS, today=TODAY)
    md = monitor.render_digest(items, threshold=40, generated=datetime(2026, 10, 5, 7, 30))
    assert "# Project digest — 2026-10-05 07:30" in md
    assert "Go-live moved to Dec" in md and "Rationale not found" in md
    assert "Doc touched" not in md
    assert "Two go-live dates" not in md
    assert "## IBF" in md
    empty = monitor.render_digest([], threshold=40)
    assert "Nothing needs your attention" in empty


def test_run_isolates_stage_failures(monkeypatch):
    import career_history.changes as changes
    import career_history.conflicts as conflicts
    import career_history.project_state as project_state
    import career_history.projects as projects
    import career_history.similarity as similarity
    import career_history.versions as versions

    monkeypatch.setattr(projects, "discover_projects", lambda: {"projects": 3})
    monkeypatch.setattr(versions, "link_versions", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(changes, "detect_changes", lambda use_llm: {})
    monkeypatch.setattr(conflicts, "detect_conflicts", lambda use_llm, max_pairs: {})
    monkeypatch.setattr(conflicts, "detect_stale", lambda: {})
    monkeypatch.setattr(project_state, "refresh_states", lambda use_llm: {})
    monkeypatch.setattr(similarity, "refresh_similarity", lambda: {})
    monkeypatch.setattr(monitor, "build_digest", lambda threshold: {"markdown": "", "kept": 2})
    out = monitor.run(skip_sync=True, skip_extract=True, use_llm=False)
    assert out["projects"] == "ok"
    assert out["versions"].startswith("RuntimeError: boom")
    assert out["digest"] == "ok" and out["digest_items"] == 2
