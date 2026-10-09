from career_history import career

CFG = {"name": "Jane Tan", "aliases": ["Jane", "JT"], "default_roles": ["project_manager", "solution_architect"],
       "role_prior_weight": 0.35}
ME = 42


def _f(i, kind, stmt, owner=ME, **attrs):
    return {"id": i, "kind": kind, "statement": stmt, "owner_entity_id": owner, "attributes": attrs,
            "confidence": 0.8, "file_id": 1, "status": attrs.pop("status", None), "from_latest_version": True}


def test_prior_only_gives_two_equal_default_roles_below_threshold():
    out = career.score_roles({"id": 1, "name": "P"}, [], [], ME, CFG)
    assert set(out) == {"project_manager", "solution_architect"}
    assert out["project_manager"]["score"] == out["solution_architect"]["score"]
    assert out["project_manager"]["score"] < 0.60          # -> needs confirmation


def test_contribution_facts_lift_pm_above_confirmation_threshold():
    facts = [_f(1, "contribution", "Led the delivery team", activity="led"),
             _f(2, "contribution", "Managed the vendor plan", activity="managed"),
             _f(3, "contribution", "Planned the cutover", activity="planned"),
             _f(4, "action_item", "Send minutes"), _f(5, "action_item", "Chase approval")]
    out = career.score_roles({"id": 1, "name": "P"}, facts, [], ME, CFG)
    assert out["project_manager"]["score"] >= 0.60
    assert out["project_manager"]["score"] > out["solution_architect"]["score"]
    assert "contribution_facts" in out["project_manager"]["signals"]
    assert {"fact_id": 1} in out["project_manager"]["sources"]


def test_project_owner_and_role_label_signals():
    facts = [_f(1, "contribution", "Designed the target architecture", activity="designed", role_hint="Solution Architect")]
    out = career.score_roles({"id": 1, "name": "P", "owner": "Jane Tan"}, facts, [], ME, CFG)
    assert out["project_manager"]["signals"]["project_owner"] == 0.4
    assert out["solution_architect"]["signals"]["role_label"] == 0.35


def test_doc_type_mix_counts_when_i_am_listed():
    files = [{"file_id": 9, "doc_type": "architecture", "people": [{"name": "Jane Tan"}]},
             {"file_id": 10, "doc_type": "architecture", "people": [{"name": "Someone Else"}]}]
    out = career.score_roles({"id": 1, "name": "P"}, [], files, ME, CFG)
    assert out["solution_architect"]["signals"]["doc_types"] == 0.08
    assert {"file_id": 9} in out["solution_architect"]["sources"]


def test_parse_metric_and_outcome_kind():
    assert career.parse_metric("Cut processing time by 30%")["name"] == "percent"
    m = career.parse_metric("Won a SGD 50,000 contract")
    assert m["name"] == "currency" and m["value"] == "50000"
    assert career.parse_metric("Rolled out to 1,200 users")["unit"].startswith("user")
    assert career.parse_metric("Delivered in 3 weeks")["name"] == "duration"
    assert career.parse_metric("Nothing numeric") is None
    assert career.outcome_kind("Won the tender") == "win"
    assert career.outcome_kind("Reduced cost by 20%") == "cost"
    assert career.outcome_kind("Go-live achieved on schedule") == "delivery"
    assert career.outcome_kind("x", {"outcome_kind": "award"}) == "award"


def test_group_outcomes_dedupes_and_inherits_role():
    facts = [_f(1, "outcome", "Went live with 1,200 users on 1 March", owner=None),
             _f(2, "outcome", "Went live with 1,200 users on 1 march.", owner=None),
             _f(3, "milestone", "UAT sign-off", owner=None, status="done"),
             _f(4, "risk", "Vendor delay", owner=None),
             _f(5, "contribution", "Negotiated a 15% discount", owner=ME)]
    out = career.group_outcomes(facts, ME, my_role_conf=0.7)
    stmts = [o["statement"] for o in out]
    assert len(out) == 3 and "Vendor delay" not in stmts
    merged = next(o for o in out if o["statement"].startswith("Went live"))
    assert merged["evidence_fact_ids"] == [1, 2] and merged["is_me"] is True  # inherited from role
    assert next(o for o in out if "discount" in o["statement"])["metric"]["name"] == "percent"
    assert all(o["source_hash"] for o in out)


def test_group_outcomes_without_role_is_not_me():
    facts = [_f(1, "outcome", "Won the deal", owner=None)]
    out = career.group_outcomes(facts, ME, my_role_conf=0.2)
    assert out[0]["is_me"] is False and out[0]["confidence"] < 0.8


def test_skill_strength_monotonic():
    assert career.skill_strength(10, 0.8, 0) > career.skill_strength(2, 0.8, 0)
    assert career.skill_strength(10, 0.8, 2) > career.skill_strength(10, 0.8, 0)
    assert career.skill_strength(10, 0.0, 2) == 0.0
