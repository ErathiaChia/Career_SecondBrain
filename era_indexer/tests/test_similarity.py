from career_history import similarity


def test_combine_blends_cosine_and_entity_overlap():
    neighbors = [
        {"project_id": 1, "other_project_id": 2, "cosine": 0.80},
        {"project_id": 1, "other_project_id": 3, "cosine": 0.85},
        {"project_id": 1, "other_project_id": 4, "cosine": 0.60},
    ]
    entity_sets = {1: {10, 11, 12}, 2: {10, 11, 12}, 3: {99}, 4: set()}
    rows = similarity.combine(neighbors, entity_sets, top_k=2, names={10: "DBS", 11: "Kafka", 12: "Alice"})
    assert [r["other_project_id"] for r in rows] == [2, 3]
    top = rows[0]
    assert top["entity_overlap"] == 1.0
    assert top["score"] == round(0.7 * 0.8 + 0.3 * 1.0, 4)
    assert top["shared_entities"] == ["Alice", "DBS", "Kafka"]
    assert rows[1]["shared_entities"] == []
