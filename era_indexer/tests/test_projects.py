from datetime import datetime, timedelta

from career_history import projects

NOW = datetime(2026, 10, 5)


def _file(fid, path, name=None, days_ago=10):
    return {"file_id": fid, "file_path": path, "file_name": name or path.rsplit("/", 1)[-1],
            "last_modified_at": NOW - timedelta(days=days_ago)}


def test_longest_fragment_wins_between_manifest_and_seed():
    manifest = projects.candidates_from_manifest([{
        "path": "01 Project/2026/01_IBF/1 AI Staff Training", "name": "AI Staff Training",
        "project_key": "2026-IBF-AI", "customer_name": "IBF", "lifecycle": "active_presales",
    }])
    files = [
        _file(1, "/V/14. ST-Engg/01 Project/2026/01_IBF/1 AI Staff Training/rfp.pdf"),
        _file(2, "/V/14. ST-Engg/01 Project/2026/01_IBF/notes.md"),
        _file(3, "/V/14. ST-Engg/01 Project/2026/16_HC3/a/deck.pptx"),
        _file(4, "/V/14. ST-Engg/02 Ops/x.md"),
    ]
    seed = projects.candidates_from_seed([f["file_path"] for f in files], ["/01 Project/2026/"])
    assigned = projects.assign_files(files, manifest + seed)
    assert [f["file_id"] for f in assigned["2026-IBF-AI"]] == [1]
    assert [f["file_id"] for f in assigned["path:01 Project/2026/01_IBF"]] == [2]
    assert [f["file_id"] for f in assigned["path:01 Project/2026/16_HC3"]] == [3]
    assert all(4 not in [f["file_id"] for f in v] for v in assigned.values())


def test_seed_candidate_names_strip_numeric_prefix():
    seed = projects.candidates_from_seed(["/V/01 Project/2026/16_HC3/a.md"], ["/01 Project/2026/"])
    assert seed[0].name == "HC3"
    assert "16_HC3" in seed[0].aliases


def test_build_project_prefers_manifest_fields():
    cand = projects.candidates_from_manifest([{
        "path": "01 Project/2026/02_HLB", "name": "HLB Credit AI", "project_key": "HLB-1",
        "customer_name": "Hong Leong Bank", "initiative_type": "poc", "status": "active",
        "lifecycle": "active_presales", "metadata": {"owner": "Era"},
    }])[0]
    p = projects.build_project(cand, [_file(1, "/x/01 Project/2026/02_HLB/a.pdf", days_ago=400)], NOW)
    assert p["client"] == "Hong Leong Bank"
    assert p["project_type"] == "poc"
    assert p["status"] == "ACTIVE"  # manifest beats recency
    assert p["owner"] == "Era"
    assert p["field_sources"]["client"]["source"] == "manifest"
    assert p["confidence"] > 0.9


def test_build_project_infers_from_filenames_and_recency():
    cand = projects.candidates_from_seed(["/v/01 Project/2026/05_Acc/x.docx"], ["/01 Project/2026/"])[0]
    files = [
        _file(1, "/v/01 Project/2026/05_Acc/a.docx", "VTJ_Accrete_AIS_Voice_Proposal_v1.0.docx", 200),
        _file(2, "/v/01 Project/2026/05_Acc/b.docx", "VTJ_Accrete_AIS_Voice_Proposal_v2.0.docx", 150),
    ]
    p = projects.build_project(cand, files, NOW)
    assert p["client"] == "Accrete"
    assert p["project_type"] == "sales_opportunity"
    assert p["status"] == "DORMANT"
    assert p["field_sources"]["status"]["source"] == "recency"
    assert p["file_count"] == 2


def test_manifest_status_mapping():
    assert projects.manifest_status({"lifecycle": "archived"}) == "ARCHIVED"
    assert projects.manifest_status({"status": "on_hold"}) == "DORMANT"
    assert projects.manifest_status({"lifecycle": "lead"}) == "ACTIVE"
    assert projects.manifest_status({}) is None
