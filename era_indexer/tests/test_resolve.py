from career_history import resolve


def _e(id_, name, type_="company", mentions=1, metadata=None):
    return {"id": id_, "canonical_name": name, "entity_type": type_,
            "aliases": [], "metadata": metadata or {}, "mention_count": mentions}


def test_name_tokens_strip_corporate_suffixes_for_orgs_only():
    assert resolve.name_tokens("ST Engineering Pte Ltd", "company") == ["st", "engineering"]
    assert resolve.name_tokens("Working Group", "concept") == ["working", "group"]


def test_token_match_prefix_and_abbreviation():
    assert resolve.token_match("engg", "engineering")
    assert resolve.token_match("eng", "engineering")
    assert not resolve.token_match("st", "sg")
    assert not resolve.token_match("2024", "2025")


def test_acronym_match():
    assert resolve.acronym_match("DBS", ["development", "bank", "of", "singapore"])
    assert not resolve.acronym_match("dbs", ["development", "bank", "singapore"])
    assert not resolve.acronym_match("DBS", ["dbs"])


def test_plan_merges_folds_variants_into_most_mentioned():
    entities = [
        _e(1, "ST Engineering", mentions=40),
        _e(2, "ST Engg", mentions=3),
        _e(3, "ST Engineering Pte Ltd", type_="organization", mentions=5),
        _e(4, "Singtel", mentions=10),
    ]
    merges = resolve.plan_merges(entities)
    assert {(m["source_id"], m["target_id"]) for m in merges} == {(2, 1), (3, 1)}


def test_plan_merges_respects_type_groups():
    entities = [_e(1, "Kafka", "technology"), _e(2, "Kafka", "person")]
    assert resolve.plan_merges(entities) == []


def test_plan_merges_prefers_project_anchored_entity():
    entities = [
        _e(1, "IBF Portal", "project", mentions=50),
        _e(2, "IBF-Portal", "project", mentions=2, metadata={"source": "path-seed"}),
    ]
    merges = resolve.plan_merges(entities)
    assert merges and merges[0]["target_id"] == 2


def test_plan_merges_embedding_requires_shared_token():
    vecs = {"Data Platform": [1.0, 0.0], "Data Lakehouse": [0.99, 0.05], "Lakehouse": [0.99, 0.05]}
    entities = [_e(1, "Data Platform", "concept"), _e(2, "Data Lakehouse", "concept"),
                _e(3, "Dashboard", "concept")]
    merges = resolve.plan_merges(entities, embed=lambda names: [vecs.get(n, [0.0, 1.0]) for n in names],
                                 threshold=0.93)
    assert [(m["source_id"], m["target_id"], m["method"]) for m in merges] in (
        [(1, 2, "embedding")], [(2, 1, "embedding")])
