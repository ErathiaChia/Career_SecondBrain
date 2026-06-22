"""Entity graph extraction and graph export generation."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any

from rich.console import Console

from era import config, db


console = Console()

EXTRACTOR_VERSION = "entity-relationship-v1"
MAX_CHUNK_CHARS = 4500

ENTITY_TYPES = {
    "person", "team", "company", "project", "technology", "product",
    "meeting", "concept", "process", "role", "topic", "document",
    "organization",
}

RELATIONSHIP_TYPES = {
    "OWNS", "USES", "DEPENDS_ON", "MANAGES", "ATTENDED", "MENTIONED_IN",
    "RELATED_TO", "DISCUSSED_IN", "REFERENCES",
}

NODE_COLORS = {
    "person": "#f97316",
    "company": "#2563eb",
    "organization": "#2563eb",
    "project": "#16a34a",
    "technology": "#7c3aed",
    "product": "#9333ea",
    "team": "#0284c7",
    "meeting": "#ca8a04",
    "concept": "#64748b",
    "process": "#0d9488",
    "role": "#0891b2",
    "topic": "#64748b",
    "document": "#0f172a",
    "community": "#db2777",
}


def refresh(
    folder: str | None = None,
    limit: int | None = None,
    force: bool = False,
    include_relationships: bool = True,
    rebuild_snapshot: bool = True,
) -> dict[str, Any]:
    """Extract graph entities/relationships, then optionally rebuild snapshot."""
    chunks = db.graph_chunks_for_extraction(
        folder=folder,
        limit=limit,
        extractor_version=EXTRACTOR_VERSION,
        force=force,
    )
    processed = failed = entity_count = relationship_count = 0
    for chunk in chunks:
        try:
            db.clear_chunk_graph_data(chunk["chunk_id"])
            extracted = extract_chunk(chunk, include_relationships=include_relationships)
            ids_by_key = _persist_entities(chunk, extracted.get("entities", []))
            entity_count += len(ids_by_key)
            if include_relationships:
                relationship_count += _persist_relationships(
                    chunk,
                    extracted.get("relationships", []),
                    ids_by_key,
                )
            db.mark_graph_chunk_extracted(
                chunk["chunk_id"],
                chunk["content_hash"],
                EXTRACTOR_VERSION,
            )
            processed += 1
        except Exception as e:
            failed += 1
            db.mark_graph_chunk_extracted(
                chunk["chunk_id"],
                chunk["content_hash"],
                EXTRACTOR_VERSION,
                status="failed",
                error_message=f"{type(e).__name__}: {e}",
            )
            console.log(
                f"[red]Graph extraction failed[/red] "
                f"{chunk['file_name']}#{chunk['chunk_index']}: {e}"
            )
    db.cleanup_orphan_graph_rows()
    snapshot = build_and_save_snapshot(folder=folder) if rebuild_snapshot else None
    return {
        "folder": folder,
        "processed_chunks": processed,
        "failed_chunks": failed,
        "entities_seen": entity_count,
        "relationships_seen": relationship_count,
        "snapshot": snapshot,
    }


def build_and_save_snapshot(folder: str | None = None) -> dict[str, Any]:
    scope = _scope(folder)
    rows = db.graph_snapshot_rows(folder=folder)
    payload = build_snapshot_payload(scope, rows)
    source_hash = _hash(rows)
    return db.save_graph_snapshot(
        scope=scope,
        source_hash=source_hash,
        extraction_version=EXTRACTOR_VERSION,
        payload=payload,
    )


def status(scope: str = "all") -> dict[str, Any]:
    return db.graph_status(scope=scope)


def extract_chunk(
    chunk: dict[str, Any],
    include_relationships: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    text = str(chunk.get("content") or "")[:MAX_CHUNK_CHARS]
    context = {
        "file_name": chunk.get("file_name"),
        "folder": chunk.get("folder"),
        "section_path": chunk.get("section_path"),
        "metadata": chunk.get("metadata") or {},
    }
    parsed = _extract_with_ollama(text, context, include_relationships)
    return _normalize_extraction(parsed)


def build_snapshot_payload(
    scope: str,
    rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Build a library-independent graph export with Sigma-compatible fields."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    degree: dict[str, int] = defaultdict(int)
    entity_ids = {row["id"] for row in rows["entities"]}
    metadata = {
        (row["object_type"], row["object_id"]): row
        for row in rows.get("graph_metadata", [])
    }

    for row in rows["relationships"]:
        source = f"entity:{row['source_entity_id']}"
        target = f"entity:{row['target_entity_id']}"
        if row["source_entity_id"] not in entity_ids or row["target_entity_id"] not in entity_ids:
            continue
        graph_meta = metadata.get(("relationship", row["id"]), {})
        evidence_count = int(row["evidence_count"])
        degree[source] += evidence_count
        degree[target] += evidence_count
        edges.append({
            "key": f"relationship:{row['id']}",
            "id": f"relationship:{row['id']}",
            "source": source,
            "target": target,
            "label": row["relationship_type"],
            "type": row["relationship_type"],
            "relationship_type": row["relationship_type"],
            "size": max(1, min(8, evidence_count)),
            "edge_weight": _float(graph_meta.get("edge_weight")) or max(1, evidence_count),
            "edge_confidence": _float(graph_meta.get("edge_confidence")) or _float(row.get("confidence")),
            "metadata": {
                "confidence": _float(row.get("confidence")),
                "evidence_count": evidence_count,
                "file_count": int(row["file_count"]),
                "provenance": {
                    "relationship_id": row["id"],
                    "evidence_count": evidence_count,
                    "file_count": int(row["file_count"]),
                },
            },
        })

    for row in rows["mentions"]:
        source = f"entity:{row['entity_id']}"
        target = f"file:{row['file_id']}"
        if row["entity_id"] not in entity_ids:
            continue
        mention_count = int(row["mention_count"])
        degree[source] += mention_count
        degree[target] += mention_count
        edges.append({
            "key": f"mention:{row['entity_id']}:{row['file_id']}",
            "id": f"mention:{row['entity_id']}:{row['file_id']}",
            "source": source,
            "target": target,
            "label": "MENTIONED_IN",
            "type": "MENTIONED_IN",
            "relationship_type": "MENTIONED_IN",
            "size": max(1, min(6, mention_count)),
            "edge_weight": max(1, mention_count),
            "edge_confidence": _float(row.get("avg_confidence")),
            "metadata": {
                "mention_count": mention_count,
                "confidence": _float(row.get("avg_confidence")),
                "provenance": {
                    "entity_id": row["entity_id"],
                    "file_id": row["file_id"],
                    "mention_count": mention_count,
                },
            },
        })

    positions = _layout_positions(
        rows["entities"],
        rows["files"],
        rows.get("communities", []),
    )
    for row in rows["entities"]:
        key = f"entity:{row['id']}"
        entity_type = _normalize_type(row["entity_type"])
        graph_meta = metadata.get(("entity", row["id"]), {})
        node_degree = int(graph_meta.get("node_degree") or degree.get(key, 0))
        node_weight = _float(graph_meta.get("node_weight")) or max(1, degree.get(key, 1))
        nodes.append({
            "key": key,
            "id": key,
            "label": row["canonical_name"],
            "type": entity_type,
            "node_type": entity_type,
            "x": positions[key][0],
            "y": positions[key][1],
            "size": max(4, min(22, 4 + math.sqrt(node_weight) * 2)),
            "color": NODE_COLORS.get(entity_type, NODE_COLORS["topic"]),
            "node_weight": node_weight,
            "node_degree": node_degree,
            "metadata": {
                "entity_id": row["id"],
                "aliases": row.get("aliases") or [],
                "mention_count": int(row["mention_count"]),
                "file_count": int(row["file_count"]),
                "confidence": _float(row.get("avg_confidence")),
                "provenance": {
                    "entity_id": row["id"],
                    "mention_count": int(row["mention_count"]),
                    "file_count": int(row["file_count"]),
                },
            },
        })

    for row in rows["files"]:
        key = f"file:{row['id']}"
        nodes.append({
            "key": key,
            "id": key,
            "label": row["file_name"],
            "type": "document",
            "node_type": "document",
            "x": positions[key][0],
            "y": positions[key][1],
            "size": max(5, min(18, 4 + math.sqrt(degree.get(key, 1)) * 1.6)),
            "color": NODE_COLORS["document"],
            "node_weight": max(1, degree.get(key, 1)),
            "node_degree": degree.get(key, 0),
            "metadata": {
                "file_id": row["id"],
                "folder": row["folder"],
                "is_audio": row["is_audio"],
                "entity_count": int(row["entity_count"]),
                "mention_count": int(row["mention_count"]),
                "provenance": {"file_id": row["id"], "folder": row["folder"]},
            },
        })

    for row in rows.get("communities", []):
        key = f"community:{row['id']}"
        graph_meta = metadata.get(("community", row["id"]), {})
        member_count = int(row.get("member_count") or 0)
        nodes.append({
            "key": key,
            "id": key,
            "label": row["name"],
            "type": "community",
            "node_type": "community",
            "x": positions[key][0],
            "y": positions[key][1],
            "size": max(8, min(26, 5 + math.sqrt(max(1, member_count)) * 3)),
            "color": NODE_COLORS["community"],
            "node_weight": _float(graph_meta.get("node_weight")) or max(1, member_count),
            "node_degree": int(graph_meta.get("node_degree") or member_count),
            "metadata": {
                "community_id": row["id"],
                "summary": row["summary"],
                "algorithm": row["algorithm"],
                "algorithm_version": row["algorithm_version"],
                "member_count": member_count,
                "provenance": {
                    "community_id": row["id"],
                    "algorithm": row["algorithm"],
                    "algorithm_version": row["algorithm_version"],
                },
            },
        })

    return {
        "scope": scope,
        "version": EXTRACTOR_VERSION,
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "entity_count": len(rows["entities"]),
            "file_count": len(rows["files"]),
            "community_count": len(rows.get("communities", [])),
            "export_contract": "v3-graph-export-v1",
        },
    }


def _persist_entities(chunk: dict[str, Any], entities: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    ids_by_key: dict[tuple[str, str], int] = {}
    for entity in entities:
        name = _clean_name(entity.get("name") or entity.get("canonical_name"))
        if not name:
            continue
        entity_type = _normalize_type(entity.get("type") or entity.get("entity_type"))
        aliases = [_clean_name(a) for a in entity.get("aliases", []) if _clean_name(a)]
        entity_id = db.upsert_entity(
            canonical_name=name,
            entity_type=entity_type,
            aliases=aliases,
            metadata={"source": "v3_graph_extraction"},
        )
        db.insert_entity_mention(
            entity_id=entity_id,
            file_id=chunk["file_id"],
            chunk_id=chunk["chunk_id"],
            section_id=chunk.get("section_id"),
            mention_text=entity.get("mention_text") or name,
            confidence=float(entity.get("confidence") or 0.7),
            extractor_version=EXTRACTOR_VERSION,
        )
        ids_by_key[(_entity_key(name), entity_type)] = entity_id
    return ids_by_key


def _persist_relationships(
    chunk: dict[str, Any],
    relationships: list[dict[str, Any]],
    ids_by_key: dict[tuple[str, str], int],
) -> int:
    count = 0
    for rel in relationships:
        source_name = _clean_name(rel.get("source"))
        target_name = _clean_name(rel.get("target"))
        if not source_name or not target_name or source_name == target_name:
            continue
        source_type = _normalize_type(rel.get("source_type"))
        target_type = _normalize_type(rel.get("target_type"))
        source_id = ids_by_key.get((_entity_key(source_name), source_type))
        target_id = ids_by_key.get((_entity_key(target_name), target_type))
        if source_id is None or target_id is None:
            continue
        relationship_id = db.upsert_relationship(
            source_entity_id=source_id,
            relationship_type=_normalize_relation(rel.get("type")),
            target_entity_id=target_id,
            confidence=float(rel.get("confidence") or 0.65),
            metadata={"source": "v3_graph_extraction"},
        )
        db.insert_relationship_evidence(
            relationship_id=relationship_id,
            file_id=chunk["file_id"],
            chunk_id=chunk["chunk_id"],
            section_id=chunk.get("section_id"),
            evidence_text=_clean_evidence(rel.get("evidence") or ""),
            extractor_version=EXTRACTOR_VERSION,
        )
        count += 1
    return count


def _extract_with_ollama(
    text: str,
    context: dict[str, Any],
    include_relationships: bool,
) -> dict[str, Any]:
    model = (
        os.environ.get("ERA_GRAPH_EXTRACTION_MODEL")
        or config.get().get("models", {}).get("graph_extraction_model")
        or "llama3.1"
    )
    base_url = (
        os.environ.get("OLLAMA_BASE_URL")
        or config.v2().get("graph_ollama_base_url")
        or "http://localhost:11434"
    ).rstrip("/")
    payload = {
        "model": model,
        "prompt": _prompt(text, context, include_relationships),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e
    return _loads_json_object(body.get("response") or "{}")


def _prompt(text: str, context: dict[str, Any], include_relationships: bool) -> str:
    relationship_instruction = (
        "Extract relationships only when the chunk explicitly supports them."
        if include_relationships else "Return an empty relationships array."
    )
    return f"""
Extract a compact, provenance-ready knowledge graph from this KB chunk.

Allowed entity types: {", ".join(sorted(ENTITY_TYPES - {"document"}))}.
Allowed relationship types: {", ".join(sorted(RELATIONSHIP_TYPES))}.

Rules:
- Return only valid JSON.
- Keep entity names canonical and short.
- Do not invent facts beyond the text.
- Prefer precise relationship labels from the allowed list.
- Every relationship must include a short evidence quote from the chunk.
- {relationship_instruction}

Context:
{json.dumps(context, ensure_ascii=False)}

JSON schema:
{{
  "entities": [
    {{"name": "string", "type": "person|team|project|company|technology|product|meeting|concept|process|organization", "aliases": [], "mention_text": "string", "confidence": 0.0}}
  ],
  "relationships": [
    {{"source": "entity name", "source_type": "entity type", "target": "entity name", "target_type": "entity type", "type": "OWNS|USES|DEPENDS_ON|MANAGES|ATTENDED|MENTIONED_IN|RELATED_TO|DISCUSSED_IN|REFERENCES", "evidence": "short quote", "confidence": 0.0}}
  ]
}}

Chunk:
\"\"\"{text}\"\"\"
""".strip()


def _normalize_extraction(parsed: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        "entities": parsed.get("entities", []) if isinstance(parsed.get("entities"), list) else [],
        "relationships": parsed.get("relationships", []) if isinstance(parsed.get("relationships"), list) else [],
    }


def _loads_json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < start:
            raise
        value = json.loads(raw[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Ollama response was not a JSON object")
    return value


def _layout_positions(
    entities: list[dict[str, Any]],
    files: list[dict[str, Any]],
    communities: list[dict[str, Any]] | None = None,
) -> dict[str, tuple[float, float]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in entities:
        groups[_normalize_type(row["entity_type"])].append(row)
    positions: dict[str, tuple[float, float]] = {}
    type_names = sorted(groups)
    for type_index, entity_type in enumerate(type_names):
        group = groups[entity_type]
        center_angle = 2 * math.pi * type_index / max(1, len(type_names))
        center_x = math.cos(center_angle) * 18
        center_y = math.sin(center_angle) * 18
        radius = max(3, math.sqrt(len(group)) * 2.5)
        for i, row in enumerate(group):
            angle = 2 * math.pi * i / max(1, len(group))
            positions[f"entity:{row['id']}"] = (
                center_x + math.cos(angle) * radius,
                center_y + math.sin(angle) * radius,
            )
    file_radius = max(24, len(files) * 0.8)
    for i, row in enumerate(files):
        angle = 2 * math.pi * i / max(1, len(files))
        positions[f"file:{row['id']}"] = (
            math.cos(angle) * file_radius,
            math.sin(angle) * file_radius,
        )
    community_rows = communities or []
    community_radius = max(34, len(community_rows) * 1.2)
    for i, row in enumerate(community_rows):
        angle = 2 * math.pi * i / max(1, len(community_rows))
        positions[f"community:{row['id']}"] = (
            math.cos(angle) * community_radius,
            math.sin(angle) * community_radius,
        )
    return positions


def _scope(folder: str | None) -> str:
    return f"folder:{folder}" if folder else "all"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _clean_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" \t\n\r:;,.")


def _entity_key(name: str) -> str:
    return _clean_name(name).casefold()


def _normalize_type(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "concept").lower()).strip("_")
    return normalized if normalized in ENTITY_TYPES else "concept"


def _normalize_relation(value: Any) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", str(value or "RELATED_TO").upper()).strip("_")
    return normalized if normalized in RELATIONSHIP_TYPES else "RELATED_TO"


def _clean_evidence(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:500]


def _float(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)
