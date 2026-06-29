"""Structural / inventory queries over the live ``file_registry``.

Answers *census* questions ("how many projects?", "list all folders under X")
that semantic search structurally cannot — the answer is plain path data in
``file_registry``, kept current by the indexer's discover/sync, so this is always
**dynamic** (no static snapshot). Also renders a compact folder overview for
injecting the live vault layout into the Judge's prompt.

Decoupled: reads only ``file_registry`` (via ``retrieval._get_engine``); never
touches the auditor.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

from era_mcp import config, retrieval

# Strip an ordering prefix like "01 ", "14. ", "06_" for fuzzy name matching.
_NUM_PREFIX = re.compile(r"^\s*\d+[.\s_)\-]*")


def _norm(name: str) -> str:
    """Folder name without its ordering prefix, lowercased (for matching)."""
    return _NUM_PREFIX.sub("", name or "").strip().lower()


def _top_level_counts() -> list[tuple[str, int]]:
    sql = text("SELECT folder, count(*) FROM file_registry GROUP BY folder ORDER BY folder")
    with retrieval._get_engine().connect() as conn:
        return [(r[0], int(r[1])) for r in conn.execute(sql).fetchall()]


def _abs_prefix_for_folder(folder: str) -> str | None:
    """Absolute path prefix ending in '/<folder>/' for a top-level folder name."""
    sql = text("""
        SELECT substring(file_path FROM 1
                 FOR position('/' || :f || '/' in file_path) + length(:f) + 1) AS prefix
          FROM file_registry
         WHERE folder = :f AND position('/' || :f || '/' in file_path) > 0
         LIMIT 1
    """)
    with retrieval._get_engine().connect() as conn:
        row = conn.execute(sql, {"f": folder}).fetchone()
    return row[0] if row and row[0] else None


def list_subfolders(prefix: str | None, depth: int = 1) -> list[dict[str, Any]]:
    """Immediate child folders under an absolute ``prefix`` (live, dynamic).

    Returns ``[{name, file_count, last_modified, path}]`` ordered by name. Only
    real folders (those with files beneath them) are returned — never files that
    sit directly in ``prefix``. ``starts_with`` (not LIKE) avoids wildcard issues
    from ``_`` / ``%`` in folder names.
    """
    if not prefix:
        return []
    if not prefix.endswith("/"):
        prefix += "/"
    d = max(1, int(depth))
    sql = text(f"""
        WITH rels AS (
            SELECT substr(file_path, :plen + 1) AS rem, last_modified_at
              FROM file_registry
             WHERE starts_with(file_path, :prefix)
        )
        SELECT array_to_string((string_to_array(rem, '/'))[1:{d}], '/') AS name,
               count(*) AS file_count,
               max(last_modified_at) AS last_modified
          FROM rels
         WHERE array_length(string_to_array(rem, '/'), 1) > {d}
         GROUP BY name
        HAVING array_to_string((string_to_array(rem, '/'))[1:{d}], '/') <> ''
         ORDER BY name
    """)
    with retrieval._get_engine().connect() as conn:
        rows = conn.execute(sql, {"plen": len(prefix), "prefix": prefix}).fetchall()
    return [
        {
            "name": r[0],
            "file_count": int(r[1]),
            "last_modified": r[2].isoformat() if r[2] else None,
            "path": prefix + r[0],
        }
        for r in rows
    ]


def resolve_prefix(question: str) -> str | None:
    """Best-effort: map a question to an absolute path prefix to enumerate under.

    Matches a top-level folder named in the question, then greedily descends into
    child folders also named in the question (e.g. "ST-Engg 01 Project 2026").
    Returns None when nothing matches (caller then lists top-level folders).
    """
    q = (question or "").lower()
    match = next((f for f in retrieval.list_folders() if _norm(f) and _norm(f) in q), None)
    if not match:
        return None
    prefix = _abs_prefix_for_folder(match)
    if not prefix:
        return None
    for _ in range(5):  # descend at most a few levels
        nxt = next(
            (c["name"] for c in list_subfolders(prefix, 1)
             if _norm(c["name"]) and _norm(c["name"]) in q),
            None,
        )
        if not nxt:
            break
        prefix = prefix + nxt + "/"
    return prefix


def project_inventory(question: str | None = None, prefix: str | None = None) -> dict[str, Any]:
    """High-level answer for "list / how many folders under X" questions.

    Resolves a prefix (explicit ``prefix`` wins; else from ``question``; else
    top-level), lists its immediate child folders, and returns a count. This is
    the structural branch's payload.
    """
    resolved = prefix or (resolve_prefix(question) if question else None)
    if resolved:
        folders = list_subfolders(resolved, 1)
        scope = resolved
    else:
        folders = [
            {"name": f, "file_count": n, "last_modified": None, "path": f}
            for f, n in _top_level_counts()
        ]
        scope = "(top-level)"
    return {"scope": scope, "count": len(folders), "folders": folders}


def folder_overview(max_items: int = 80) -> str:
    """Compact, live text view of the vault layout for prompt injection.

    Top-level folders (with file counts), each followed by its immediate
    subfolders (depth 1), as an indented tree capped at ``max_items`` lines.
    Always reflects the current ``file_registry`` (dynamic, never static).
    """
    lines: list[str] = []
    for folder, count in _top_level_counts():
        if len(lines) >= max_items:
            lines.append("  … (truncated)")
            break
        lines.append(f"{folder}  ({count} files)")
        prefix = _abs_prefix_for_folder(folder)
        if not prefix:
            continue
        for child in list_subfolders(prefix, 1):
            if len(lines) >= max_items:
                break
            lines.append(f"  └ {child['name']}  ({child['file_count']})")
    return "\n".join(lines) if lines else "(vault is empty / not indexed yet)"
