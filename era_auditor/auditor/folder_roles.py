"""Folder role resolution: organizational containers versus knowledge.

Every folder gets a role BEFORE any auditing logic runs. Roles answer
"what is this folder FOR?" so the auditor reasons about assets instead of
folder names:

- CONTAINER folders (Resources, Templates, Version 1, drafts, ...) organize
  knowledge; they are not knowledge. Duplication detection and topic
  comparison must never operate on them.
- TEMPORAL folders (2026, Jan, 202510_Oct, Sprint 7, Q1) partition by time.
  Repeated temporal names across the vault are intentional, never findings.

Other roles map directly from the existing classification folder_type.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from .models import FolderClassification, FolderRecord


class FolderRole(str, Enum):
    """The nine folder roles from the Knowledge Steward directive.

    Container folders (Resources, Templates, Version 1, Presentation Slides)
    provide structure; they are NOT knowledge entities. RESOURCE_LIBRARY is
    the shared, reusable knowledge collection (04 Resources). ADMINISTRATIVE
    covers ops/admin folders that organize work rather than hold customer
    knowledge. Templates are containers; there is no separate asset role
    because assets are tracked in the asset registry, not as folder roles.
    """

    ROOT = "root"
    PROJECT = "project"
    CUSTOMER = "customer"
    INITIATIVE = "initiative"
    STAGE = "stage"
    CONTAINER = "container"
    TEMPORAL = "temporal"
    RESOURCE_LIBRARY = "resource_library"
    ADMINISTRATIVE = "administrative"


# Temporal partition patterns beyond plain years:
#   "Jan", "01_Jan", "January", "202510_Oct", "202602_Feb", "2026-01",
#   "Sprint 7", "Q1", "Q3 2026", "Week 12"
MONTH_NAMES = (
    "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
    "|january|february|march|april|june|july|august|september|october|november|december"
)
TEMPORAL_PATTERNS = [
    re.compile(r"^20[0-9]{2}$"),                                  # 2026
    re.compile(rf"^({MONTH_NAMES})$", re.IGNORECASE),             # Jan, October
    re.compile(rf"^[0-9]{{1,2}}[._ -]({MONTH_NAMES})$", re.IGNORECASE),  # 01_Jan
    re.compile(rf"^20[0-9]{{4}}[._ -]({MONTH_NAMES})$", re.IGNORECASE),  # 202510_Oct
    re.compile(r"^20[0-9]{2}[._ -](0[1-9]|1[0-2])$"),             # 2026-01
    re.compile(r"^(0[1-9]|1[0-2])$"),                             # 01..12
    re.compile(r"^sprint[ _-]?[0-9]+$", re.IGNORECASE),           # Sprint 7
    re.compile(r"^q[1-4]([ _-]?20[0-9]{2})?$", re.IGNORECASE),    # Q1, Q3 2026
    re.compile(r"^week[ _-]?[0-9]{1,2}$", re.IGNORECASE),         # Week 12
    re.compile(r"^[0-9]{2}[._ -]?w[0-9]{1,2}$", re.IGNORECASE),   # 26W12
]

# Version-container patterns: "Version 1", "v2", "V3.1", "Version_2"
VERSION_PATTERNS = [
    re.compile(r"^version[ _-]?[0-9]+(\.[0-9]+)*$", re.IGNORECASE),
    re.compile(r"^v[0-9]+(\.[0-9]+)*$", re.IGNORECASE),
]

_FOLDER_TYPE_TO_ROLE: dict[str, FolderRole] = {
    "root": FolderRole.ROOT,
    "inbox": FolderRole.CONTAINER,
    "temporal": FolderRole.TEMPORAL,
    "customer": FolderRole.CUSTOMER,
    "initiative": FolderRole.INITIATIVE,
    "stage": FolderRole.STAGE,
    "project_artifact": FolderRole.STAGE,
    "project": FolderRole.PROJECT,
    "resource": FolderRole.RESOURCE_LIBRARY,
    "product": FolderRole.RESOURCE_LIBRARY,
    # Ops/admin folders organize work; they are administrative, not customer
    # knowledge libraries.
    "administration": FolderRole.ADMINISTRATIVE,
    "operations": FolderRole.ADMINISTRATIVE,
    # Templates are containers (structure, not knowledge).
    "template": FolderRole.CONTAINER,
    # Knowledge assets live in the registry, not as folder roles; a folder
    # that holds them is part of the resource library it belongs to.
    "knowledge_asset": FolderRole.RESOURCE_LIBRARY,
    "archive": FolderRole.CONTAINER,
    "code_repo": FolderRole.CONTAINER,
}


def _normalize(name: str) -> str:
    """Lowercase, strip numeric prefixes and separators for matching."""
    value = re.sub(r"^[0-9]{1,3}[._ -]+", "", name.strip())
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


class FolderRoleResolver:
    """Deterministic role resolution layered on existing classifications."""

    def __init__(self, naming_standards: dict[str, Any]):
        self.container_names: set[str] = {
            str(name).strip().lower()
            for name in (naming_standards.get("container_names") or [])
        }

    def is_temporal_name(self, name: str) -> bool:
        stripped = name.strip()
        return any(pattern.match(stripped) for pattern in TEMPORAL_PATTERNS)

    def is_version_name(self, name: str) -> bool:
        stripped = name.strip()
        return any(pattern.match(stripped) for pattern in VERSION_PATTERNS)

    def is_container_name(self, name: str) -> bool:
        if self.is_version_name(name):
            return True
        return _normalize(name) in self.container_names

    def resolve(
        self,
        folder: FolderRecord,
        classification: FolderClassification | None = None,
    ) -> FolderRole:
        """Resolve the folder's role.

        Name evidence for CONTAINER/TEMPORAL wins over generic classification:
        a "Resources" folder inside a project is a container regardless of how
        the classifier labeled it. Structural classifications (root, customer,
        stage, initiative) win over name evidence because they carry path
        context that names alone don't.
        """
        folder_type = classification.folder_type if classification else None

        structural = {"root", "customer", "initiative", "stage", "project_artifact", "code_repo"}
        if folder_type in structural:
            return _FOLDER_TYPE_TO_ROLE[folder_type]

        if self.is_temporal_name(folder.name):
            return FolderRole.TEMPORAL
        if self.is_container_name(folder.name):
            return FolderRole.CONTAINER

        if folder_type in _FOLDER_TYPE_TO_ROLE:
            return _FOLDER_TYPE_TO_ROLE[folder_type]

        # Unclassified folders default to a resource library: a collection of
        # whatever knowledge lives in or below them. Assets themselves are
        # tracked in the asset registry, not as folder roles.
        return FolderRole.RESOURCE_LIBRARY

    def audit_exempt(self, role: FolderRole) -> bool:
        """Roles that duplication/topic analysis must never operate on."""
        return role in {FolderRole.CONTAINER, FolderRole.TEMPORAL, FolderRole.ROOT}
