from era_mcp import projects

PROJECTS = [
    {"name": "CL89 CPX AI Use Case", "project_key": "2026-CL89-CPX-AI-USECASE",
     "client": "Acme10 Orion Vega", "status": "ACTIVE", "aliases": []},
    {"name": "Delta67 Sigma", "project_key": "2026-CL91-AI-PROPOSAL",
     "client": "CL87", "status": "ACTIVE", "aliases": None},
    {"name": "Acme50 Orion Vega", "project_key": "2026-CL89-AI-STAFF-TRAINING",
     "client": "Acme10 Orion Vega", "status": "ACTIVE", "aliases": ["CL89 training"]},
    {"name": "Nova64 Zenith Atlas", "project_key": "2026-CL87-EYE-CLINIC",
     "client": "Delta7 Sigma Rho", "status": "ACTIVE",
     "aliases": ["12_CL87 - Eye Clinic", "CL87 - Eye Clinic"]},
    {"name": "Lyra53 Nova", "project_key": "2026-CL87-NURSE-SCHEDULING",
     "client": "Atlas36 Delta Sigma", "status": "ACTIVE", "aliases": []},
]


def _patch(monkeypatch):
    monkeypatch.setattr(projects, "list_projects", lambda: PROJECTS)


def test_token_fallback_ignores_punctuation(monkeypatch):
    _patch(monkeypatch)
    assert projects._resolve_by_tokens("CPX AI Use Case")["project_key"] == "2026-CL89-CPX-AI-USECASE"


def test_token_fallback_uses_key_client_and_aliases(monkeypatch):
    _patch(monkeypatch)
    assert projects._resolve_by_tokens("CL91 AI proposal")["project_key"] == "2026-CL91-AI-PROPOSAL"
    assert projects._resolve_by_tokens("CL89 training")["project_key"] == "2026-CL89-AI-STAFF-TRAINING"


def test_token_fallback_tolerates_one_wrong_word(monkeypatch):
    _patch(monkeypatch)
    assert projects._resolve_by_tokens("CL87 eye center")["project_key"] == "2026-CL87-EYE-CLINIC"
    assert projects._resolve_by_tokens("CL87 nurse rostering")["project_key"] == "2026-CL87-NURSE-SCHEDULING"


def test_coverage_note_flags_unextracted_projects(monkeypatch):
    import pytest
    pytest.importorskip("fastapi")
    from era_mcp import project_routes
    p = {"id": 1, "name": "Delta57 Sigma", "client": "CL92"}

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
