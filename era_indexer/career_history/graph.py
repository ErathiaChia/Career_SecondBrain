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

from career_history import config, db


console = Console()

# Bumped to v2 when facts (decisions/commitments/events) joined the same pass.
# A version change makes graph_chunks_for_extraction treat all chunks as needing
# (re)extraction, so the first v2 run produces entities + relationships + facts.
# v3: typed project facts (requirement/risk/action_item/...) with topic, status,
# priority, owner and supersedes.
EXTRACTOR_VERSION = "entity-rel-facts-v3"
MAX_CHUNK_CHARS = 4500

# Document-level extraction (one LLM call per FILE instead of per chunk) — the
# scalable path for large vaults (~1 call/file vs tens of thousands of chunks).
# Uses its own version so its per-file state in graph_extraction_state never
# collides with chunk-level runs.
DOC_EXTRACTOR_VERSION = "doc-entity-facts-v2"
MAX_DOC_CHARS = 12000
# Long files are split into MAX_DOC_CHARS windows (one call each) instead of being
# truncated to their first window. Capped so one giant file cannot stall a run.
MAX_DOC_WINDOWS = 6

ENTITY_TYPES = {
    "person", "team", "company", "project", "technology", "product",
    "meeting", "concept", "process", "role", "topic", "document",
    "organization", "client", "vendor", "deliverable",
}

RELATIONSHIP_TYPES = {
    "OWNS", "USES", "DEPENDS_ON", "MANAGES", "ATTENDED", "MENTIONED_IN",
    "RELATED_TO", "DISCUSSED_IN", "REFERENCES", "COMMITTED_TO", "DECIDED",
    "HAS_REQUIREMENT", "ADDRESSED_BY", "BLOCKS", "SUPERSEDES", "DELIVERS", "CLIENT_OF",
}

# Structured facts extracted in the SAME pass as entities/relationships.
FACT_KINDS = {
    "decision", "commitment", "event",
    "requirement", "risk", "action_item", "open_question", "dependency", "milestone",
}
FACT_STATUSES = {
    "open", "in_progress", "done", "blocked", "cancelled",
    "proposed", "approved", "rejected", "mitigated",
}
_STATUS_ALIASES = {
    "pending": "open", "todo": "open", "to do": "open", "new": "open", "wip": "in_progress",
    "ongoing": "in_progress", "in progress": "in_progress", "complete": "done",
    "completed": "done", "closed": "done", "resolved": "done", "accepted": "approved",
    "agreed": "approved", "draft": "proposed", "on hold": "blocked",
}
_PRIORITY_ALIASES = {
    "critical": "high", "urgent": "high", "high": "high", "h": "high", "p1": "high",
    "medium": "medium", "med": "medium", "m": "medium", "moderate": "medium", "p2": "medium",
    "low": "low", "l": "low", "minor": "low", "p3": "low",
}
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

NODE_COLORS = {
    "person": "#f97316",
    "company": "#2563eb",
    "organization": "#2563eb",
    "client": "#1d4ed8",
    "vendor": "#3b82f6",
    "deliverable": "#15803d",
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
    processed = failed = entity_count = relationship_count = fact_count = 0
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
            fact_count += _persist_facts(chunk, extracted.get("facts", []), ids_by_key)
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
        "facts_seen": fact_count,
        "snapshot": snapshot,
    }


def refresh_documents(
    folder: str | None = None,
    limit: int | None = None,
    force: bool = False,
    rebuild_snapshot: bool = True,
) -> dict[str, Any]:
    """Document-level extraction: ONE LLM call per FILE (its chunks concatenated
    and capped to MAX_DOC_CHARS), instead of per chunk. The scalable path for
    large vaults — ~one call per file vs tens of thousands. Entities/relationships/
    facts are persisted against the file's representative (first) chunk; the run is
    incremental + folder-scoped via graph_extraction_state (DOC_EXTRACTOR_VERSION)."""
    window_chars, max_windows = _doc_window_settings()
    docs = db.documents_for_extraction(
        folder=folder, limit=limit,
        extractor_version=DOC_EXTRACTOR_VERSION, force=force,
        max_chars=window_chars * max_windows,
    )
    track_changes = _change_tracking_enabled()
    total = len(docs)
    processed = failed = entity_count = relationship_count = fact_count = 0
    console.log(f"[bold]Document extraction[/bold]: {total} file(s) to process")
    for doc in docs:
        try:
            extracted = extract_document(doc, window_chars=window_chars, max_windows=max_windows)
            old_facts = _file_facts(doc["file_id"]) if track_changes else []
            db.clear_chunk_graph_data(doc["rep_chunk_id"])
            ctx = {"file_id": doc["file_id"], "chunk_id": doc["rep_chunk_id"], "section_id": None}
            ids_by_key = _persist_entities(ctx, extracted.get("entities", []))
            rel = _persist_relationships(ctx, extracted.get("relationships", []), ids_by_key)
            facts = _persist_facts(ctx, extracted.get("facts", []), ids_by_key)
            entity_count += len(ids_by_key)
            relationship_count += rel
            fact_count += facts
            if track_changes and old_facts:
                _record_fact_diff(doc["file_id"], old_facts)
            db.mark_graph_chunk_extracted(doc["rep_chunk_id"], doc["content_hash"], DOC_EXTRACTOR_VERSION)
            processed += 1
            console.log(
                f"[green][{processed}/{total}][/green] {doc['file_name']} — "
                f"{len(ids_by_key)} ent, {rel} rel, {facts} facts"
            )
        except Exception as e:
            failed += 1
            db.mark_graph_chunk_extracted(
                doc["rep_chunk_id"], doc["content_hash"], DOC_EXTRACTOR_VERSION,
                status="failed", error_message=f"{type(e).__name__}: {e}",
            )
            console.log(f"[red][{processed + failed}/{total}] FAILED[/red] {doc['file_name']}: {e}")
    db.cleanup_orphan_graph_rows()
    snapshot = build_and_save_snapshot(folder=folder) if rebuild_snapshot else None
    return {
        "folder": folder,
        "processed_documents": processed,
        "failed_documents": failed,
        "entities_seen": entity_count,
        "relationships_seen": relationship_count,
        "facts_seen": fact_count,
        "snapshot": snapshot,
    }


def _change_tracking_enabled() -> bool:
    try:
        from career_history import intel_db
        return intel_db.table_exists("project_changes")
    except Exception:  # noqa: BLE001
        return False


def _file_facts(file_id: int) -> list[dict[str, Any]]:
    from career_history import intel_db
    try:
        return intel_db.facts_for_file(file_id)
    except Exception:  # noqa: BLE001
        return []


def _record_fact_diff(file_id: int, old_facts: list[dict[str, Any]]) -> None:
    from career_history import changes
    try:
        changes.record_fact_diff(file_id, old_facts, _file_facts(file_id), EXTRACTOR_VERSION)
    except Exception as e:  # noqa: BLE001
        console.log(f"[yellow]Fact diff skipped for file {file_id}:[/yellow] {e}")


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
    max_chars: int = MAX_CHUNK_CHARS,
) -> dict[str, list[dict[str, Any]]]:
    text = str(chunk.get("content") or "")[:max_chars]
    context = {
        "file_name": chunk.get("file_name"),
        "folder": chunk.get("folder"),
        "section_path": chunk.get("section_path"),
        "metadata": chunk.get("metadata") or {},
    }
    parsed = _extract_with_ollama(text, context, include_relationships)
    return _normalize_extraction(parsed)


def _doc_window_settings() -> tuple[int, int]:
    models = config.get().get("models", {})
    try:
        window = int(models.get("graph_doc_window_chars") or MAX_DOC_CHARS)
        windows = int(models.get("graph_doc_max_windows") or MAX_DOC_WINDOWS)
    except (TypeError, ValueError):
        return MAX_DOC_CHARS, MAX_DOC_WINDOWS
    return max(2000, window), max(1, windows)


def split_windows(text: str, window_chars: int, max_windows: int) -> list[str]:
    """Split ``text`` into at most ``max_windows`` pieces of ~``window_chars``,
    breaking on a paragraph/sentence boundary near the end of each window."""
    text = text or ""
    out: list[str] = []
    pos = 0
    while pos < len(text) and len(out) < max_windows:
        end = min(len(text), pos + window_chars)
        if end < len(text):
            floor = pos + window_chars // 2
            cut = max(text.rfind("\n\n", floor, end), text.rfind(". ", floor, end))
            if cut > pos:
                end = cut + 1
        piece = text[pos:end].strip()
        if piece:
            out.append(piece)
        pos = end
    return out


def merge_extractions(parts: list[dict[str, list[dict[str, Any]]]]) -> dict[str, list[dict[str, Any]]]:
    """Merge per-window extractions: entities dedup by (name, type) keeping the
    highest confidence; relationships dedup by (source, type, target); facts dedup
    by (kind, statement)."""
    entities: dict[tuple[str, str], dict[str, Any]] = {}
    relationships: dict[tuple[str, str, str], dict[str, Any]] = {}
    facts: dict[tuple[str, str], dict[str, Any]] = {}
    for part in parts:
        for e in part.get("entities", []):
            if not isinstance(e, dict):
                continue
            key = (_entity_key(str(e.get("name") or "")), _normalize_type(e.get("type")))
            if not key[0]:
                continue
            prev = entities.get(key)
            if prev is None or (_float(e.get("confidence")) or 0) > (_float(prev.get("confidence")) or 0):
                if prev is not None:
                    e = {**e, "aliases": list({*prev.get("aliases", []), *e.get("aliases", [])})}
                entities[key] = e
        for r in part.get("relationships", []):
            if not isinstance(r, dict):
                continue
            key = (_entity_key(str(r.get("source") or "")), _normalize_relation(r.get("type")),
                   _entity_key(str(r.get("target") or "")))
            relationships.setdefault(key, r)
        for f in part.get("facts", []):
            if not isinstance(f, dict):
                continue
            key = (str(f.get("kind") or "").lower(), _entity_key(str(f.get("statement") or "")))
            facts.setdefault(key, f)
    return {
        "entities": list(entities.values()),
        "relationships": list(relationships.values()),
        "facts": list(facts.values()),
    }


def extract_document(
    doc: dict[str, Any],
    window_chars: int = MAX_DOC_CHARS,
    max_windows: int = MAX_DOC_WINDOWS,
) -> dict[str, list[dict[str, Any]]]:
    """Extract a whole file window-by-window and merge. A window that times out is
    retried once as two halves before giving up, so one slow call no longer fails
    the whole document."""
    windows = split_windows(str(doc.get("content") or ""), window_chars, max_windows)
    base = {"file_name": doc.get("file_name"), "folder": doc.get("folder"),
            "section_path": None, "metadata": {"file_type": doc.get("file_type")}}
    parts: list[dict[str, list[dict[str, Any]]]] = []
    errors: list[str] = []
    for i, window in enumerate(windows, start=1):
        chunk = {**base, "content": window,
                 "section_path": f"window {i}/{len(windows)}" if len(windows) > 1 else None}
        try:
            parts.append(extract_chunk(chunk, max_chars=window_chars))
        except (TimeoutError, RuntimeError) as e:
            if "timed out" not in str(e).lower() and not isinstance(e, TimeoutError):
                errors.append(str(e))
                continue
            half = max(2000, len(window) // 2)
            for sub in split_windows(window, half, 2):
                try:
                    parts.append(extract_chunk({**chunk, "content": sub}, max_chars=half))
                except Exception as sub_e:  # noqa: BLE001
                    errors.append(str(sub_e))
        except ValueError as e:
            errors.append(str(e))
    if not parts and errors:
        raise RuntimeError("; ".join(errors[:3]))
    return merge_extractions(parts)


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


def _persist_facts(
    chunk: dict[str, Any],
    facts: list[dict[str, Any]],
    ids_by_key: dict[tuple[str, str], int],
) -> int:
    """Persist typed facts, linking subject/object/project/owner to entities
    extracted in the same chunk, and ``supersedes`` to an earlier fact from the
    same extraction. One bad fact never fails the chunk."""
    count = 0
    ids_by_statement: dict[str, int] = {}
    for fact in normalize_facts(facts):
        attributes = fact["attributes"]
        owner_id = _resolve_fact_entity(fact.get("owner"), "person", ids_by_key)
        if fact.get("owner") and owner_id is None:
            attributes = {**attributes, "owner": fact["owner"]}
        try:
            fact_id = db.insert_fact(
                kind=fact["kind"],
                statement=fact["statement"],
                file_id=chunk["file_id"],
                chunk_id=chunk["chunk_id"],
                subject_entity_id=_resolve_fact_entity(fact.get("subject"), fact.get("subject_type"), ids_by_key),
                object_entity_id=_resolve_fact_entity(fact.get("object"), fact.get("object_type"), ids_by_key),
                project_entity_id=_resolve_fact_entity(fact.get("project"), "project", ids_by_key),
                attributes=attributes,
                occurred_at=fact["occurred_at"],
                source_quote=fact["quote"],
                confidence=fact["confidence"],
                extractor_version=EXTRACTOR_VERSION,
                topic=fact["topic"],
                status=fact["status"],
                priority=fact["priority"],
                owner_entity_id=owner_id,
                supersedes_fact_id=ids_by_statement.get(_entity_key(fact.get("supersedes") or "")),
            )
            ids_by_statement[_entity_key(fact["statement"])] = fact_id
            count += 1
        except Exception:
            continue
    return count


def normalize_facts(facts: list[Any]) -> list[dict[str, Any]]:
    """Validate and normalise raw LLM facts: known kind, non-empty statement,
    canonical status/priority, ISO dates, bounded confidence. Facts that name an
    earlier statement in ``supersedes`` are ordered after it."""
    out: list[dict[str, Any]] = []
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        kind = re.sub(r"[^a-z]+", "_", str(fact.get("kind") or "").strip().lower()).strip("_")
        kind = {"action": "action_item", "question": "open_question", "task": "action_item"}.get(kind, kind)
        statement = _clean_evidence(fact.get("statement"))
        if kind not in FACT_KINDS or not statement:
            continue
        attributes = fact.get("attributes") if isinstance(fact.get("attributes"), dict) else {}
        status = normalize_status(fact.get("status") or attributes.get("status"))
        if status is None and kind in {"action_item", "open_question", "risk", "commitment"}:
            status = "open"
        confidence = _float(fact.get("confidence")) or 0.6
        out.append({
            **fact,
            "kind": kind,
            "statement": statement,
            "attributes": attributes,
            "topic": (_clean_name(fact.get("topic")).lower()[:80] or None),
            "status": status,
            "priority": normalize_priority(fact.get("priority") or fact.get("severity")
                                           or attributes.get("priority") or attributes.get("severity")),
            "owner": _clean_name(fact.get("owner") or attributes.get("owner")) or None,
            "occurred_at": _clean_ts(fact.get("occurred_at") or attributes.get("due_at")
                                     if kind == "milestone" else fact.get("occurred_at")),
            "quote": _clean_evidence(fact.get("quote") or fact.get("evidence") or ""),
            "confidence": max(0.0, min(1.0, confidence)),
            "supersedes": _clean_evidence(fact.get("supersedes")) or None,
        })
    statements = {_entity_key(f["statement"]) for f in out}
    out.sort(key=lambda f: 1 if f["supersedes"] and _entity_key(f["supersedes"]) in statements else 0)
    return out


def normalize_status(value: Any) -> str | None:
    raw = re.sub(r"[_\-]+", " ", str(value or "").strip().lower())
    if not raw:
        return None
    if raw.replace(" ", "_") in FACT_STATUSES:
        return raw.replace(" ", "_")
    return _STATUS_ALIASES.get(raw)


def normalize_priority(value: Any) -> str | None:
    return _PRIORITY_ALIASES.get(str(value or "").strip().lower())


_MEETING_RE = re.compile(r"meeting|minutes|\bmom\b|notes|standup|stand-up|sync|call|workshop|retro", re.I)
_CONTRACT_RE = re.compile(r"proposal|\bsow\b|statement of work|\brfp\b|\brfq\b|tender|contract|quotation|\bbrd\b|\bprd\b|requirement|spec", re.I)
_RAID_RE = re.compile(r"raid|risk|issue|action|tracker|log|register|plan|schedule|timeline", re.I)


def doc_type_hint(file_type: Any, file_name: Any) -> str:
    """One extraction hint keyed off the file type and name, so a slide deck, a
    RAID log and meeting minutes each get asked for the facts they actually hold."""
    ft = str(file_type or "").lower().lstrip(".")
    name = str(file_name or "")
    if ft in {"mp3", "m4a", "wav", "aac", "flac", "ogg", "mp4", "mov"} or _MEETING_RE.search(name):
        return ("Meeting record: extract decisions (with alternatives and rationale), action items "
                "with owner and due date, open questions, risks raised and commitments.")
    if ft in {"xlsx", "xls", "csv", "numbers"}:
        if _RAID_RE.search(name):
            return ("Tracker / RAID log: each row is usually one risk, issue, action item, dependency or "
                    "milestone. Map columns such as Owner, Status, Due, Priority/Severity, Mitigation.")
        return ("Spreadsheet: rows may be requirements, estimates, milestones or a plan; map Owner, "
                "Status, Due and Priority columns when present.")
    if ft in {"pptx", "ppt", "key"}:
        return ("Slide deck: slide titles are topics. Extract objectives, scope, requirements, "
                "milestones, proposed decisions, risks and dependencies.")
    if name.lower().startswith("readme") or ft in {"py", "js", "ts", "yaml", "yml", "json"}:
        return "Technical README / config: extract technologies, components, dependencies and requirements."
    if _CONTRACT_RE.search(name):
        return ("Proposal / contract / requirements document: extract requirements, deliverables, "
                "milestones, commitments, assumptions (as dependencies) and risks.")
    return ("Document: extract decisions, requirements, risks, action items, open questions, "
            "dependencies and milestones that the text states explicitly.")


def _resolve_fact_entity(
    name: Any,
    type_hint: Any,
    ids_by_key: dict[tuple[str, str], int],
) -> int | None:
    """Map a fact participant name to an entity id extracted in the same chunk."""
    cleaned = _clean_name(name)
    if not cleaned:
        return None
    key = _entity_key(cleaned)
    if type_hint:
        hinted = ids_by_key.get((key, _normalize_type(type_hint)))
        if hinted is not None:
            return hinted
    for (k, _t), entity_id in ids_by_key.items():
        if k == key:
            return entity_id
    return None


def _clean_ts(value: Any) -> str | None:
    """Return a YYYY-MM-DD date if one is present in the value, else None."""
    if not value:
        return None
    match = _DATE_RE.search(str(value))
    return match.group(0) if match else None


def _extraction_timeout() -> int:
    """Read timeout (s) for one extraction LLM call. Local models on long
    document-level prompts can take minutes, so the default is generous. Override
    with models.graph_extraction_timeout in config.yaml or ERA_GRAPH_EXTRACTION_TIMEOUT."""
    raw = (
        os.environ.get("ERA_GRAPH_EXTRACTION_TIMEOUT")
        or config.get().get("models", {}).get("graph_extraction_timeout")
    )
    try:
        return int(raw) if raw else 600
    except (TypeError, ValueError):
        return 600


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
        **ollama_json_options(),
    }
    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_extraction_timeout()) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e
    return _loads_json_object(body.get("response") or "{}")


def ollama_json_options() -> dict[str, Any]:
    """Shared Ollama settings for JSON extraction calls. Thinking models (gemma4,
    qwen3.5) otherwise reason until the read timeout (a 12k-char window timed out
    after 30 min); the default context can silently truncate a window; and an
    uncapped num_predict lets a model loop instead of closing the JSON."""
    models = config.get().get("models", {})
    return {
        "think": bool(models.get("graph_extraction_think", False)),
        "keep_alive": models.get("graph_keep_alive", "30m"),
        "options": {
            "temperature": 0,
            "num_ctx": int(models.get("graph_num_ctx", 16384)),
            "num_predict": int(models.get("graph_num_predict", 4096)),
        },
    }


def _prompt(text: str, context: dict[str, Any], include_relationships: bool) -> str:
    relationship_instruction = (
        "Extract relationships only when the chunk explicitly supports them."
        if include_relationships else "Return an empty relationships array."
    )
    meta = context.get("metadata") or {}
    hint = doc_type_hint(meta.get("file_type"), context.get("file_name"))
    entity_types = "|".join(sorted(ENTITY_TYPES - {"document"}))
    return f"""
Extract a compact, provenance-ready project knowledge graph from this KB chunk.

Allowed entity types: {", ".join(sorted(ENTITY_TYPES - {"document"}))}.
Allowed relationship types: {", ".join(sorted(RELATIONSHIP_TYPES))}.
Fact kinds: {", ".join(sorted(FACT_KINDS))}.
Source hint: {hint}

Rules:
- Return only valid JSON.
- Keep entity names canonical and short. Use "client" for the customer an
  engagement is for, "vendor" for suppliers/partners, "deliverable" for named outputs.
- Do not invent facts beyond the text. Every fact needs a short verbatim quote.
- Every relationship must include a short evidence quote from the chunk.
- {relationship_instruction}
- Fact kinds:
  decision      = something decided; attributes: alternatives[], rationale, impact, decided_by
  commitment    = a promise (who owes what to whom, by when); attributes: due_at, direction (owed_by_me|owed_to_me), counterparty
  event         = something that happened on a date (occurred_at)
  requirement   = something the solution must do or satisfy; attributes: source, acceptance_criteria
  risk          = a possible problem; priority = severity; attributes: likelihood, impact, mitigation
  action_item   = a task; owner = who does it; attributes: due_at
  open_question = an unresolved question; owner = who must answer
  dependency    = subject depends on object (team, vendor, system, approval); attributes: dependency_type
  milestone     = a planned or reached checkpoint; occurred_at = target/actual date
- topic: 1-4 lowercase words naming what the fact is about (e.g. "data migration",
  "budget", "go-live"), so facts about the same thing can be compared.
- status: one of {", ".join(sorted(FACT_STATUSES))}; omit if unstated.
- priority: high|medium|low when stated or clearly implied (severity for risks).
- supersedes: the exact statement of an earlier fact in this same output that
  this fact replaces (e.g. a revised date or reversed decision), else omit.
- Reference entity names that also appear in "entities"; leave subject/object/
  project/owner empty if unclear. Return empty arrays when nothing is explicit.

Context:
{json.dumps(context, ensure_ascii=False)}

JSON schema:
{{
  "entities": [
    {{"name": "string", "type": "{entity_types}", "aliases": [], "mention_text": "string", "confidence": 0.0}}
  ],
  "relationships": [
    {{"source": "entity name", "source_type": "entity type", "target": "entity name", "target_type": "entity type", "type": "{"|".join(sorted(RELATIONSHIP_TYPES))}", "evidence": "short quote", "confidence": 0.0}}
  ],
  "facts": [
    {{"kind": "{"|".join(sorted(FACT_KINDS))}", "statement": "string", "topic": "string", "status": "string", "priority": "high|medium|low", "owner": "person name", "subject": "entity name", "object": "entity name", "project": "project name", "supersedes": "earlier statement", "attributes": {{}}, "occurred_at": "YYYY-MM-DD", "quote": "short verbatim quote", "confidence": 0.0}}
  ]
}}

Chunk:
\"\"\"{text}\"\"\"
""".strip()


def _normalize_extraction(parsed: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        "entities": parsed.get("entities", []) if isinstance(parsed.get("entities"), list) else [],
        "relationships": parsed.get("relationships", []) if isinstance(parsed.get("relationships"), list) else [],
        "facts": parsed.get("facts", []) if isinstance(parsed.get("facts"), list) else [],
    }


_BAD_ESCAPE_RE = re.compile(r'\\(?!["\\/bfnrtu])')
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def repair_json(raw: str) -> str:
    """Fix the malformations local models commonly emit: invalid backslash
    escapes (Windows paths, LaTeX) and trailing commas before ``}``/``]``."""
    fixed = _BAD_ESCAPE_RE.sub(r"\\\\", raw)
    return _TRAILING_COMMA_RE.sub(r"\1", fixed)


def _loads_json_object(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    end = raw.rfind("}")
    body = raw[start:end + 1] if 0 <= start < end else raw
    value: Any = None
    last_error: Exception | None = None
    for candidate in (raw, body, repair_json(body)):
        try:
            value = json.loads(candidate, strict=False)
            break
        except json.JSONDecodeError as e:
            last_error = e
    else:
        raise last_error or ValueError("unparseable JSON")
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
