from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from .config import AppConfig
from .models import FolderClassification, FolderRecord
from .template_diff import parse_stage_name


YEAR_PATTERN = re.compile(r"^20[0-9]{2}$")
CODE_PREFIX_PATTERN = re.compile(r"^[0-9]{2}[_ -](?P<code>[A-Za-z0-9_-]+)$")
# Month-name folders like 01_Jan, 10Oct, 202601_Jan, 202510_Oct, 09Sept, 05May.
# Optional 4-digit year prefix, 1-2 digit month index, separator, month word.
MONTH_NAME_PATTERN = re.compile(
    r"^(20[0-9]{2})?[_ -]?(0?[1-9]|1[0-2])[_ -]?"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*$",
    re.IGNORECASE,
)


class FolderConstitution:
    def __init__(self, config: AppConfig):
        self.config = config
        self.rules_dir = config.base_dir / "auditor" / "rules"
        self.organization_rules = self._load_yaml("organization_rules.yaml")
        self.project_templates = self._load_yaml("project_templates.yaml")
        self.customer_registry = self._load_yaml("customer_registry.yaml")
        self.project_registry = self._load_yaml("project_registry.yaml")
        self.decision_history = self._load_yaml("decision_history.yaml")
        self.allowed_empty_folders = self._load_yaml("allowed_empty_folders.yaml")
        self.naming_standards = self._load_yaml("naming_standards.yaml")
        self.initiative_types = self._load_yaml("initiative_types.yaml")
        self.stage_lookup = self._build_stage_lookup()
        self.projects_by_path = {
            project.get("folder_path"): project
            for project in self.project_registry.get("projects", [])
            if project.get("folder_path")
        }

    def as_prompt_payload(self) -> dict[str, Any]:
        return {
            "organization_rules": self.organization_rules,
            "project_templates": self.project_templates,
            "customer_registry": self.customer_registry,
            "project_registry": self.project_registry,
            "decision_history": self.decision_history,
            "allowed_empty_folders": self.allowed_empty_folders,
            "naming_standards": self.naming_standards,
            "initiative_types": self.initiative_types,
        }

    def classify_deterministic(self, folder: FolderRecord) -> FolderClassification | None:
        path = folder.path
        name = folder.name
        parts = [] if path == "." else path.split("/")
        root_category = parts[0] if parts else "."

        if path == ".":
            return FolderClassification(
                folder_type="root",
                root_category=".",
                matched_rule="workspace_root",
                confidence=1.0,
                reasoning="Workspace scan root is structural and should not be audited as content.",
            )

        if folder.metadata_signals.get("is_code_repo"):
            return FolderClassification(
                folder_type="code_repo",
                root_category=root_category,
                matched_rule="code_repo:markers",
                classification_source="constitution",
                classification_role="code_repo",
                confidence_reason="Folder contains code repository markers and is treated as an opaque leaf.",
                confidence=1.0,
                reasoning="Folder is a code repository; its internals are working files, not knowledge folders.",
            )

        empty_match = self.allowed_empty_match(path)
        if empty_match and empty_match.get("type") == "inbox":
            return FolderClassification(
                folder_type="inbox",
                root_category=root_category,
                is_intentional_empty=True,
                matched_rule=f"allowed_empty:{path}",
                confidence=1.0,
                reasoning=empty_match.get("reason", "Folder is an intentional staging area."),
            )

        top_level_rule = self.top_level_rule(path)
        if top_level_rule:
            return FolderClassification(
                folder_type=top_level_rule.get("type", "root"),
                root_category=name,
                is_intentional_empty=bool(top_level_rule.get("may_be_empty", False)),
                matched_rule=f"top_level:{name}",
                classification_source="constitution",
                classification_role=top_level_rule.get("type", "root"),
                confidence_reason="Exact top-level folder rule matched.",
                confidence=1.0,
                reasoning=top_level_rule.get("purpose", "Known top-level structural folder."),
            )

        project_match = self.project_match(path)
        if project_match:
            return FolderClassification(
                folder_type="initiative",
                customer=project_match.get("customer_name"),
                initiative=project_match.get("initiative_name"),
                initiative_type=project_match.get("initiative_type"),
                root_category=root_category,
                customer_code=project_match.get("customer_code"),
                customer_name=project_match.get("customer_name"),
                registry_project_id=project_match.get("project_id"),
                registry_customer_id=project_match.get("customer_code"),
                classification_source="project_registry",
                classification_role="initiative",
                template_status="registered_project",
                matched_rule=f"project_registry:{project_match.get('project_id')}",
                confidence_reason="Folder path exactly matched the Project Registry.",
                confidence=1.0,
                reasoning="Folder is a registered project/initiative.",
            )

        if self.is_temporal(name):
            return FolderClassification(
                folder_type="temporal",
                root_category=root_category,
                matched_rule="temporal:year",
                classification_source="constitution",
                classification_role="temporal",
                confidence_reason="Folder name matches temporal year rule.",
                confidence=1.0,
                reasoning="Year folder is a temporal partition, not duplicate content.",
            )

        if name.lower() in {"archive", "archives", "old"}:
            return FolderClassification(
                folder_type="archive",
                root_category=root_category,
                matched_rule="archive:name",
                classification_source="constitution",
                classification_role="archive",
                confidence_reason="Folder name is an archive convention.",
                confidence=0.95,
                reasoning="Folder name indicates archive or old material.",
            )

        stage = self.stage_name(name)
        if stage:
            return FolderClassification(
                folder_type="stage",
                root_category=root_category,
                stage=stage,
                template_status="matches_stage_standard",
                matched_rule=f"stage:{stage}",
                classification_source="template",
                classification_role="stage",
                confidence_reason="Folder matched accepted stage naming standards.",
                confidence=0.98,
                reasoning="Folder matches a known project stage or artifact naming standard.",
            )

        customer_code = self.customer_code(name)
        if customer_code:
            known_customer = self.known_customer(customer_code)
            if known_customer:
                return FolderClassification(
                    folder_type="customer",
                    root_category=root_category,
                    customer_code=customer_code,
                    customer_name=known_customer.get("full_name"),
                    customer=known_customer.get("full_name"),
                    matched_rule=f"known_customer:{customer_code}",
                    registry_customer_id=customer_code,
                    classification_source="customer_registry",
                    classification_role="customer",
                    confidence_reason="Customer code matched the Customer Registry.",
                    confidence=0.98,
                    reasoning=f"Customer code {customer_code} is defined in the customer dictionary.",
                )
            if self._appears_under_project(parts):
                return FolderClassification(
                    folder_type="customer",
                    root_category=root_category,
                    customer_code=customer_code,
                    matched_rule="customer_code:unknown",
                    classification_source="fallback",
                    classification_role="customer",
                    confidence_reason="Folder follows customer code pattern but has no registry entry.",
                    confidence=0.7,
                    reasoning="Folder name follows the customer-code pattern but is not yet in the dictionary.",
                )

        if self._appears_customer_container(parts):
            relaxed_code = self.relaxed_customer_code(name)
            known_customer = self.known_customer(relaxed_code) if relaxed_code else None
            return FolderClassification(
                folder_type="customer",
                root_category=root_category,
                customer_code=relaxed_code,
                customer_name=known_customer.get("full_name") if known_customer else None,
                customer=known_customer.get("full_name") if known_customer else None,
                matched_rule="project_template:customer",
                registry_customer_id=relaxed_code if known_customer else None,
                classification_source="customer_registry" if known_customer else "template",
                classification_role="customer",
                confidence_reason="Direct child under project year; enriched by registry when possible.",
                confidence=0.82 if known_customer else 0.72,
                reasoning="Direct child under a project year is treated as a customer/account container.",
            )

        if self._appears_initiative(parts):
            return FolderClassification(
                folder_type="initiative",
                root_category=root_category,
                initiative=name,
                template_status="project_initiative",
                matched_rule="project_template:initiative",
                classification_source="template",
                classification_role="initiative",
                confidence_reason="Folder appears beneath project year/customer hierarchy.",
                confidence=0.85,
                reasoning="Folder appears to be an initiative under a project year and customer.",
            )

        # Generic organizational container (Resources, Data, Demo, Images, ...).
        # These hold material but are not themselves a topic; classify them so
        # they stop falling through to the LLM.
        if self._is_container_name(name):
            return FolderClassification(
                folder_type="knowledge_asset",
                root_category=root_category,
                matched_rule=f"container:{normalize_name(name)}",
                classification_source="naming_standards",
                classification_role="container",
                confidence_reason="Folder name is a generic organizational container.",
                confidence=0.6,
                reasoning="Folder is a generic container (e.g. Resources/Data), not a distinct topic.",
            )

        # Category inheritance: a descendant of a known non-project top-level root
        # that matched nothing more specific inherits that category's folder_type.
        category_type = self._category_type(root_category)
        if category_type and len(parts) >= 2:
            return FolderClassification(
                folder_type=category_type,
                root_category=root_category,
                matched_rule=f"category:{root_category}",
                classification_source="organization_rules",
                classification_role=category_type,
                confidence_reason="Folder sits under a known top-level category root.",
                confidence=0.6,
                reasoning=f"Folder inherits the '{category_type}' category from its top-level root.",
            )

        return None

    def allowed_empty_match(self, path: str) -> dict[str, Any] | None:
        for item in self.allowed_empty_folders.get("allowed_empty_folders", []):
            if item.get("path") == path:
                return item
            pattern = item.get("path_glob")
            if pattern and fnmatch(path, pattern):
                return item
        return None

    def top_level_rule(self, path: str) -> dict[str, Any] | None:
        if "/" in path or path == ".":
            return None
        return self.organization_rules.get("top_level_folders", {}).get(path)

    def is_temporal(self, name: str) -> bool:
        temporal = self.naming_standards.get("temporal", {})
        year_pattern = temporal.get("year_pattern")
        if year_pattern and re.match(year_pattern, name):
            return True
        if not year_pattern and YEAR_PATTERN.match(name):
            return True
        month_pattern = temporal.get("month_pattern")
        if month_pattern and re.match(month_pattern, name):
            return True
        # Common month-name folders: 01_Jan, 202601_Jan, 10Oct, 202510_Oct,
        # 09Sept, 02Feb, 05May. Year prefix is optional; a 1-2 digit month index
        # followed by a 3+ letter month abbreviation is treated as temporal.
        if MONTH_NAME_PATTERN.match(name.strip()):
            return True
        return False

    def customer_code(self, name: str) -> str | None:
        match = CODE_PREFIX_PATTERN.match(name)
        if match:
            return normalize_code(match.group("code"))
        normalized = normalize_code(name)
        if normalized in self.customer_registry.get("customers", {}):
            return normalized
        return None

    def relaxed_customer_code(self, name: str) -> str | None:
        value = re.sub(r"^[0-9]{2}[_ -]", "", name.strip())
        value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
        return normalize_code(value) if value else None

    def known_customer(self, code: str) -> dict[str, Any] | None:
        customers = self.customer_registry.get("customers", {})
        return customers.get(code) or customers.get(code.replace("_", "-")) or customers.get(code.replace("-", "_"))

    def project_match(self, path: str) -> dict[str, Any] | None:
        if path in self.projects_by_path:
            return self.projects_by_path[path]
        return None

    def project_context(self, path: str) -> dict[str, Any] | None:
        for project_path, project in self.projects_by_path.items():
            if path == project_path or path.startswith(f"{project_path}/"):
                return project
        return None

    def project_lifecycle(self, path: str) -> str | None:
        """Registered lifecycle for a project path: lead, active_presales,
        delivery, or archived. None when unregistered."""
        project = self.projects_by_path.get(path)
        if project:
            return project.get("lifecycle") or project.get("status")
        return None

    # ------------------------------------------------------------------
    # Initiative archetypes
    # ------------------------------------------------------------------

    def initiative_type_definition(self, type_name: str) -> dict[str, Any]:
        return (self.initiative_types.get("initiative_types") or {}).get(type_name) or {}

    def registered_initiative_type(self, path: str) -> str | None:
        """Registry-first: the initiative_type recorded in the Project
        Registry for this path, when present."""
        project = self.projects_by_path.get(path)
        if project:
            return project.get("initiative_type")
        return None

    def infer_initiative_type(
        self,
        initiative_name: str,
        child_names: list[str],
    ) -> str:
        """Deterministic archetype inference from folder evidence.

        Order of evidence:
        1. Name signals per archetype (workshop, strategy, architecture...).
           Intent expressed in the name wins: a workshop with stray stage
           folders is still a workshop and must never be asked for PreSales.
        2. Stage-tree children (A./A.1/B. Delivery...) -> sales_opportunity.
        3. Fall back to the configured default type.
        """
        types = self.initiative_types.get("initiative_types") or {}

        lowered_name = initiative_name.lower()
        has_stage_children = any(parse_stage_name(name) for name in child_names)
        for type_name, definition in types.items():
            if type_name == "sales_opportunity":
                continue
            name_any = ((definition.get("signals") or {}).get("name_any")) or []
            if any(signal in lowered_name for signal in name_any):
                # Training engagements sold as opportunities carry the stage
                # tree; structure evidence promotes them to sales_opportunity.
                if type_name == "training_engagement" and has_stage_children:
                    return "sales_opportunity"
                return type_name

        lowered_children = [name.lower() for name in child_names]
        sales = types.get("sales_opportunity") or {}
        children_any = ((sales.get("signals") or {}).get("children_any")) or []
        for signal in children_any:
            if any(child.startswith(signal) for child in lowered_children):
                return "sales_opportunity"
        if any(parse_stage_name(name) for name in child_names):
            return "sales_opportunity"

        return self.initiative_types.get("default_type", "sales_opportunity")

    def initiative_uses_stage_tree(self, type_name: str) -> bool:
        definition = self.initiative_type_definition(type_name)
        if definition:
            return bool(definition.get("uses_stage_tree", False))
        # Unknown type: be conservative and do not force the sales template.
        return False

    def stage_name(self, name: str) -> str | None:
        normalized = normalize_name(name)
        if normalized in self.stage_lookup:
            return self.stage_lookup[normalized]
        if parse_stage_name(name):
            # Stage-prefixed folders are classified as stages so structural
            # noise stays suppressed, but the template differ validates them
            # (collisions, wrong-letter nesting, alias drift) instead of
            # rubber-stamping the name as compliant.
            return name
        return None

    def duplicate_ignore_names(self) -> set[str]:
        names = self.naming_standards.get("duplicate_detection", {}).get("ignore_exact_names", [])
        return {normalize_name(name) for name in names}

    def duplicate_ignore_roles(self) -> set[str]:
        return set(self.naming_standards.get("duplicate_detection", {}).get("ignore_roles", []))

    def _build_stage_lookup(self) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for item in self.naming_standards.get("stage_names", []):
            canonical = item["canonical"]
            lookup[normalize_name(canonical)] = canonical
            for alias in item.get("aliases", []):
                lookup[normalize_name(alias)] = canonical
        return lookup

    def _load_yaml(self, name: str) -> dict[str, Any]:
        path = self.rules_dir / name
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _appears_under_project(self, parts: list[str]) -> bool:
        return len(parts) >= 3 and parts[0] == self.project_templates.get("project_root", "01 Project")

    def _appears_customer_container(self, parts: list[str]) -> bool:
        if len(parts) != 3:
            return False
        if parts[0] != self.project_templates.get("project_root", "01 Project"):
            return False
        return self.is_temporal(parts[1])

    def _appears_initiative(self, parts: list[str]) -> bool:
        if len(parts) != 4:
            return False
        if parts[0] != self.project_templates.get("project_root", "01 Project"):
            return False
        if not self.is_temporal(parts[1]):
            return False
        return self.customer_code(parts[2]) is not None

    def _is_container_name(self, name: str) -> bool:
        containers = {
            normalize_name(c)
            for c in self.naming_standards.get("container_names", [])
        }
        return normalize_name(name) in containers

    def _category_type(self, root_category: str | None) -> str | None:
        if not root_category:
            return None
        rule = self.organization_rules.get("top_level_folders", {}).get(root_category)
        if not rule:
            return None
        return rule.get("category_type")


def normalize_code(value: str) -> str:
    return value.strip().upper().replace("-", "_")


def normalize_name(value: str) -> str:
    return " ".join(Path(value).name.strip().lower().replace("_", " ").split())
