"""Document diffs: compare two versions of a document (the previous file in its
version chain, or an earlier conversion of the same file).

Text comes from the indexer's cached ``converted_markdown`` artifacts, which are
kept per content hash, so earlier contents survive edits. When no artifact exists
(plain-text files) the current text is rebuilt from chunks and the previous text
is reported as unavailable rather than guessed.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

from era_mcp import llm, projects

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")


def _sections(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {"(top)": []}
    current = "(top)"
    for line in (text or "").splitlines():
        m = _HEADING.match(line)
        if m:
            current = m.group(1).strip()
            out.setdefault(current, [])
        else:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def diff_texts(old: str, new: str, max_lines: int = 200) -> dict[str, Any]:
    """Line diff plus a section-level view (added / removed / changed headings)."""
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    unified = list(difflib.unified_diff(old_lines, new_lines, "previous", "current", lineterm="", n=1))
    added = sum(1 for l in unified if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in unified if l.startswith("-") and not l.startswith("---"))
    old_s, new_s = _sections(old), _sections(new)
    changed = [h for h in new_s if h in old_s and old_s[h] != new_s[h] and h != "(top)"]
    ratio = difflib.SequenceMatcher(None, old or "", new or "", autojunk=False).ratio() \
        if len(old or "") + len(new or "") < 400_000 else None
    return {
        "lines_added": added,
        "lines_removed": removed,
        "similarity": round(ratio, 3) if ratio is not None else None,
        "sections_added": [h for h in new_s if h not in old_s],
        "sections_removed": [h for h in old_s if h not in new_s],
        "sections_changed": changed,
        "diff": unified[:max_lines],
        "truncated": len(unified) > max_lines,
    }


def _markdown_versions(file_id: int) -> list[dict[str, Any]]:
    if not projects._present("processing_artifacts"):
        return []
    return projects._query("""
        SELECT source_hash, payload ->> 'markdown' AS markdown, updated_at
          FROM processing_artifacts
         WHERE file_id = :f AND artifact_type = 'converted_markdown'
         ORDER BY updated_at DESC
    """, {"f": file_id})


def _chunk_text(file_id: int) -> str:
    rows = projects._query("""
        SELECT content FROM document_chunks WHERE file_id = :f ORDER BY chunk_index
    """, {"f": file_id})
    return "\n\n".join(r["content"] for r in rows)


def _file(file_id: int) -> dict[str, Any] | None:
    rows = projects._query("""
        SELECT id AS file_id, file_name, file_path, file_hash, last_modified_at
          FROM file_registry WHERE id = :f
    """, {"f": file_id})
    return rows[0] if rows else None


def _current_text(file_id: int, file_hash: str | None) -> str:
    versions = _markdown_versions(file_id)
    for v in versions:
        if v["source_hash"] == file_hash and v["markdown"]:
            return v["markdown"]
    if versions and versions[0]["markdown"]:
        return versions[0]["markdown"]
    return _chunk_text(file_id)


def resolve_pair(file_id: int, other_file_id: int | None = None) -> dict[str, Any]:
    """Pick (previous, current) texts: an explicit other file, else the previous
    file in the version chain, else the previous conversion of this file."""
    current = _file(file_id)
    if current is None:
        return {"error": f"file {file_id} not found"}
    new_text = _current_text(file_id, current.get("file_hash"))
    if other_file_id is None and projects._present("document_versions"):
        rows = projects._query("SELECT previous_file_id FROM document_versions WHERE file_id = :f",
                               {"f": file_id})
        other_file_id = rows[0]["previous_file_id"] if rows else None
    if other_file_id is not None:
        other = _file(other_file_id)
        if other is None:
            return {"error": f"file {other_file_id} not found"}
        return {"current": current, "previous": other, "basis": "version_chain",
                "new_text": new_text, "old_text": _current_text(other_file_id, other.get("file_hash"))}
    earlier = [v for v in _markdown_versions(file_id)
               if v["source_hash"] != current.get("file_hash") and v["markdown"]]
    if earlier:
        return {"current": current, "previous": {**current, "as_of": earlier[0]["updated_at"]},
                "basis": "earlier_conversion", "new_text": new_text, "old_text": earlier[0]["markdown"]}
    return {"current": current, "previous": None, "basis": "none", "new_text": new_text, "old_text": None}


async def summarize(diff: dict[str, Any], file_name: str) -> dict[str, Any]:
    """LLM summary of a diff. States explicitly when no rationale is present."""
    body = "\n".join(diff["diff"][:160])
    messages = [
        {"role": "system", "content": (
            "You summarise document changes for a project lead. Reply JSON: "
            '{"summary": "...", "key_changes": ["..."], "why_it_matters": ["..."], '
            '"rationale": "stated reason or null"}. Only use what the diff shows. If the '
            'diff does not state why, rationale must be null.')},
        {"role": "user", "content": f"Document: {file_name}\nSections changed: {diff['sections_changed']}\n"
                                    f"Sections added: {diff['sections_added']}\n"
                                    f"Sections removed: {diff['sections_removed']}\n\nDiff:\n{body}"},
    ]
    try:
        out = await llm.chat_json(messages, timeout=90)
    except (llm.LLMUnavailable, ValueError) as e:
        return {"summary": None, "error": f"summary unavailable: {e}"}
    if not isinstance(out, dict):
        return {"summary": None, "error": "summary unavailable: non-object response"}
    if not out.get("rationale"):
        out["rationale"] = "Change detected; rationale not found in the documents."
    return out
