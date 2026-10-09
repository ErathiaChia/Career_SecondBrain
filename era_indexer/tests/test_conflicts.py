from datetime import datetime

from career_history import conflicts


def _f(id_, kind, statement, file_id, **kw):
    base = {"id": id_, "kind": kind, "statement": statement, "file_id": file_id,
            "file_name": f"file{file_id}.docx", "topic": None, "status": None, "attributes": {},
            "occurred_at": None, "supersedes_fact_id": None, "from_latest_version": True,
            "last_verified_at": datetime(2026, 9, file_id)}
    base.update(kw)
    return base


def test_deterministic_date_and_status_conflicts():
    facts = [
        _f(1, "milestone", "UAT sign-off portal", 1, occurred_at="2026-11-01"),
        _f(2, "milestone", "UAT sign-off portal", 2, occurred_at="2026-12-15"),
        _f(3, "action_item", "Send revised SOW", 1, status="open"),
        _f(4, "action_item", "Send revised SOW", 3, status="done"),
        _f(5, "milestone", "UAT sign-off portal", 1, occurred_at="2026-10-01"),
    ]
    rows = conflicts.deterministic_conflicts(9, facts)
    kinds = {(r["fact_a_id"], r["fact_b_id"]): r for r in rows}
    assert kinds[(1, 2)]["conflict_type"] == "date_mismatch"
    assert kinds[(1, 2)]["likely_latest_fact_id"] == 2
    assert kinds[(3, 4)]["conflict_type"] == "status_mismatch"
    assert kinds[(3, 4)]["likely_latest_fact_id"] == 4
    assert (1, 5) not in kinds


def test_date_check_ignores_different_events_recurring_series_and_duplicates():
    facts = [
        # Different events about the same company: share most words, not the same claim.
        _f(1, "commitment", "TechSolutions Malaysia Sdn Bhd was incorporated on 2024-03-15", 1,
           occurred_at="2024-03-15"),
        _f(2, "commitment", "TechSolutions Malaysia Sdn Bhd commenced business on 2024-04-01", 2,
           occurred_at="2024-04-01"),
        # Recurring payments: same template, three distinct dates.
        _f(3, "commitment", "Payment Date 20-Oct-2025", 1, occurred_at="2025-10-20"),
        _f(4, "commitment", "Payment Date 20-Nov-2025", 2, occurred_at="2025-11-20"),
        _f(5, "commitment", "Payment Date 20-Dec-2025", 3, occurred_at="2025-12-20"),
        # Historical events are never date-compared.
        _f(6, "event", "Account turned NPL", 1, occurred_at="2017-12-30"),
        _f(7, "event", "Account turned NPL", 2, occurred_at="2019-12-30"),
        # A real slip, duplicated across two copies of the newer file.
        _f(8, "milestone", "UAT completes 30 Nov 2025", 1, occurred_at="2025-11-30"),
        _f(9, "milestone", "UAT completes 15 Jan 2026", 2, occurred_at="2026-01-15"),
        _f(10, "milestone", "UAT completes 15 Jan 2026", 3, occurred_at="2026-01-15"),
    ]
    rows = conflicts.deterministic_conflicts(9, facts)
    pairs = {(r["fact_a_id"], r["fact_b_id"]) for r in rows}
    assert pairs == {(8, 9)}


def test_shared_topic_needs_substantial_overlap():
    a = _f(1, "milestone", "UAT start", 1, topic="uat", occurred_at="2026-11-01")
    b = _f(2, "milestone", "UAT sign-off by client steering committee", 2, topic="uat",
           occurred_at="2026-12-15")
    c = _f(3, "milestone", "UAT start date", 3, topic="uat", occurred_at="2026-11-20")
    pairs = {(r["fact_a_id"], r["fact_b_id"]) for r in conflicts.deterministic_conflicts(9, [a, b, c])}
    assert pairs == {(1, 3)}


def test_tokens_strip_common_date_formats():
    t = conflicts._tokens
    assert t("Payment Date 20-Nov-2025") == t("Payment Date 20-Oct-2025") == frozenset({"payment", "date"})
    assert t("Downgraded to D- in Mar17") == t("Downgraded to D- in Apr 2019")
    assert t("Turned NPL on 30/12/17") == t("Turned NPL on 5/4/23")
    assert t("Secretary 1 appointed") != t("Secretary 2 appointed")
    assert "decision" in t("Marketing decision")


def test_latest_version_wins_over_recency():
    a = _f(1, "milestone", "Go-live", 5, occurred_at="2026-11-01")
    b = _f(2, "milestone", "Go-live", 1, occurred_at="2026-12-01", from_latest_version=True)
    a["from_latest_version"] = False
    assert conflicts._newer(a, b)["id"] == 2


def test_candidate_pairs_filters_and_ranks():
    facts = [
        _f(1, "decision", "Host the portal on AWS", 1, topic="hosting"),
        _f(2, "decision", "Host the portal on Azure", 2, topic="hosting"),
        _f(3, "decision", "Use Kafka for event streaming", 2),
        _f(4, "decision", "Host the portal on GCP", 1, topic="hosting"),
        _f(5, "requirement", "Host the portal on AWS", 3, topic="hosting"),
        _f(6, "decision", "Portal hosting on AWS regions", 3, supersedes_fact_id=1),
    ]
    pairs = conflicts.candidate_pairs(facts, checked={(1, 2)}, max_pairs=10)
    ids = [(a["id"], b["id"]) for a, b, _ in pairs]
    assert (1, 2) not in ids
    assert (2, 4) in ids
    assert (1, 4) not in ids
    assert all(a["kind"] == b["kind"] for a, b, _ in pairs)
    assert (1, 6) not in ids


def test_judge_pair_parses_llm(monkeypatch):
    a = _f(1, "decision", "Host on AWS", 1)
    b = _f(2, "decision", "Host on Azure", 2)
    monkeypatch.setattr(conflicts.llm, "generate_json", lambda p: {
        "contradicts": True, "conflict_type": "decision", "explanation": "Different clouds",
        "likely_latest": "A", "confidence": 0.8})
    row = conflicts.judge_pair(7, a, b)
    assert row["status"] == "needs_confirmation" and row["likely_latest_fact_id"] == 1
    monkeypatch.setattr(conflicts.llm, "generate_json", lambda p: {"contradicts": False})
    assert conflicts.judge_pair(7, a, b)["status"] == "no_conflict"


def test_compute_stale_flags():
    now = datetime(2026, 10, 5)
    facts = [
        {"id": 1, "kind": "milestone", "status": None, "supersedes_fact_id": None, "is_latest": True,
         "evidence_at": now},
        {"id": 2, "kind": "milestone", "status": None, "supersedes_fact_id": 1, "is_latest": True,
         "evidence_at": now},
        {"id": 3, "kind": "action_item", "status": "open", "supersedes_fact_id": None, "is_latest": None,
         "evidence_at": datetime(2024, 1, 1), "project_last_activity": datetime(2026, 9, 1)},
        # Same kind of old open item, but its project has been quiet for > 60 days.
        {"id": 6, "kind": "action_item", "status": "open", "supersedes_fact_id": None, "is_latest": None,
         "evidence_at": datetime(2024, 1, 1), "project_last_activity": datetime(2026, 6, 1)},
        # Not in any project.
        {"id": 7, "kind": "commitment", "status": None, "supersedes_fact_id": None, "is_latest": None,
         "evidence_at": datetime(2024, 1, 1), "project_last_activity": None},
        {"id": 4, "kind": "decision", "status": None, "supersedes_fact_id": None, "is_latest": False,
         "scope_key": "p", "family_key": "plan", "evidence_at": now},
        {"id": 5, "kind": "action_item", "status": "done", "supersedes_fact_id": None, "is_latest": None,
         "evidence_at": datetime(2020, 1, 1)},
    ]
    flags = conflicts.compute_stale_flags(
        facts, [{"fact_a_id": 1, "fact_b_id": 4, "likely_latest_fact_id": 1}],
        {("p", "plan"): 99}, now, max_age_days=365, active_days=60)
    got = {(f["object_id"], f["reason"]) for f in flags}
    assert got == {(1, "superseded"), (4, "contradicted_by_newer"), (4, "older_document_version"),
                   (3, "not_reverified")}
    assert next(f for f in flags if f["reason"] == "older_document_version")["newer_evidence_id"] == 99
