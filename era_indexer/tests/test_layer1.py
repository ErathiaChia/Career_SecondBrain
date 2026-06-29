"""Unit tests for Layer 1 pure helpers (no DB / no LLM).

Covers the deterministic-seeding path logic and the fact-extraction helpers in
graph.py. Run from era_indexer/: `python -m pytest tests/test_layer1.py`.
"""
from career_history import graph, seed_entities


def test_segment_after_picks_project_folder():
    root = "/01 Project/2026/"
    assert seed_entities._segment_after(
        "/Vol/14. ST-Engg/01 Project/2026/01_IBF/A.1/rfp.pdf", root) == "01_IBF"
    assert seed_entities._segment_after(
        "/Vol/14. ST-Engg/01 Project/2026/16_HC3/readme.md", root) == "16_HC3"


def test_segment_after_skips_loose_files_and_non_matches():
    root = "/01 Project/2026/"
    # A file directly under the root (no further folder) is not a project.
    assert seed_entities._segment_after("/Vol/14. ST-Engg/01 Project/2026/loose.md", root) is None
    # A path that does not contain the root at all.
    assert seed_entities._segment_after("/Vol/14. ST-Engg/02 Ops/x.md", root) is None


def test_aliases_strip_numeric_prefix():
    assert "IBF" in seed_entities._aliases("01_IBF")
    assert "01_IBF" in seed_entities._aliases("01_IBF")
    assert "HC3" in seed_entities._aliases("16_HC3")
    assert seed_entities._aliases("UOB") == ["UOB"]  # nothing to strip


def test_resolve_fact_entity_matches_by_name_and_type():
    ids = {("ibf", "project"): 5, ("ron", "person"): 7}
    assert graph._resolve_fact_entity("IBF", "project", ids) == 5
    assert graph._resolve_fact_entity("Ron", None, ids) == 7      # type-agnostic fallback
    assert graph._resolve_fact_entity("Unknown", None, ids) is None
    assert graph._resolve_fact_entity("", None, ids) is None


def test_clean_ts_extracts_iso_date_or_none():
    assert graph._clean_ts("due 2026-07-05, urgent") == "2026-07-05"
    assert graph._clean_ts("next week") is None
    assert graph._clean_ts(None) is None
