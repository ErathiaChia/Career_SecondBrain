from datetime import datetime

from career_history import cards, graph

FILE = {"file_id": 7, "file_name": "V2_Acme_Proposal.pptx", "folder": "01 Project", "file_type": "pptx",
        "file_hash": "h1", "last_modified_at": datetime(2026, 3, 1), "title": None}
FACTS = [{"id": 1, "kind": "decision", "statement": "Use token pricing", "status": "approved", "occurred_at": "2026-02-10"},
         {"id": 2, "kind": "risk", "statement": "Vendor delay", "status": "open", "priority": "high",
          "attributes": {"due_at": "2026-04-01"}},
         {"id": 3, "kind": "outcome", "statement": "Won the pilot", "attributes": {"metric": "SGD 50k"}},
         {"id": 4, "kind": "action_item", "statement": "Send SOW", "attributes": {"due_at": "2026-03-15"}}]
MENTIONS = [{"id": 10, "name": "Acme Bank", "type": "client", "mention_count": 5},
            {"id": 11, "name": "Jane Tan", "type": "person", "mention_count": 3},
            {"id": 12, "name": "Appian", "type": "technology", "mention_count": 2}]
PROJECTS = [{"id": 3, "name": "Acme Credit", "project_key": "ACME-CREDIT"}]
VERSIONS = [{"file_id": 6, "version_label": "V1", "version_rank": 1, "is_latest": False}]
LLM = {"title": "Acme credit proposal", "doc_type": "proposal", "summary": "A proposal for Acme.",
       "keywords": ["pricing", "tokens"], "topics": ["Pricing", "ai agents"],
       "outcomes": [{"statement": "Won the pilot", "metric": "50k"}, {"statement": "Shortlisted", "metric": None}],
       "dates": [{"date": "2026-02-28", "label": "submission"}], "references": ["Master SOW"]}


def test_assemble_merges_deterministic_and_llm_inputs():
    card = cards.assemble(FILE, LLM, FACTS, MENTIONS, PROJECTS, VERSIONS, {"version": "V2"})
    assert card["file_id"] == 7 and card["source_hash"] == "h1"
    assert card["intelligence_version"] == cards.INTELLIGENCE_VERSION
    assert card["title"] == "Acme credit proposal" and card["doc_type"] == "proposal"
    assert card["topics"] == ["pricing", "ai agents"]
    assert [d["fact_id"] for d in card["decisions"]] == [1]
    assert [r["fact_id"] for r in card["risks"]] == [2]
    assert [a["fact_id"] for a in card["actions"]] == [4]
    # fact outcome first, LLM outcome deduped against it, extra LLM outcome kept
    assert [o["statement"] for o in card["outcomes"]] == ["Won the pilot", "Shortlisted"]
    assert card["customers"] == [{"id": 10, "name": "Acme Bank"}]
    assert card["people"] == [{"id": 11, "name": "Jane Tan"}]
    assert card["technologies"] == [{"id": 12, "name": "Appian"}]
    assert card["projects"][0]["project_key"] == "ACME-CREDIT"
    dates = {(d["date"], d["source"]) for d in card["dates"]}
    assert ("2026-02-10", "fact") in dates and ("2026-04-01", "fact") in dates and ("2026-02-28", "llm") in dates
    assert card["doc_date"] == "2026-02-10"
    assert "Acme Bank" in card["card_text"] and "Use token pricing" in card["card_text"]
    assert card["references"] == [{"text": "Master SOW", "file_id": None}]


def test_assemble_without_llm_card_falls_back():
    card = cards.assemble(FILE, None, [], [], [], [])
    assert card["title"] == "V2_Acme_Proposal.pptx" and card["doc_type"] == "presentation"
    assert card["summary"] == "" and card["doc_date"] == "2026-03-01"


def test_inputs_hash_stable_and_sensitive():
    a = cards.inputs_hash(FACTS, MENTIONS, PROJECTS, VERSIONS)
    assert a == cards.inputs_hash(list(reversed(FACTS)), MENTIONS, PROJECTS, VERSIONS)
    assert a != cards.inputs_hash(FACTS[:1], MENTIONS, PROJECTS, VERSIONS)
    assert a != cards.inputs_hash(FACTS, MENTIONS, [], VERSIONS)


def test_related_documents_ranking_and_cap():
    versions = [{"file_id": 6}]
    siblings = [{"file_id": 20, "shared": 4}, {"file_id": 21, "shared": 1}, {"file_id": 22, "shared": 0}]
    neighbours = [{"file_id": 30, "cosine": 0.95}, {"file_id": 20, "cosine": 0.7}] + \
                 [{"file_id": 100 + i, "cosine": 0.61} for i in range(12)]
    rel = cards.related_documents(versions, siblings, neighbours)
    assert rel[0] == {"file_id": 6, "relation": "version", "score": 1.0}
    assert rel[1]["file_id"] == 30 and rel[1]["relation"] == "similar"
    by_id = {r["file_id"]: r for r in rel}
    assert by_id[20]["relation"] == "project" and by_id[20]["score"] == 0.9   # best wins over cosine 0.7
    assert 22 not in by_id and len(rel) == 10


def test_merge_cards_unions_and_caps():
    merged = graph.merge_cards([
        {"title": "T", "doc_type": "proposal", "summary": "first", "keywords": ["a", "B"], "topics": ["X"],
         "outcomes": [{"statement": "won", "metric": "1"}], "dates": [{"date": "2026-01-02", "label": "kickoff"}]},
        {"summary": "second", "keywords": ["b", "c"], "topics": ["x", "y"],
         "outcomes": [{"statement": "WON", "metric": "2"}, "delivered"], "dates": ["2026-01-02", {"date": "bad"}]},
        {},
    ])
    assert merged["title"] == "T" and merged["doc_type"] == "proposal"
    assert merged["summary"] == "[1/2] first [2/2] second"
    assert merged["keywords"] == ["a", "B", "c"] and merged["topics"] == ["x", "y"]
    assert [o["statement"] for o in merged["outcomes"]] == ["won", "delivered"]
    assert merged["dates"] == [{"date": "2026-01-02", "label": "kickoff", "source": "llm"},
                               {"date": "2026-01-02", "label": "", "source": "llm"}]
    assert graph.merge_cards([]) == {}
