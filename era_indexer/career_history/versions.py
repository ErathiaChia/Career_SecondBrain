"""Document version chains (Architecture_v1 -> v2 -> v3).

Two files are versions of each other when they live in the same scope (the same
project, else the same parent folder), share a file type, and share a *family
key*: the file name with version tokens (v2, v1.1, rev3), working-set affixes
(final, draft, copy, Page6, conflict copies) and leading document IDs removed.
Date stamps are kept, because dated notes (20250621_ToDo) are a time series,
not versions of one document.

``link_versions`` rebuilds ``document_versions`` and appends a
``version_added`` vault event when a new latest version appears in a family.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from rich.console import Console

from career_history import intel_db

console = Console()

_ID_PREFIX = re.compile(r"^\d+(?:-\d+)*\s+")
_VERSION_TOKEN = re.compile(r"(?:^|(?<=[\s_\-.(]))(?:v|ver|version|rev|r)\s?(\d+(?:[._]\d+)*)(?=$|[\s_\-.)])",
                            re.IGNORECASE)
_AFFIXES = re.compile(
    r"(?:^|(?<=[\s_\-.(]))(?:final|draft|latest|updated|update|copy|clean|signed|"
    r"page\s?\d+|conflict[\w\s-]*|copy of)(?=$|[\s_\-.)])",
    re.IGNORECASE,
)
_PAREN_COPY = re.compile(r"\(\d+\)")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def parse_version(file_name: str) -> tuple[int, ...] | None:
    stem = os.path.splitext(file_name or "")[0]
    matches = _VERSION_TOKEN.findall(stem)
    if not matches:
        return None
    return tuple(int(p) for p in re.split(r"[._]", matches[-1]) if p.isdigit())


def version_label(file_name: str) -> str | None:
    v = parse_version(file_name)
    return "v" + ".".join(str(x) for x in v) if v else None


def family_key(file_name: str) -> str:
    stem = os.path.splitext(file_name or "")[0].strip()
    stem = _ID_PREFIX.sub("", stem)
    stem = _VERSION_TOKEN.sub(" ", stem)
    stem = _AFFIXES.sub(" ", stem)
    stem = _PAREN_COPY.sub(" ", stem)
    return _NON_ALNUM.sub(" ", stem.lower()).strip()


def scope_key(row: dict[str, Any]) -> str:
    return row.get("project_key") or os.path.dirname(row["file_path"])


def build_chains(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group files into families and order each family oldest -> newest.

    Ordered by version number when every member carries one, otherwise by
    modification time (a "final" file without a number is usually the newest).
    """
    families: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for f in files:
        key = family_key(f["file_name"])
        if not key:
            continue
        families[(scope_key(f), key, (f.get("file_type") or "").lower())].append(f)
    rows: list[dict[str, Any]] = []
    epoch = datetime(1970, 1, 1)
    for (scope, key, _ftype), members in families.items():
        versions = [parse_version(m["file_name"]) for m in members]
        if all(v is not None for v in versions):
            order = sorted(zip(members, versions),
                           key=lambda mv: (mv[1], mv[0].get("last_modified_at") or epoch))
            ordered = [m for m, _ in order]
        else:
            ordered = sorted(members, key=lambda m: (m.get("last_modified_at") or epoch, m["file_name"]))
        previous = None
        for rank, m in enumerate(ordered, start=1):
            rows.append({
                "file_id": m["file_id"],
                "family_key": key,
                "scope_key": scope,
                "project_id": m.get("project_id"),
                "version_label": version_label(m["file_name"]),
                "version_rank": rank,
                "previous_file_id": previous,
                "is_latest": rank == len(ordered),
                "family_size": len(ordered),
                "file_name": m["file_name"],
                "file_path": m["file_path"],
            })
            previous = m["file_id"]
    return rows


def new_latest_versions(rows: list[dict[str, Any]], existing: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Latest members of multi-file families that were not already the latest
    member of a multi-file family before this rebuild."""
    out = []
    for r in rows:
        if not r["is_latest"] or r["family_size"] < 2:
            continue
        prev = existing.get(r["file_id"])
        if prev is None or not prev.get("is_latest") or (prev.get("family_size") or 1) < 2:
            out.append(r)
    return out


def link_versions() -> dict[str, Any]:
    files = intel_db.version_candidates()
    existing = intel_db.existing_version_rows()
    rows = build_chains(files)
    by_id = {r["file_id"]: r for r in rows}
    intel_db.replace_document_versions([
        {k: r[k] for k in ("file_id", "family_key", "scope_key", "project_id", "version_label",
                           "version_rank", "previous_file_id", "is_latest", "family_size")}
        for r in rows
    ])
    events = 0
    if existing:  # the first build would otherwise announce every family at once
        for r in new_latest_versions(rows, existing):
            prev = by_id.get(r["previous_file_id"]) if r["previous_file_id"] else None
            intel_db.record_event("version_added", r["file_path"], file_id=r["file_id"], payload={
                "family_key": r["family_key"],
                "version_label": r["version_label"],
                "previous_file_id": r["previous_file_id"],
                "previous_file_name": prev["file_name"] if prev else None,
                "project_id": r["project_id"],
            })
            events += 1
    families = sum(1 for r in rows if r["is_latest"] and r["family_size"] > 1)
    summary = {"files": len(rows), "multi_version_families": families, "version_events": events}
    console.log(f"[green]link-versions done.[/green] {summary}")
    return summary
