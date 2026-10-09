from career_history import changes


def _f(id_, kind, statement, **kw):
    return {"id": id_, "kind": kind, "statement": statement, "topic": kw.get("topic"),
            "status": kw.get("status"), "priority": kw.get("priority"),
            "occurred_at": kw.get("occurred_at"), "due_at": kw.get("due_at"),
            "extractor_version": kw.get("v", "entity-rel-facts-v3")}


def test_diff_facts_detects_status_date_revision_add_remove():
    old = [
        _f(1, "action_item", "Send SOW", status="open"),
        _f(2, "milestone", "Go-live", occurred_at="2026-11-01"),
        _f(3, "decision", "Host on AWS", topic="hosting"),
        _f(4, "risk", "Key engineer leaving"),
    ]
    new = [
        _f(11, "action_item", "Send SOW", status="done"),
        _f(12, "milestone", "Go-live", occurred_at="2026-12-15"),
        _f(13, "decision", "Host on Azure", topic="hosting"),
        _f(14, "requirement", "SSO via Entra ID"),
    ]
    diffs = changes.diff_facts(old, new)
    by_stmt = {d["statement"]: d for d in diffs}
    assert by_stmt["Send SOW"]["deltas"] == {"status": ("open", "done")}
    assert by_stmt["Go-live"]["deltas"] == {"date": ("2026-11-01", "2026-12-15")}
    assert by_stmt["Host on Azure"]["previous"] == "Host on AWS"
    assert by_stmt["SSO via Entra ID"]["change_type"] == "fact_added"
    assert by_stmt["Key engineer leaving"]["change_type"] == "fact_removed"
    assert len(diffs) == 5


def test_fact_summary_and_severity():
    d = {"change_type": "fact_changed", "kind": "milestone", "statement": "Go-live",
         "deltas": {"date": ("2026-11-01", "2026-12-15")}}
    assert "date 2026-11-01 -> 2026-12-15" in changes._fact_summary(d)
    assert changes._fact_severity(d) == "warning"
    assert changes._fact_severity({"change_type": "fact_added", "kind": "action_item",
                                   "statement": "x", "deltas": {}}) == "info"


def test_record_fact_diff_skips_first_extraction_and_upgrades(monkeypatch):
    calls = []
    monkeypatch.setattr(changes.intel_db, "project_ids_for_files", lambda ids: {})
    monkeypatch.setattr(changes.intel_db, "insert_change", lambda *a, **k: calls.append(a))
    old_v2 = [_f(1, "decision", "Host on AWS", v="entity-rel-facts-v2")]
    assert changes.record_fact_diff(5, old_v2, [_f(2, "decision", "Host on Azure")], "entity-rel-facts-v3") == 0
    assert changes.record_fact_diff(5, [], [_f(2, "decision", "x")], "entity-rel-facts-v3") == 0
    assert changes.record_fact_diff(5, [_f(1, "decision", "a")], [_f(2, "decision", "b")],
                                    "entity-rel-facts-v3") == 2
    assert len(calls) == 2


def test_event_change_and_deterministic_impact():
    c = changes.event_change({"id": 1, "kind": "deleted", "file_id": None, "file_path": "/v/p/Plan.docx",
                              "file_name": None, "current_project_id": None,
                              "payload": {"project_id": 7, "facts": [{"id": 1}, {"id": 2}]}})
    assert c["project_id"] == 7 and c["severity"] == "warning" and "2 extracted fact" in c["summary"]
    v = changes.event_change({"id": 2, "kind": "version_added", "file_id": 3, "file_path": "x",
                              "file_name": "Plan v3.docx", "current_project_id": 7,
                              "payload": {"version_label": "v3", "family_key": "plan"}})
    assert v["change_type"] == "version_added" and v["summary"] == "New version v3 of plan"
    impact = changes.deterministic_impact([{**c, "payload": {}}, {**v, "payload": {}}])
    assert impact["rationale_found"] is False
    assert impact["rationale"] == changes.NO_RATIONALE
