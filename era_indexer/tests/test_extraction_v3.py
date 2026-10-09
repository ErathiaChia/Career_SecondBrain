import pytest

from career_history import graph


def test_prompt_has_career_kinds_card_and_identity(monkeypatch):
    monkeypatch.setattr(graph.config, "me", lambda: {"name": "Jane Tan", "aliases": ["JT"]})
    p = graph._prompt("text", {"file_name": "x.pptx", "metadata": {"file_type": "pptx", "want_card": True}}, True)
    assert "contribution  =" in p and "outcome       =" in p and "lesson        =" in p
    assert '"card": {' in p and "doc_type" in p and "proposal|" in p
    assert "The vault owner is Jane Tan (aliases: JT)" in p
    p2 = graph._prompt("text", {"file_name": "x.pptx", "metadata": {"file_type": "pptx"}}, True)
    assert '"card": {' not in p2


def test_prompt_without_identity(monkeypatch):
    monkeypatch.setattr(graph.config, "me", lambda: {})
    assert "vault owner" not in graph._prompt("t", {"file_name": "a.md", "metadata": {}}, False)


def test_normalize_facts_maps_career_aliases():
    out = graph.normalize_facts([{"kind": "achievement", "statement": "Won the deal"},
                                 {"kind": "lessons_learned", "statement": "Start UAT earlier"},
                                 {"kind": "contribution", "statement": "Led the team", "owner": "I"}])
    assert [f["kind"] for f in out] == ["outcome", "lesson", "contribution"]
    assert out[2]["owner"] == "I"


def test_normalize_extraction_returns_card():
    out = graph._normalize_extraction({"entities": [], "card": {"title": "x"}})
    assert out["card"] == {"title": "x"}
    assert graph._normalize_extraction({"card": "nope"})["card"] == {}


def test_extract_document_retries_truncated_and_unparseable_as_halves(monkeypatch):
    calls = []

    def fake(chunk, include_relationships=True, max_chars=0):
        calls.append(len(chunk["content"]))
        if len(chunk["content"]) > 4000:
            raise graph.TruncatedOutput("length")
        return {"entities": [], "relationships": [], "facts": [{"kind": "decision", "statement": f"d{len(calls)}"}],
                "card": {"summary": f"s{len(calls)}"}}
    monkeypatch.setattr(graph, "extract_chunk", fake)
    out = graph.extract_document({"content": "x" * 7000, "file_name": "a.md"}, window_chars=8000, max_windows=1)
    assert calls[0] == 7000 and len(calls) == 3           # one failed big call, two halves
    assert out["windows"] == 1 and len(out["facts"]) == 2
    assert out["card"]["summary"].startswith("[1/2]")

    calls.clear()
    def bad_json(chunk, include_relationships=True, max_chars=0):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("unparseable JSON")
        return {"entities": [], "relationships": [], "facts": []}
    monkeypatch.setattr(graph, "extract_chunk", bad_json)
    graph.extract_document({"content": "y" * 5000, "file_name": "b.md"}, window_chars=8000, max_windows=1)
    assert len(calls) == 3


def test_extract_document_sets_want_card(monkeypatch):
    seen = {}
    def fake(chunk, include_relationships=True, max_chars=0):
        seen.update(chunk["metadata"])
        return {"entities": [], "relationships": [], "facts": []}
    monkeypatch.setattr(graph, "extract_chunk", fake)
    graph.extract_document({"content": "abc", "file_name": "a.md", "file_type": "md"})
    assert seen["want_card"] is True and seen["file_type"] == "md"
