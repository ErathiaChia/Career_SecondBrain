"""Deterministic project entity seeding from the folder taxonomy (no LLM).

Derives one canonical ``entities`` row per project from file paths and links every
file under that project as a file-level ``entity_mention``. Runs inside
``discover`` (so project entities stay current as folders change) and via the
``seed-entities`` CLI command. This is what gives the agent canonical project
resolution ("IBF" -> the IBF project entity) + aggregation, with zero LLM.

Configure where projects live in config.yaml:

    seed:
      project_roots:            # path fragments; the segment AFTER each is a project
        - "/01 Project/2026/"
        - "/01 Project/2025/"

The folder segment immediately following a root fragment in a file path is taken
as the project; aliases are derived by stripping the numeric ordering prefix
("01_IBF" -> alias "IBF"). Idempotent: clears prior path-seed mentions and
re-inserts, so re-runs never bloat. No-op when no roots are configured.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from rich.console import Console

from career_history import config, db

console = Console()

SEED_VERSION = "path-seed-v1"
_NUM_PREFIX = re.compile(r"^\s*\d+[.\s_)\-]*")


def _project_roots() -> list[str]:
    roots = config.get().get("seed", {}).get("project_roots", []) or []
    return [str(r) for r in roots if str(r).strip()]


def _segment_after(file_path: str, root: str) -> str | None:
    """Folder segment immediately after ``root`` in ``file_path``; None when the
    root is absent or only a filename (no further folder) follows it."""
    idx = file_path.find(root)
    if idx < 0:
        return None
    rest = file_path[idx + len(root):]
    if "/" not in rest:  # only a filename follows -> not a project folder
        return None
    seg = rest.split("/", 1)[0].strip()
    return seg or None


def _aliases(name: str) -> list[str]:
    out = [name]
    stripped = _NUM_PREFIX.sub("", name).strip()
    if stripped and stripped != name:
        out.append(stripped)
    return out


def seed(folder: str | None = None) -> dict[str, Any]:
    """Upsert project entities + file-level mentions from configured roots.

    Idempotent (clears prior path-seed mentions, scoped, then re-inserts). No-op
    with a log when ``seed.project_roots`` is unset.
    """
    roots = _project_roots()
    if not roots:
        console.log("[yellow]seed-entities: no seed.project_roots configured; skipping.[/yellow]")
        return {"projects": 0, "mentions": 0, "skipped": True}

    project_files: dict[str, set[int]] = defaultdict(set)
    for f in db.files_for_seeding(folder=folder):
        for root in roots:
            seg = _segment_after(f["file_path"], root)
            if seg:
                project_files[seg].add(f["file_id"])
                break

    db.clear_seed_mentions(SEED_VERSION, folder=folder)
    mentions = 0
    for project_name, file_ids in project_files.items():
        entity_id = db.upsert_entity(
            canonical_name=project_name,
            entity_type="project",
            aliases=_aliases(project_name),
            metadata={"source": "path-seed"},
        )
        for file_id in file_ids:
            db.insert_entity_mention(
                entity_id=entity_id,
                file_id=file_id,
                chunk_id=None,
                section_id=None,
                mention_text=project_name,
                confidence=1.0,
                extractor_version=SEED_VERSION,
            )
            mentions += 1
    summary = {"projects": len(project_files), "mentions": mentions, "skipped": False}
    console.log(f"[green]seed-entities done.[/green] {summary}")
    return summary
