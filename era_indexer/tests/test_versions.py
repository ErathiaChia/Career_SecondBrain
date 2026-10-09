from datetime import datetime

from career_history import versions


def test_family_key_strips_versions_and_affixes():
    k = versions.family_key
    assert k("Architecture_v1.pptx") == k("Architecture_v3.pptx") == "architecture"
    assert k("V3_Genie_Studio_NCTS-SAP_Workshop.pdf") == k("V1_Genie_Studio_NCTS-SAP_Workshop.pdf")
    assert k("Proposal_v1.1_FINAL.docx") == k("Proposal_v2_draft.docx")
    assert k("260003-250024 VTJ_Accrete_Proposal_v1.0.docx") == "vtj accrete proposal"
    assert k("Deck (1).pptx") == k("Deck.pptx")
    assert k("Deck_Page6.pptx") == k("Deck_Page8.pptx")


def test_family_key_keeps_dates_so_daily_notes_stay_distinct():
    assert versions.family_key("20250621_ToDo.md") != versions.family_key("20250625_ToDo.md")


def test_family_key_does_not_eat_words_that_start_with_v():
    assert versions.family_key("Voice_Authentication.docx") == "voice authentication"
    assert versions.family_key("Review_Notes.docx") == "review notes"


def test_parse_version_and_label():
    assert versions.parse_version("Arch_v2.10.pptx") == (2, 10)
    assert versions.parse_version("Arch_rev3.pptx") == (3,)
    assert versions.parse_version("Arch.pptx") is None
    assert versions.version_label("Proposal_v1.1.docx") == "v1.1"


def _f(fid, name, mtime, scope="P1", ftype="pptx"):
    return {"file_id": fid, "file_name": name, "file_path": f"/x/{scope}/{name}",
            "file_type": ftype, "last_modified_at": mtime, "project_key": scope, "project_id": 1}


def test_build_chains_orders_by_version_and_links_previous():
    rows = versions.build_chains([
        _f(3, "Architecture_v3.pptx", datetime(2026, 9, 1)),
        _f(1, "Architecture_v1.pptx", datetime(2026, 9, 20)),  # touched later, still v1
        _f(2, "Architecture_v2.pptx", datetime(2026, 9, 10)),
        _f(9, "Architecture_v1.pdf", datetime(2026, 9, 1), ftype="pdf"),
    ])
    chain = sorted((r for r in rows if r["family_size"] == 3), key=lambda r: r["version_rank"])
    assert [r["file_id"] for r in chain] == [1, 2, 3]
    assert chain[1]["previous_file_id"] == 1 and chain[2]["previous_file_id"] == 2
    assert [r["is_latest"] for r in chain] == [False, False, True]
    pdf = next(r for r in rows if r["file_id"] == 9)
    assert pdf["family_size"] == 1 and pdf["is_latest"]


def test_build_chains_falls_back_to_mtime_without_version_numbers():
    rows = versions.build_chains([
        _f(1, "Proposal_draft.docx", datetime(2026, 9, 1), ftype="docx"),
        _f(2, "Proposal_final.docx", datetime(2026, 9, 5), ftype="docx"),
    ])
    latest = next(r for r in rows if r["is_latest"])
    assert latest["file_id"] == 2


def test_new_latest_versions_only_reports_new_heads():
    rows = versions.build_chains([
        _f(1, "Arch_v1.pptx", datetime(2026, 9, 1)),
        _f(2, "Arch_v2.pptx", datetime(2026, 9, 2)),
    ])
    existing_first_run = {1: {"is_latest": True, "family_size": 1}}
    assert [r["file_id"] for r in versions.new_latest_versions(rows, existing_first_run)] == [2]
    existing_same = {1: {"is_latest": False, "family_size": 2}, 2: {"is_latest": True, "family_size": 2}}
    assert versions.new_latest_versions(rows, existing_same) == []
