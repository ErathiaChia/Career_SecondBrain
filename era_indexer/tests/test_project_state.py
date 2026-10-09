from datetime import datetime

from career_history import project_state as ps

NOW = datetime(2026, 10, 5)
PROJECT = {"id": 1, "name": "IBF Portal", "client": "IBF", "status": "ACTIVE",
           "project_type": "delivery", "owner": None, "last_activity": datetime(2026, 9, 30)}


def _f(id_, kind, statement, **kw):
    base = {"id": id_, "kind": kind, "statement": statement, "topic": None, "status": None,
            "priority": None, "attributes": {}, "occurred_at": None, "last_verified_at": datetime(2026, 9, 1),
            "confidence": 0.8, "source_quote": statement, "supersedes_fact_id": None, "file_id": 10,
            "file_name": "notes.md", "last_modified_at": datetime(2026, 9, 1), "owner": None,
            "from_latest_version": True}
    base.update(kw)
    return base


FACTS = [
    _f(1, "decision", "Use Azure for hosting"),
    _f(2, "risk", "Vendor API may slip", status="open", priority="high"),
    _f(3, "action_item", "Send SOW", status="open", owner="Alice", attributes={"due_at": "2026-09-20"}),
    _f(4, "action_item", "Book UAT room", status="open", attributes={"due_at": "2026-10-20"}),
    _f(5, "milestone", "Go-live 2026-11-01", occurred_at=datetime(2026, 11, 1)),
    _f(6, "milestone", "Go-live 2026-12-15", occurred_at=datetime(2026, 12, 15), supersedes_fact_id=5),
    _f(7, "open_question", "Who signs off security?", status="open"),
    _f(8, "requirement", "SSO via Entra ID", from_latest_version=False),
    _f(9, "action_item", "Draft charter", status="done"),
]


def test_deterministic_state_derives_fields_and_drops_superseded():
    state = ps.deterministic_state(PROJECT, FACTS, now=NOW)
    assert [i["fact_id"] for i in state["next_actions"]["value"]] == [3, 4]
    assert [i["fact_id"] for i in state["overdue"]["value"]] == [3]
    assert [i["fact_id"] for i in state["milestones"]["value"]] == [6]
    assert state["superseded_count"] == 1
    assert [i["fact_id"] for i in state["blockers"]["value"]] == [2]
    assert state["requirements"]["value"][0]["confidence"] < 0.8
    assert state["next_actions"]["sources"][0]["file_name"] == "notes.md"
    assert state["next_actions"]["last_verified"].startswith("2026-09-01")


def test_health_is_explainable():
    state = ps.deterministic_state(PROJECT, FACTS, now=NOW)
    health = ps.compute_health(PROJECT, state, {"stale_facts": 0}, now=NOW)
    dims = health["dimensions"]
    assert dims["delivery"]["evidence"] == [3]
    assert dims["risk"]["level"] in {"amber", "green"}
    assert dims["activity"]["score"] == 100
    assert health["level"] in {"green", "amber", "red"}
    assert "weakest dimension" in health["headline"]


def test_validate_rollup_drops_uncited_and_marks_unknown():
    facts_by_id = {f["id"]: f for f in FACTS}
    raw = {
        "phase": {"value": "build", "source_fact_ids": [999], "confidence": 0.9},
        "summary": {"value": "On track for December go-live", "source_fact_ids": ["6", 1]},
        "objectives": [{"value": "Launch portal", "source_fact_ids": [6]},
                       {"value": "Invented goal", "source_fact_ids": []}],
        "priorities": "not a list",
    }
    out = ps.validate_rollup(raw, facts_by_id)
    assert out["phase"]["value"] == ps.UNKNOWN
    assert out["summary"]["value"] == "On track for December go-live"
    assert {s["fact_id"] for s in out["summary"]["sources"]} == {1, 6}
    assert out["objectives"]["value"] == ["Launch portal"]
    assert out["priorities"]["value"] == []


def test_source_hash_stable_and_sensitive_to_facts():
    state = ps.deterministic_state(PROJECT, FACTS, now=NOW)
    health = ps.compute_health(PROJECT, state, {}, now=NOW)
    h1 = ps.source_hash(PROJECT, FACTS, {}, state, health)
    assert h1 == ps.source_hash(PROJECT, FACTS, {}, state, health)
    changed = FACTS[:-1] + [_f(9, "action_item", "Draft charter", status="open")]
    assert h1 != ps.source_hash(PROJECT, changed, {}, state, health)
