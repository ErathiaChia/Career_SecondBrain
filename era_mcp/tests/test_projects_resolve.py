from era_mcp import projects

PROJECTS = [
    {"name": "CPX - AI Use Case", "project_key": "2026-IBF-CPX-AI-USECASE",
     "client": "Institute of Banking and Finance", "status": "ACTIVE", "aliases": []},
    {"name": "AI Proposal", "project_key": "2026-HC3-AI-PROPOSAL",
     "client": "TTSH", "status": "ACTIVE", "aliases": None},
    {"name": "AI Staff Training", "project_key": "2026-IBF-AI-STAFF-TRAINING",
     "client": "Institute of Banking and Finance", "status": "ACTIVE", "aliases": ["IBF training"]},
    {"name": "Eye Clinic AI", "project_key": "2026-TTSH-EYE-CLINIC",
     "client": "Tan Tock Seng Hospital - Eye Clinic", "status": "ACTIVE",
     "aliases": ["12_TTSH - Eye Clinic", "TTSH - Eye Clinic"]},
    {"name": "Nurse Scheduling", "project_key": "2026-TTSH-NURSE-SCHEDULING",
     "client": "Tan Tock Seng Hospital", "status": "ACTIVE", "aliases": []},
]


def _patch(monkeypatch):
    monkeypatch.setattr(projects, "list_projects", lambda: PROJECTS)


def test_token_fallback_ignores_punctuation(monkeypatch):
    _patch(monkeypatch)
    assert projects._resolve_by_tokens("CPX AI Use Case")["project_key"] == "2026-IBF-CPX-AI-USECASE"


def test_token_fallback_uses_key_client_and_aliases(monkeypatch):
    _patch(monkeypatch)
    assert projects._resolve_by_tokens("HC3 AI proposal")["project_key"] == "2026-HC3-AI-PROPOSAL"
    assert projects._resolve_by_tokens("IBF training")["project_key"] == "2026-IBF-AI-STAFF-TRAINING"


def test_token_fallback_tolerates_one_wrong_word(monkeypatch):
    _patch(monkeypatch)
    assert projects._resolve_by_tokens("TTSH eye center")["project_key"] == "2026-TTSH-EYE-CLINIC"
    assert projects._resolve_by_tokens("TTSH nurse rostering")["project_key"] == "2026-TTSH-NURSE-SCHEDULING"


def test_coverage_note_flags_unextracted_projects(monkeypatch):
    import pytest
    pytest.importorskip("fastapi")
    from era_mcp import project_routes
    p = {"id": 1, "name": "AI Architecture", "client": "HSA"}

    monkeypatch.setattr(projects, "fact_coverage", lambda _id: {"files": 83, "files_with_facts": 0, "facts": 0})
    out = project_routes._coverage(p)
    assert "UNKNOWN, not 'nothing open'" in out["note"]
    assert project_routes._with_note("## Next actions", out).startswith("> **Coverage:**")

    monkeypatch.setattr(projects, "fact_coverage", lambda _id: {"files": 41, "files_with_facts": 27, "facts": 124})
    out = project_routes._coverage(p)
    assert "note" not in out
    assert project_routes._with_note("## Next actions", out) == "## Next actions"


def test_token_fallback_requires_most_tokens(monkeypatch):
    _patch(monkeypatch)
    assert projects._resolve_by_tokens("CPX hospital rostering") is None
    assert projects._resolve_by_tokens(" - ") is None
