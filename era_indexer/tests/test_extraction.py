"""Unit tests for document-level extraction helpers (no DB / no LLM).

Run from era_indexer/: `python -m pytest tests/test_extraction.py`.
"""
import json

import pytest

from career_history import graph


def test_repair_json_fixes_bad_escapes_and_trailing_commas():
    raw = '{"entities": [{"name": "C:\\Users\\era", "type": "concept"},], }'
    parsed = graph._loads_json_object(raw)
    assert parsed["entities"][0]["name"] == "C:\\Users\\era"


def test_loads_json_object_strips_prose_around_json():
    parsed = graph._loads_json_object('Sure! {"entities": [], "facts": []} done')
    assert parsed == {"entities": [], "facts": []}


def test_loads_json_object_rejects_non_object():
    with pytest.raises(ValueError):
        graph._loads_json_object("[1, 2, 3]")


def test_strict_loader_does_not_salvage_truncated_json():
    raw = '{"entities": [{"name": "IBF", "type": "project"}, {"name": "cut'
    with pytest.raises(json.JSONDecodeError):
        graph._loads_json_object(raw)


def test_salvage_drops_the_unfinished_element():
    raw = (
        '{"entities": ['
        + ",".join(
            '{"name": "E%d", "type": "project", "confidence": 0.8}' % i
            for i in range(40)
        )
        + ', {"name": "CUT", "type": "proj'
    )
    parsed, salvaged = graph.loads_extraction_json(raw)
    assert salvaged is True
    assert len(parsed["entities"]) == 40
    assert all(row["name"] != "CUT" for row in parsed["entities"])
    assert len(raw) > 2000


def test_salvage_closes_a_finished_field_whose_object_was_cut():
    raw = '{"entities": [{"name": "IBF", "type": "project"'
    parsed, salvaged = graph.loads_extraction_json(raw)
    assert salvaged is True
    assert parsed["entities"] == [{"name": "IBF", "type": "project"}]


def test_salvage_drops_a_cut_off_field_and_keeps_the_earlier_one():
    raw = '{"entities": [{"name": "IBF", "type": "proj'
    parsed, salvaged = graph.loads_extraction_json(raw)
    assert salvaged is True
    assert parsed["entities"] == [{"name": "IBF"}]


def test_salvage_repairs_escapes_before_closing():
    raw = '{"entities": [{"name": "C:\\Users\\era", "type": "concept"}, {"name": "cut'
    parsed, salvaged = graph.loads_extraction_json(raw)
    assert salvaged is True
    assert parsed["entities"][0]["name"] == "C:\\Users\\era"


def test_split_windows_covers_text_and_respects_cap():
    text = ("Paragraph one. " * 50 + "\n\n") * 10
    windows = graph.split_windows(text, 2000, 3)
    assert 1 < len(windows) <= 3
    assert all(len(w) <= 2000 for w in windows)
    assert graph.split_windows("", 2000, 3) == []


def test_split_windows_returns_all_text_when_under_cap():
    text = "a" * 5000
    windows = graph.split_windows(text, 2000, 10)
    assert "".join(windows) == text


def test_merge_extractions_dedupes_across_windows():
    a = {"entities": [{"name": "IBF", "type": "project", "confidence": 0.5, "aliases": ["01_IBF"]}],
         "relationships": [{"source": "Ron", "type": "OWNS", "target": "IBF"}],
         "facts": [{"kind": "decision", "statement": "Use Gemini"}]}
    b = {"entities": [{"name": "ibf", "type": "project", "confidence": 0.9, "aliases": ["IBF Programme"]}],
         "relationships": [{"source": "ron", "type": "owns", "target": "ibf"}],
         "facts": [{"kind": "decision", "statement": "use gemini"},
                   {"kind": "risk", "statement": "GCC unconfirmed"}]}
    merged = graph.merge_extractions([a, b])
    assert len(merged["entities"]) == 1
    assert merged["entities"][0]["confidence"] == 0.9
    assert set(merged["entities"][0]["aliases"]) == {"01_IBF", "IBF Programme"}
    assert len(merged["relationships"]) == 1
    assert len(merged["facts"]) == 2


def test_extract_document_retries_timed_out_window_as_halves(monkeypatch):
    calls = []

    def fake_extract(chunk, include_relationships=True, max_chars=0):
        calls.append(len(chunk["content"]))
        if len(chunk["content"]) > 3000:
            raise TimeoutError("timed out")
        return {"entities": [{"name": f"E{len(calls)}", "type": "concept"}],
                "relationships": [], "facts": []}

    monkeypatch.setattr(graph, "extract_chunk", fake_extract)
    doc = {"content": "word. " * 1000, "file_name": "x.pdf", "folder": "f"}
    out = graph.extract_document(doc, window_chars=6000, max_windows=1)
    assert len(out["entities"]) == 2
    assert calls[0] > 3000 and all(c <= 3000 for c in calls[1:])


def test_extract_document_resplits_truncated_json_and_prefers_halves(monkeypatch):
    calls = []

    def fake_extract(chunk, include_relationships=True, max_chars=0):
        calls.append(len(chunk["content"]))
        if len(chunk["content"]) > 3000:
            raise graph.TruncatedOutput(
                "extraction JSON was truncated",
                partial={"entities": [{"name": "Parent", "type": "project"}],
                         "relationships": [], "facts": []},
            )
        return {"entities": [{"name": f"Half{len(calls)}", "type": "project"}],
                "relationships": [], "facts": []}

    monkeypatch.setattr(graph, "extract_chunk", fake_extract)
    doc = {"content": "word. " * 1000, "file_name": "deck.pptx", "folder": "f"}
    out = graph.extract_document(doc, window_chars=6000, max_windows=1)
    assert [row["name"] for row in out["entities"]] == ["Half2", "Half3"]
    assert calls[0] > 3000


def test_extract_document_keeps_salvaged_prefix_when_halves_fail(monkeypatch):
    def fake_extract(chunk, include_relationships=True, max_chars=0):
        if len(chunk["content"]) > 3000:
            raise graph.TruncatedOutput(
                "extraction JSON was truncated",
                partial={"entities": [{"name": "Kept", "type": "project"}],
                         "relationships": [], "facts": []},
            )
        raise RuntimeError("Ollama request failed: connection refused")

    monkeypatch.setattr(graph, "extract_chunk", fake_extract)
    doc = {"content": "word. " * 1000, "file_name": "deck.pptx", "folder": "f"}
    out = graph.extract_document(doc, window_chars=6000, max_windows=1)
    assert [row["name"] for row in out["entities"]] == ["Kept"]


def test_transient_db_error_matches_the_address_failure():
    exc = Exception(
        "(psycopg2.DatabaseError) could not receive data from server: "
        "Can't assign requested address"
    )
    assert graph._is_transient_db_error(exc)
    assert not graph._is_transient_db_error(json.JSONDecodeError("Expecting ',' delimiter", "{}", 0))
