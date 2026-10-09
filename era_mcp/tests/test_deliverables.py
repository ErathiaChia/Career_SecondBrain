from era_mcp import deliverables as d

TODAY = "2026-10-05"
PROJECT = {"id": 1, "name": "CL89 Portal", "client": "CL89", "project_type": "delivery",
           "status": "ACTIVE", "last_activity": "2026-10-01T10:00:00"}


def _f(fid, kind, statement, **kw):
    base = {"fact_id": fid, "kind": kind, "statement": statement, "status": None, "priority": None,
            "owner": None, "attributes": {}, "occurred_at": None, "file_name": "plan.docx",
            "from_latest_version": True, "stale_reasons": [], "conflict_ids": [], "topic": None}
    base.update(kw)
    return base


FACTS = [
    _f(1, "action_item", "Send SOW", status="open", owner="Alice", attributes={"due_at": "2026-09-30"}),
    _f(2, "action_item", "Book UAT room", status="open", attributes={"due_at": "2026-10-08"}),
    _f(3, "action_item", "Draft charter", status="done"),
    _f(4, "risk", "Vendor API may slip", status="open", priority="high"),
    _f(5, "open_question", "Who signs off security?", status="open", owner="Bob"),
    _f(6, "decision", "Host on Azure", from_latest_version=False),
    _f(7, "milestone", "Go-live", occurred_at="2026-12-15"),
    _f(8, "commitment", "Weekly status report", status="open", stale_reasons=["not_reverified"]),
]
CONFLICTS = [{"id": 9, "status": "needs_confirmation", "fact_a": "Go-live 1 Nov", "fact_b": "Go-live 15 Dec",
              "fact_a_id": 70, "fact_b_id": 7, "fact_a_file": "old.pptx", "fact_b_file": "plan.docx",
              "conflict_type": "date_mismatch", "explanation": "Different go-live dates"}]


def test_rank_next_actions_orders_by_urgency_with_reasons():
    actions = d.rank_next_actions(FACTS, CONFLICTS, today=TODAY)
    assert actions[0]["action"] == "Send SOW"
    assert "overdue since 2026-09-30" in actions[0]["reasons"]
    types = [a["type"] for a in actions]
    assert {"risk", "conflict", "open_question", "stale"} <= set(types)
    assert "Draft charter" not in [a["action"] for a in actions]
    assert actions[0]["source"].startswith("[F1, plan.docx]")


def test_render_brief_cites_and_flags():
    md = d.render_brief(PROJECT, None, FACTS, [], CONFLICTS, [], today=TODAY)
    assert "## Project brief: CL89 Portal" in md
    assert "No project state built yet" in md
    assert "Host on Azure" in md and "older version" in md
    assert "Needs confirmation" in md
    assert "[F7, plan.docx]" in md


def test_render_meeting_prep_per_attendee_and_topic():
    md = d.render_meeting_prep(PROJECT, FACTS, [], CONFLICTS, ["Alice", "Bob"], None, today=TODAY)
    assert "### With Alice\n- Send SOW" in md
    assert "### With Bob\n- Who signs off security?" in md
    assert "Overdue items (1)" in md
    md_topic = d.render_meeting_prep(PROJECT, FACTS, [], [], [], "UAT", today=TODAY)
    assert "Book UAT room" in md_topic and "Send SOW" not in md_topic


def test_render_whats_happening():
    md = d.render_whats_happening(
        [{"project": "CL89 Portal", "summary": "Document modified: plan.docx",
          "impact": {"summary": "Go-live moved", "impact": ["Timeline slips 6 weeks"]}}],
        [{"name": "CL89 Portal", "level": "amber", "headline": "delivery weak"}],
        [{"due": "2026-10-08", "project": "CL89 Portal", "statement": "Book UAT room", "fact_id": 2}], 7)
    assert "Go-live moved" in md and "Timeline slips" in md and "AMBER" in md and "2026-10-08" in md
