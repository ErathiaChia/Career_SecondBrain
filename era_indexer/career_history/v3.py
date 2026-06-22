"""Era Vault V3 knowledge operating system orchestration.

V3 keeps chunks as evidence, while summaries, entities, relationships, and
communities become first-class retrieval objects.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from rich.console import Console

from era import db, graph


console = Console()

SUMMARY_MODEL = "extractive-local"
SUMMARY_PROMPT_VERSION = "v3-summary-v1"
COMMUNITY_ALGORITHM = "relationship-neighborhood"
COMMUNITY_VERSION = "v3-community-v1"


def refresh(
    folder: str | None = None,
    limit: int | None = None,
    force_graph: bool = False,
) -> dict[str, Any]:
    """Run the V3 knowledge build stages for an optional ingestion scope."""
    alias_updates = db.sync_v3_chunk_aliases(folder=folder)
    document_summaries = refresh_document_summaries(folder=folder, limit=limit)
    section_summaries = refresh_section_summaries(folder=folder, limit=limit)
    graph_result = graph.refresh(folder=folder, limit=limit, force=force_graph)
    communities = refresh_communities(folder=folder)
    metadata = db.recompute_graph_metadata()
    snapshot = graph.build_and_save_snapshot(folder=folder)
    return {
        "folder": folder,
        "alias_updates": alias_updates,
        "document_summaries": document_summaries,
        "section_summaries": section_summaries,
        "graph": graph_result,
        "communities": communities,
        "graph_metadata": metadata,
        "snapshot": snapshot,
    }


def refresh_document_summaries(
    folder: str | None = None,
    limit: int | None = None,
) -> int:
    """Generate extractive document summaries as retrieval objects."""
    count = 0
    for row in db.v3_documents_for_summary(folder=folder, limit=limit):
        content = row.get("content") or ""
        summary = summarize_text(content, title=row["title"])
        if not summary:
            continue
        db.upsert_document_summary(
            file_id=row["file_id"],
            summary=summary,
            model=SUMMARY_MODEL,
            prompt_version=SUMMARY_PROMPT_VERSION,
            source_hash=row["file_hash"],
            metadata={
                "document_id": row["document_id"],
                "title": row["title"],
                "folder": row["folder"],
                "summary_type": "document",
            },
        )
        count += 1
    return count


def refresh_section_summaries(
    folder: str | None = None,
    limit: int | None = None,
) -> int:
    """Generate extractive section summaries as retrieval objects."""
    count = 0
    for row in db.v3_sections_for_summary(folder=folder, limit=limit):
        content = row.get("content") or ""
        summary = summarize_text(content, title=row["section_path"])
        if not summary:
            continue
        db.upsert_section_summary(
            section_id=row["section_id"],
            file_id=row["file_id"],
            summary=summary,
            model=SUMMARY_MODEL,
            prompt_version=SUMMARY_PROMPT_VERSION,
            source_hash=row["file_hash"],
            metadata={
                "section_path": row["section_path"],
                "folder": row["folder"],
                "summary_type": "section",
            },
        )
        count += 1
    return count


def refresh_communities(folder: str | None = None) -> dict[str, Any]:
    """Create thematic communities from relationship neighborhoods."""
    relationships = db.v3_relationship_rows(folder=folder)
    communities = build_communities(relationships)
    id_map = db.replace_communities(
        communities,
        algorithm=COMMUNITY_ALGORITHM,
        algorithm_version=COMMUNITY_VERSION,
    )
    return {
        "algorithm": COMMUNITY_ALGORITHM,
        "algorithm_version": COMMUNITY_VERSION,
        "communities": len(id_map),
        "relationships": len(relationships),
    }


def status() -> dict[str, int]:
    """Return V3 object counts."""
    return db.v3_status()


def validate(query: str = "What do we know about ArgoCD?") -> dict[str, Any]:
    """Validate that V3 knowledge objects exist for a known rollout query."""
    counts = status()
    ready = {
        "summaries": counts.get("document_summaries", 0) > 0,
        "entities": counts.get("entities", 0) > 0,
        "relationships": counts.get("relationships", 0) > 0,
        "communities": counts.get("communities", 0) > 0,
        "graph_metadata": counts.get("graph_metadata", 0) > 0,
    }
    return {
        "query": query,
        "ready": all(ready.values()),
        "checks": ready,
        "counts": counts,
        "guidance": (
            "Run `era v3-refresh --folder <scope>` before enabling "
            "`v3.knowledge_os_enabled` for sync."
        ),
    }


def summarize_text(text: str, title: str | None = None, max_sentences: int = 3) -> str:
    """Cheap local summary used until LLM summary generation is enabled."""
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    selected = [s.strip() for s in sentences if len(s.strip()) > 30][:max_sentences]
    if not selected:
        selected = [cleaned[:700]]
    prefix = f"{title}: " if title else ""
    return (prefix + " ".join(selected))[:1200]


def build_communities(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster entities by type and direct relationship neighborhoods."""
    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "entity_ids": set(),
        "documents": set(),
        "relationship_types": set(),
        "names": set(),
        "evidence": 0,
    })

    for rel in relationships:
        source_type = rel.get("source_type") or "topic"
        target_type = rel.get("target_type") or "topic"
        rel_type = rel.get("relationship_type") or "RELATED_TO"
        group_name = _community_name(source_type, target_type, rel_type)
        group = groups[group_name]
        group["entity_ids"].add(rel["source_entity_id"])
        group["entity_ids"].add(rel["target_entity_id"])
        group["relationship_types"].add(rel_type)
        group["names"].add(rel.get("source_name") or "")
        group["names"].add(rel.get("target_name") or "")
        group["evidence"] += int(rel.get("evidence_count") or 0)

    communities: list[dict[str, Any]] = []
    for name, group in sorted(groups.items()):
        entity_ids = sorted(group["entity_ids"])
        if not entity_ids:
            continue
        source_hash = _hash({
            "name": name,
            "entities": entity_ids,
            "relationships": sorted(group["relationship_types"]),
        })
        member_names = [n for n in sorted(group["names"]) if n][:8]
        communities.append({
            "name": name,
            "summary": (
                f"{name} connects {len(entity_ids)} entities through "
                f"{', '.join(sorted(group['relationship_types'])) or 'relationships'}. "
                f"Representative members: {', '.join(member_names)}."
            ),
            "source_hash": source_hash,
            "metadata": {
                "relationship_types": sorted(group["relationship_types"]),
                "evidence_count": group["evidence"],
            },
            "members": [
                {
                    "member_type": "entity",
                    "entity_id": entity_id,
                    "membership_weight": 1,
                    "provenance": {
                        "algorithm": COMMUNITY_ALGORITHM,
                        "algorithm_version": COMMUNITY_VERSION,
                    },
                }
                for entity_id in entity_ids
            ],
        })
    return communities


def _community_name(source_type: str, target_type: str, rel_type: str) -> str:
    types = sorted({
        _title(source_type),
        _title(target_type),
    })
    relation = _title(rel_type.replace("_", " "))
    if len(types) == 1:
        return f"{types[0]} {relation}"
    return f"{types[0]} and {types[1]} {relation}"


def _title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "Topic")).strip().title()


def _hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
