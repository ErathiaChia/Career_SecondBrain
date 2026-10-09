from era_mcp import epistemic


def test_parse_labels_counts_unknowns_and_uncited():
    answer = """Here is the status.
- FACT: Go-live moved to 15 Dec [2].
- **INFERENCE:** UAT will likely slip too [2][4].
- UNKNOWN: who approved the new date.
FACT: Budget is SGD 200k."""
    out = epistemic.parse(answer)
    assert out["labelled"] is True
    assert out["counts"] == {"fact": 2, "inference": 1, "unknown": 1}
    assert out["unknowns"] == ["who approved the new date."]
    assert out["uncited_facts"] == ["Budget is SGD 200k."]


def test_parse_unlabelled_answer():
    out = epistemic.parse("The project started in March [1].")
    assert out["labelled"] is False
    assert out["counts"] == {"fact": 0, "inference": 0, "unknown": 0}
