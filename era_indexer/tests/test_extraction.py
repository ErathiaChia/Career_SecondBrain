"""Unit tests for document-level extraction helpers (no DB / no LLM).

Run from era_indexer/: `python -m pytest tests/test_extraction.py`.
"""
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
    a = {"entities": [{"name": "CL89", "type": "project", "confidence": 0.5, "aliases": ["01_CL89"]}],
         "relationships": [{"source": "Ron", "type": "OWNS", "target": "CL89"}],
         "facts": [{"kind": "decision", "statement": "Use Gemini"}]}
    b = {"entities": [{"name": "cl89", "type": "project", "confidence": 0.9, "aliases": ["CL89 Programme"]}],
         "relationships": [{"source": "ron", "type": "owns", "target": "cl89"}],
         "facts": [{"kind": "decision", "statement": "use gemini"},
                   {"kind": "risk", "statement": "GCC unconfirmed"}]}
    merged = graph.merge_extractions([a, b])
    assert len(merged["entities"]) == 1
    assert merged["entities"][0]["confidence"] == 0.9
    assert set(merged["entities"][0]["aliases"]) == {"01_CL89", "CL89 Programme"}
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
