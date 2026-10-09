import json

from auditor.manifest import manifest_rows


def test_manifest_rows_maps_registry_and_adds_customer_parent():
    rows = manifest_rows([
        {
            "project_id": "2026-IBF-AI-STAFF-TRAINING",
            "folder_path": "01 Project/2026/01_IBF/1 AI Staff Training",
            "customer_code": "IBF",
            "customer_name": "Institute of Banking and Finance",
            "initiative_name": "AI Staff Training",
            "status": "active",
            "initiative_type": "sales_opportunity",
            "year": 2026,
            "tags": ["training"],
            "metadata": {"lifecycle": "active_presales", "owner": "Era"},
        },
        {"project_id": "x", "folder_path": ""},
    ])
    by_path = {r["path"]: r for r in rows}
    project = by_path["01 Project/2026/01_IBF/1 AI Staff Training"]
    assert project["kind"] == "project"
    assert project["project_key"] == "2026-IBF-AI-STAFF-TRAINING"
    assert project["lifecycle"] == "active_presales"
    assert json.loads(project["metadata"]) == {"owner": "Era"}
    customer = by_path["01 Project/2026/01_IBF"]
    assert customer["kind"] == "customer"
    assert customer["customer_code"] == "IBF"
    assert len(rows) == 2
