from career_history import graph


def test_normalize_facts_maps_kinds_status_priority():
    facts = graph.normalize_facts([
        {"kind": "Action", "statement": "Send SOW to client", "status": "Pending", "priority": "P1",
         "owner": "Alice", "quote": "Alice to send SOW"},
        {"kind": "risk", "statement": "Vendor API may slip", "severity": "Critical"},
        {"kind": "milestone", "statement": "UAT complete", "attributes": {"due_at": "target 2026-11-30"}},
        {"kind": "gossip", "statement": "ignored"},
        {"kind": "decision", "statement": ""},
    ])
    assert [f["kind"] for f in facts] == ["action_item", "risk", "milestone"]
    action, risk, milestone = facts
    assert (action["status"], action["priority"], action["owner"]) == ("open", "high", "Alice")
    assert (risk["status"], risk["priority"]) == ("open", "high")
    assert milestone["occurred_at"] == "2026-11-30"
    assert milestone["status"] is None


def test_normalize_facts_orders_superseding_fact_after_original():
    facts = graph.normalize_facts([
        {"kind": "milestone", "statement": "Go-live moved to 2026-12-15",
         "supersedes": "Go-live on 2026-11-01"},
        {"kind": "milestone", "statement": "Go-live on 2026-11-01"},
    ])
    assert [f["statement"] for f in facts] == ["Go-live on 2026-11-01", "Go-live moved to 2026-12-15"]


def test_normalize_status_and_priority():
    assert graph.normalize_status("In Progress") == "in_progress"
    assert graph.normalize_status("closed") == "done"
    assert graph.normalize_status("whatever") is None
    assert graph.normalize_priority("Med") == "medium"
    assert graph.normalize_priority(None) is None


def test_doc_type_hint_routes_by_type_and_name():
    assert "RAID" in graph.doc_type_hint("xlsx", "HLB_RAID_Log_v3.xlsx")
    assert "Slide deck" in graph.doc_type_hint("pptx", "Kickoff.pptx")
    assert "Meeting" in graph.doc_type_hint("docx", "2026-09-01 Meeting Minutes.docx")
    assert "Proposal" in graph.doc_type_hint("pdf", "IBF_Proposal_v2.pdf")
    assert "README" in graph.doc_type_hint("md", "README.md")
    assert "Meeting" in graph.doc_type_hint("m4a", "recording.m4a")


def test_prompt_lists_new_kinds_and_hint():
    prompt = graph._prompt("text", {"file_name": "RAID.xlsx", "metadata": {"file_type": "xlsx"}}, True)
    for kind in ("requirement", "risk", "action_item", "open_question", "dependency", "milestone"):
        assert kind in prompt
    assert "Tracker / RAID log" in prompt
