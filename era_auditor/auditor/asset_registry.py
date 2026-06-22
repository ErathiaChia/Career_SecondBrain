"""Asset registry: track knowledge assets instead of folders.

An asset is a distinct piece of knowledge content - a deck, document,
spreadsheet, or media file. Identity is the content hash when available
(large files are hashed by the scanner) or the normalized filename for
unhashed small files.

For every asset the registry derives:
- copy_count and all paths where copies live
- project_count / customer_count by parsing each path against the project
  tree (01 Project/{year}/{customer}/{initiative}/...)
- root_count: how many top-level roots the asset spans
- reuse_score (0-100): weighted blend of the above
- canonical_location: the 04 Resources copy when present, else the
  shallowest copy
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .db import AuditorDatabase
from .models import KnowledgeAsset
from .semantic_dupes import _stem_without_affixes

# File categories considered knowledge assets (mirrors scanner.file_category).
KNOWLEDGE_EXTENSIONS: dict[str, str] = {
    ".pdf": "document",
    ".doc": "document",
    ".docx": "document",
    ".md": "document",
    ".txt": "document",
    ".rtf": "document",
    ".ppt": "presentation",
    ".pptx": "presentation",
    ".key": "presentation",
    ".xls": "spreadsheet",
    ".xlsx": "spreadsheet",
    ".csv": "spreadsheet",
    ".png": "media",
    ".jpg": "media",
    ".jpeg": "media",
    ".gif": "media",
    ".webp": "media",
    ".svg": "media",
    ".mp4": "media",
    ".mov": "media",
    ".drawio": "diagram",
    ".vsdx": "diagram",
}

# Minimum size for a file to count as a knowledge asset. Filters out icons,
# stubs and empty placeholders without losing real documents.
DEFAULT_SIZE_FLOOR_BYTES = 16 * 1024

PROJECT_ROOT_PATTERN = re.compile(r"^01[ _].*project", re.IGNORECASE)
RESOURCES_ROOT_PATTERN = re.compile(r"^04[ _].*resource", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"^20[0-9]{2}$")


def normalize_asset_name(filename: str) -> str:
    """Normalize a filename for identity matching of unhashed files:
    lowercase, drop extension, collapse separators, strip version suffixes
    ("v2", "final", "(1)") and dates."""
    stem = filename.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    value = stem.lower()
    value = re.sub(r"[\s_\-\.]+", " ", value).strip()
    value = re.sub(r"\(?(copy|final|draft|v[0-9]+(\.[0-9]+)*|[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})\)?$", "", value).strip()
    value = re.sub(r"\([0-9]+\)$", "", value).strip()
    return value


def parse_project_context(path: str) -> tuple[str | None, str | None]:
    """Extract (customer, project) identity from a path inside 01 Project.

    Expected shape: 01 Project/{year}/{customer}/{initiative}/...
    Returns (customer_segment, "customer/initiative") or (None, None) when
    the path is not inside the project tree.
    """
    parts = path.split("/")
    if not parts or not PROJECT_ROOT_PATTERN.match(parts[0]):
        return None, None
    index = 1
    if index < len(parts) and YEAR_PATTERN.match(parts[index]):
        index += 1
    if index >= len(parts) - 1:  # need at least customer + filename
        return None, None
    customer = parts[index]
    initiative = parts[index + 1] if index + 1 < len(parts) - 1 else None
    project = f"{customer}/{initiative}" if initiative else customer
    return customer, project


def compute_reuse_score(
    copy_count: int,
    project_count: int,
    customer_count: int,
    root_count: int,
) -> int:
    """0-100 reuse score. A single copy in a single place scores 0.

    Weights favor cross-project and cross-customer reuse (the strongest
    signals that an asset is reusable knowledge) over raw copy count.
    """
    score = 0.0
    score += min(copy_count - 1, 5) * 6          # up to 30 for many copies
    score += min(project_count, 4) * 10          # up to 40 for project reuse
    score += min(customer_count, 3) * 8          # up to 24 for customer reuse
    score += min(max(root_count - 1, 0), 2) * 3  # up to 6 for cross-root spread
    return min(int(round(score)), 100)


class AssetRegistryBuilder:
    """Builds the asset registry from auditor_files after each scan."""

    def __init__(
        self,
        database: AuditorDatabase,
        size_floor_bytes: int = DEFAULT_SIZE_FLOOR_BYTES,
    ):
        self.database = database
        self.size_floor_bytes = size_floor_bytes

    def build(self) -> list[KnowledgeAsset]:
        files = self.database.active_files(min_size_bytes=self.size_floor_bytes)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for file in files:
            extension = (file.get("extension") or "").lower()
            file_type = KNOWLEDGE_EXTENSIONS.get(extension)
            if file_type is None:
                continue
            file["file_type"] = file_type
            if file.get("content_hash"):
                key = f"hash:{file['content_hash']}"
            else:
                normalized = normalize_asset_name(file["path"])
                if not normalized:
                    continue
                key = f"name:{extension}:{normalized}"
            groups[key].append(file)

        assets = [self._build_asset(key, copies) for key, copies in groups.items()]
        return sorted(assets, key=lambda a: (-a.reuse_score, -a.copy_count, a.asset_name))

    def refresh(self, run_id: int) -> int:
        """Rebuild and persist the registry for a run. Returns asset count."""
        assets = self.build()
        return self.database.replace_assets(run_id, assets)

    def _build_asset(self, key: str, copies: list[dict[str, Any]]) -> KnowledgeAsset:
        paths = sorted({copy["path"] for copy in copies})
        customers: set[str] = set()
        projects: set[str] = set()
        roots: set[str] = set()
        for path in paths:
            roots.add(path.split("/")[0])
            customer, project = parse_project_context(path)
            if customer:
                customers.add(customer)
            if project:
                projects.add(project)

        resources_copies = [
            path for path in paths if RESOURCES_ROOT_PATTERN.match(path.split("/")[0])
        ]
        if resources_copies:
            canonical = min(resources_copies, key=lambda p: p.count("/"))
        else:
            canonical = min(paths, key=lambda p: (p.count("/"), p))

        primary = copies[0]
        asset_name = paths[0].rsplit("/", 1)[-1]
        # Family key groups working-set derivations (Page6/V3/...) of the same
        # logical asset so the Librarian reasons about the family, not variants.
        family_stem = _stem_without_affixes(asset_name)
        family_key = f"{primary['file_type']}:{family_stem}" if family_stem else None
        return KnowledgeAsset(
            asset_key=key,
            asset_name=asset_name,
            file_hash=primary.get("content_hash"),
            file_type=primary["file_type"],
            size_bytes=max(int(copy["size_bytes"]) for copy in copies),
            copy_count=len(paths),
            paths=paths,
            customer_count=len(customers),
            customers=sorted(customers),
            project_count=len(projects),
            projects=sorted(projects),
            root_count=len(roots),
            reuse_score=compute_reuse_score(
                copy_count=len(paths),
                project_count=len(projects),
                customer_count=len(customers),
                root_count=len(roots),
            ),
            canonical_location=canonical,
            in_resources=bool(resources_copies),
            family_key=family_key,
        )
