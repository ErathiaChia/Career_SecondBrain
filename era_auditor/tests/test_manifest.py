import json

from auditor.manifest import manifest_rows


def test_manifest_rows_maps_registry_and_adds_customer_parent():
    rows = manifest_rows([
        {
            "project_id": "2026-CL89-AI-STAFF-TRAINING",
            "folder_path": "01 Project/2026/01_CL89/1 Acme50 Orion Vega",
            "customer_code": "CL89",
            "customer_name": "Acme10 Orion Vega",
            "initiative_name": "Acme50 Orion Vega",
            "status": "active",
            "initiative_type": "sales_opportunity",
            "year": 2026,
            "tags": ["training"],
            "metadata": {"lifecycle": "active_presales", "owner": "Era"},
        },
        {"project_id": "x", "folder_path": ""},
    ])
    by_path = {r["path"]: r for r in rows}
    project = by_path["01 Project/2026/01_CL89/1 Acme50 Orion Vega"]
    assert project["kind"] == "project"
    assert project["project_key"] == "2026-CL89-AI-STAFF-TRAINING"
    assert project["lifecycle"] == "active_presales"
    assert json.loads(project["metadata"]) == {"owner": "Era"}
    customer = by_path["01 Project/2026/01_CL89"]
    assert customer["kind"] == "customer"
    assert customer["customer_code"] == "CL89"
    assert len(rows) == 2
