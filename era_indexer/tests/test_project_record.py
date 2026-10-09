from career_history import project_state

PROJECT = {"id": 1, "name": "Acme Credit AI", "client": "Acme", "status": "ACTIVE", "project_type": "ai"}
FACTS = [{"id": 1, "kind": "milestone", "statement": "Go-live", "status": "done", "occurred_at": "2026-03-01",
          "attributes": {}, "confidence": 0.9, "file_id": 5, "file_name": "plan.xlsx"},
         {"id": 2, "kind": "decision", "statement": "Use Appian", "status": "approved", "occurred_at": "2026-01-15",
          "attributes": {}, "confidence": 0.8, "file_id": 5, "file_name": "arch.docx"}]
EXTRAS = {
    "roles": [{"role": "solution_architect", "confidence": 0.72, "status": "proposed", "sources": [{"fact_id": 2}],
               "updated_at": "2026-10-01T00:00:00"},
              {"role": "project_manager", "confidence": 0.4, "status": "proposed", "sources": []}],
    "technologies": [{"entity_id": 9, "name": "Appian", "entity_type": "technology", "mention_count": 7}],
    "events": [{"kind": "modified", "detected_at": "2026-04-02T10:00:00", "file_id": 5, "file_name": "plan.xlsx"}],
    "cards": [{"file_id": 5, "file_name": "arch.docx", "title": "Architecture", "doc_type": "architecture",
               "summary": "s", "fact_count": 2, "topics": ["genai agents"]}],
    "achievements": [{"id": 3, "statement": "Went live", "metric": None, "outcome_kind": "delivery", "is_me": True,
                      "confidence": 0.8, "evidence_fact_ids": [1]}],
    "related_projects": [{"project_id": 2, "name": "Orion Portal", "score": 0.61, "shared_entities": ["Appian"]}],
    "ai_keywords": ["genai", "llm"],
    "facts_by_id": {f["id"]: f for f in FACTS},
}


def test_project_record_fields():
    state = project_state.deterministic_state(PROJECT, FACTS, extras=EXTRAS)
    assert state["role"]["value"] == "solution_architect" and state["role"]["confidence"] == 0.72
    assert state["technologies"]["value"][0]["name"] == "Appian"
    tl = state["timeline"]["value"]
    assert [t["date"] for t in tl] == ["2026-01-15", "2026-03-01", "2026-04-02"]
    assert tl[-1]["kind"] == "file_modified"
    assert state["evidence_documents"]["value"][0]["doc_type"] == "architecture"
    assert state["outcomes"]["value"][0]["achievement_id"] == 3 and state["outcomes"]["confidence"] == 0.8
    assert state["related_projects"]["value"][0]["name"] == "Orion Portal"
    assert state["is_ai_initiative"] is True


def test_project_record_confirmed_role_wins_over_higher_proposed():
    extras = dict(EXTRAS, roles=[{"role": "project_manager", "confidence": 0.5, "status": "confirmed", "sources": []},
                                 {"role": "solution_architect", "confidence": 0.9, "status": "proposed", "sources": []}])
    state = project_state.deterministic_state(PROJECT, FACTS, extras=extras)
    assert state["role"]["value"] == "project_manager" and state["role"]["status"] == "confirmed"


def test_project_record_empty_extras():
    state = project_state.deterministic_state(PROJECT, FACTS)
    assert state["role"]["value"] == project_state.UNKNOWN
    assert state["is_ai_initiative"] is False and state["evidence_documents"]["value"] == []


def test_validate_rollup_handles_stage_and_business_problem():
    facts_by_id = {f["id"]: f for f in FACTS}
    raw = {"phase": {"value": "build", "source_fact_ids": [1]},
           "stage": {"value": "delivery", "source_fact_ids": [1], "confidence": 0.9},
           "business_problem": {"value": "Credit risk triage", "source_fact_ids": [99]},  # uncited -> UNKNOWN
           "summary": {"value": "ok", "source_fact_ids": [2]}, "objectives": [], "priorities": []}
    out = project_state.validate_rollup(raw, facts_by_id)
    assert out["stage"]["value"] == "delivery"
    assert out["business_problem"]["value"] == project_state.UNKNOWN


def test_rollup_prompt_mentions_new_fields():
    p = project_state._rollup_prompt(PROJECT, FACTS)
    assert '"stage"' in p and '"business_problem"' in p
