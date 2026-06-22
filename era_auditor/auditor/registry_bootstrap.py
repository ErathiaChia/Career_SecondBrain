"""Generate (and optionally apply) registry patches from the scanned tree.

The auditor derives customer and project registry candidates from classified
folders instead of requiring hand-maintained YAML. A reviewable patch file is
written to the reports directory; --apply merges it into the rule YAML files.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import AppConfig, resolve_report_directory
from .constitution import FolderConstitution, normalize_code
from .db import AuditorDatabase
from .models import FolderRecord
from .template_diff import build_children_by_parent, parse_stage_name


class RegistryBootstrapper:
    def __init__(self, config: AppConfig, database: AuditorDatabase):
        self.config = config
        self.database = database
        self.constitution = FolderConstitution(config)
        self.rules_dir = config.base_dir / "auditor" / "rules"

    # ------------------------------------------------------------------
    # Patch generation
    # ------------------------------------------------------------------

    def build_patch(self) -> dict[str, Any]:
        folders = self.database.active_folders()
        classifications = self.database.latest_classifications()
        children_by_parent = build_children_by_parent(folders)

        known_customers = {
            normalize_code(code)
            for code in self.constitution.customer_registry.get("customers", {})
        }
        known_project_paths = set(self.constitution.projects_by_path)

        customers: dict[str, dict[str, Any]] = {}
        projects: list[dict[str, Any]] = []

        for folder in folders:
            classification = classifications.get(folder.id)
            if classification is None or classification.folder_type != "customer":
                continue
            code = classification.customer_code or folder.name
            normalized = normalize_code(code)
            if normalized in known_customers or normalized in customers:
                continue
            customers[normalized] = {
                "full_name": classification.customer_name or _humanize(folder.name),
                "industry": None,
                "country": None,
                "source_folder": folder.path,
            }

            if folder.path in known_project_paths:
                continue
            parts = folder.path.split("/")
            year = next((int(p) for p in parts if p.isdigit() and len(p) == 4), None)
            lifecycle = self._infer_lifecycle(folder.path, children_by_parent)
            child_names = [
                child.rsplit("/", 1)[-1]
                for child in children_by_parent.get(folder.path, [])
            ]
            initiative_type = self.constitution.infer_initiative_type(
                folder.name, child_names
            )
            projects.append(
                {
                    "project_id": _project_id(year, normalized),
                    "customer_code": normalized,
                    "customer_name": classification.customer_name or _humanize(folder.name),
                    "initiative_name": None,
                    "status": "active",
                    "lifecycle": lifecycle,
                    "initiative_type": initiative_type,
                    "year": year,
                    "folder_path": folder.path,
                    "tags": [],
                    "last_updated": datetime.now(timezone.utc).date().isoformat(),
                }
            )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "customers": customers,
            "projects": projects,
        }

    def _infer_lifecycle(
        self,
        path: str,
        children_by_parent: dict[str | None, list[str]],
    ) -> str:
        stack = [path]
        while stack:
            current = stack.pop()
            for child_path in children_by_parent.get(current, []):
                name = child_path.rsplit("/", 1)[-1]
                parsed = parse_stage_name(name)
                if parsed and parsed.indices:
                    return "active_presales"
                if parsed:
                    stack.append(child_path)
        return "lead"

    # ------------------------------------------------------------------
    # Patch I/O
    # ------------------------------------------------------------------

    def write_patch(self, patch: dict[str, Any]) -> Path:
        report_dir = resolve_report_directory(self.config)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = report_dir / f"registry_patch_{timestamp}.yaml"
        path.write_text(
            yaml.safe_dump(patch, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    def apply_patch(self, patch: dict[str, Any]) -> dict[str, int]:
        customer_path = self.rules_dir / "customer_registry.yaml"
        project_path = self.rules_dir / "project_registry.yaml"

        customer_data = yaml.safe_load(customer_path.read_text(encoding="utf-8")) or {}
        customer_data.setdefault("customers", {})
        added_customers = 0
        for code, entry in (patch.get("customers") or {}).items():
            if code in customer_data["customers"]:
                continue
            customer_data["customers"][code] = {
                key: value
                for key, value in entry.items()
                if key != "source_folder" and value is not None
            }
            added_customers += 1

        project_data = yaml.safe_load(project_path.read_text(encoding="utf-8")) or {}
        project_data.setdefault("projects", [])
        existing_paths = {
            project.get("folder_path") for project in project_data["projects"]
        }
        added_projects = 0
        for project in patch.get("projects") or []:
            if project.get("folder_path") in existing_paths:
                continue
            project_data["projects"].append(
                {key: value for key, value in project.items() if value is not None}
            )
            added_projects += 1

        if added_customers:
            customer_path.write_text(
                yaml.safe_dump(customer_data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
        if added_projects:
            project_path.write_text(
                yaml.safe_dump(project_data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

        # Keep the database registry tables in sync with the YAML files.
        if added_customers or added_projects:
            self.database.sync_registries_from_yaml()

        return {"customers": added_customers, "projects": added_projects}


def load_patch(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _humanize(name: str) -> str:
    import re

    value = re.sub(r"^[0-9]{2}[_ -]", "", name)
    return value.replace("_", " ").strip()


def _project_id(year: int | None, customer_code: str) -> str:
    prefix = str(year) if year else "XXXX"
    return f"{prefix}-{customer_code.replace('_', '-')}"
