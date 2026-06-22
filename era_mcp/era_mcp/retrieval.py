"""Retrieval layer: embed a query via Ollama, search pgvector, return results."""
from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from era_mcp import config

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(config.database_url(), pool_pre_ping=True, future=True)
    return _engine


def _vec_literal(v: list[float]) -> str:
    """Format a Python list as a pgvector literal: '[1,2,3]'."""
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


_parent_chunks_available_cache: bool | None = None


def _parent_chunks_available() -> bool:
    """Whether the parent_chunks table exists (migration 0004). Cached so the
    check runs once per process; retrieval degrades to chunk-level context when
    absent (schema drift safe)."""
    global _parent_chunks_available_cache
    if _parent_chunks_available_cache is None:
        try:
            with _get_engine().connect() as conn:
                exists = conn.execute(
                    text("SELECT to_regclass('public.parent_chunks')")
                ).scalar()
            _parent_chunks_available_cache = exists is not None
        except Exception:
            _parent_chunks_available_cache = False
    return _parent_chunks_available_cache


async def embed_query(text_input: str) -> list[float]:
    """Embed a single query string via the Ollama HTTP API."""
    url = f"{config.ollama_base_url()}/api/embed"
    payload = {"model": config.embedding_model(), "input": text_input}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["embeddings"][0]


def search(
    query: str,
    query_embedding: list[float],
    top_k: int | None = None,
    folder: str | None = None,
    kind: str | None = None,
    context_window: int = 3,
) -> list[dict[str, Any]]:
    """Hybrid search over document_chunks: dense vector + lexical full-text,
    fused with Reciprocal Rank Fusion (RRF).

    Two candidate channels are pulled independently -- the top
    ``candidate_pool`` chunks by cosine similarity and the top
    ``candidate_pool`` chunks by full-text ``ts_rank`` (using the same
    ``'simple'`` config the index was built with) -- then merged by RRF
    score ``sum(1 / (rrf_k + rank))``. Pure-vector hits (e.g. legacy chunks
    with no ``search_vector``, or queries with no lexical match) still surface
    through the vector channel.

    Returns a list of result dicts with content, metadata, file info, cosine
    ``similarity`` (None for FTS-only hits), ``rrf_score``, and optional
    speaker attribution. When ``context_window`` > 0, surrounding chunks from
    the same file are merged in so the LLM gets broader context.
    """
    if top_k is None:
        top_k = config.default_top_k()

    vec = _vec_literal(query_embedding)
    cand = max(config.candidate_pool(), top_k)

    conditions = []
    params: dict[str, Any] = {
        "qvec": vec,
        "qtext": query or "",
        "top_k": top_k,
        "cand": cand,
        "rrf_k": config.rrf_k(),
        "w_vec": config.rrf_vector_weight(),
        "w_fts": config.rrf_fts_weight(),
    }

    if folder:
        conditions.append("fr.folder = :folder")
        params["folder"] = folder
    if kind:
        conditions.append("dc.metadata->>'kind' = :kind")
        params["kind"] = kind

    where = (" AND ".join(conditions)) if conditions else "TRUE"

    use_parent = config.parent_context_enabled() and _parent_chunks_available()
    # When collapsing children to parents, pull a deeper pool so the final list
    # still contains ~top_k distinct parents after de-duplication.
    final_limit = min(cand, top_k * 3) if use_parent else top_k
    params["final_limit"] = final_limit
    parent_select = (
        "pc.content AS parent_content, dc.parent_chunk_id AS parent_chunk_id"
        if use_parent else
        "NULL AS parent_content, NULL AS parent_chunk_id"
    )
    parent_join = (
        "LEFT JOIN parent_chunks pc ON pc.id = dc.parent_chunk_id"
        if use_parent else ""
    )

    sql = text(f"""
        WITH vec AS (
            SELECT dc.id AS chunk_pk,
                   ROW_NUMBER() OVER (
                       ORDER BY dc.embedding <=> CAST(:qvec AS vector)
                   ) AS rank,
                   1 - (dc.embedding <=> CAST(:qvec AS vector)) AS similarity
              FROM document_chunks dc
              JOIN file_registry fr ON dc.file_id = fr.id
             WHERE dc.embedding IS NOT NULL AND {where}
             ORDER BY dc.embedding <=> CAST(:qvec AS vector)
             LIMIT :cand
        ),
        fts AS (
            SELECT dc.id AS chunk_pk,
                   ROW_NUMBER() OVER (
                       ORDER BY ts_rank(
                           dc.search_vector,
                           websearch_to_tsquery('simple', :qtext)
                       ) DESC
                   ) AS rank
              FROM document_chunks dc
              JOIN file_registry fr ON dc.file_id = fr.id
             WHERE dc.search_vector @@ websearch_to_tsquery('simple', :qtext)
               AND {where}
             ORDER BY ts_rank(
                 dc.search_vector,
                 websearch_to_tsquery('simple', :qtext)
             ) DESC
             LIMIT :cand
        ),
        fused AS (
            SELECT COALESCE(v.chunk_pk, f.chunk_pk) AS chunk_pk,
                   COALESCE(:w_vec / (:rrf_k + v.rank), 0)
                       + COALESCE(:w_fts / (:rrf_k + f.rank), 0) AS rrf_score,
                   v.similarity AS similarity
              FROM vec v
              FULL OUTER JOIN fts f ON v.chunk_pk = f.chunk_pk
        )
        SELECT dc.content,
               dc.metadata,
               dc.file_id,
               dc.chunk_index,
               fr.file_name,
               fr.file_path,
               fr.folder,
               fr.is_audio,
               fused.similarity,
               ss.speaker_label,
               ss.start_time,
               ss.end_time,
               fused.rrf_score,
               {parent_select}
          FROM fused
          JOIN document_chunks dc ON dc.id = fused.chunk_pk
          JOIN file_registry fr ON dc.file_id = fr.id
          LEFT JOIN speaker_segments ss ON dc.speaker_segment_id = ss.id
          {parent_join}
         ORDER BY fused.rrf_score DESC, fused.similarity DESC NULLS LAST
         LIMIT :final_limit
    """)

    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql, params).fetchall()

        hits = []
        for row in rows:
            entry: dict[str, Any] = {
                "content": row[0],
                "file_id": row[2],
                "chunk_index": row[3],
                "file_name": row[4],
                "file_path": row[5],
                "folder": row[6],
                "is_audio": row[7],
                "similarity": round(float(row[8]), 4) if row[8] is not None else None,
                "rrf_score": round(float(row[12]), 6),
                "metadata": row[1],
                "parent_content": row[13],
                "parent_chunk_id": row[14],
            }
            if row[9] is not None:
                entry["speaker"] = row[9]
                entry["start_time"] = float(row[10])
                entry["end_time"] = float(row[11])
            hits.append(entry)

        if not hits:
            return []

        # Parent-child ("small-to-big"): return the larger parent chunk as
        # context, de-duplicated so each parent appears once even when several
        # of its children matched. Children without a parent (audio, flat docs)
        # fall back to chunk-level neighbor-window expansion.
        if use_parent:
            return _collapse_to_parents(hits, top_k, context_window, conn)

        if context_window <= 0:
            results = []
            for hit in hits[:top_k]:
                results.append(_chunk_result(hit, hit["content"], hit["chunk_index"], None))
            return results

        results = []
        for hit in hits[:top_k]:
            merged, rng = _neighbor_window(conn, hit, context_window)
            results.append(_chunk_result(hit, merged, hit["chunk_index"], rng))
        return results


def _chunk_result(
    hit: dict[str, Any],
    content: str,
    matched_index: int | None,
    context_range: list[int] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": content,
        "file_name": hit["file_name"],
        "file_path": hit["file_path"],
        "folder": hit["folder"],
        "is_audio": hit["is_audio"],
        "similarity": hit["similarity"],
        "rrf_score": hit["rrf_score"],
        "metadata": hit["metadata"],
    }
    if matched_index is not None:
        result["matched_chunk_index"] = matched_index
    if context_range is not None:
        result["context_range"] = context_range
    if "speaker" in hit:
        result["speaker"] = hit["speaker"]
        result["start_time"] = hit["start_time"]
        result["end_time"] = hit["end_time"]
    return result


def _neighbor_window(
    conn: Any, hit: dict[str, Any], context_window: int
) -> tuple[str, list[int]]:
    cidx = hit["chunk_index"]
    ctx_rows = conn.execute(text("""
        SELECT chunk_index, content
          FROM document_chunks
         WHERE file_id = :fid
           AND chunk_index BETWEEN :low AND :high
         ORDER BY chunk_index
    """), {
        "fid": hit["file_id"],
        "low": max(0, cidx - context_window),
        "high": cidx + context_window,
    }).fetchall()
    if not ctx_rows:
        return hit["content"], [cidx, cidx]
    merged = "\n\n".join(r[1] for r in ctx_rows)
    return merged, [ctx_rows[0][0], ctx_rows[-1][0]]


def _collapse_to_parents(
    hits: list[dict[str, Any]],
    top_k: int,
    context_window: int,
    conn: Any,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_parents: dict[int, dict[str, Any]] = {}
    for hit in hits:
        if len(results) >= top_k:
            break
        pid = hit.get("parent_chunk_id")
        if pid is not None and hit.get("parent_content"):
            if pid in seen_parents:
                # Another child of an already-returned parent matched; record it.
                seen_parents[pid].setdefault("also_matched_chunks", []).append(
                    hit["chunk_index"]
                )
                continue
            result = _chunk_result(
                hit, hit["parent_content"], hit["chunk_index"], None
            )
            result["parent_chunk_id"] = pid
            seen_parents[pid] = result
            results.append(result)
        else:
            # No parent (audio / flat docs): chunk-level context.
            if context_window > 0:
                merged, rng = _neighbor_window(conn, hit, context_window)
                results.append(_chunk_result(hit, merged, hit["chunk_index"], rng))
            else:
                results.append(
                    _chunk_result(hit, hit["content"], hit["chunk_index"], None)
                )
    return results


def status_summary(folder: str | None = None) -> dict[str, int]:
    """Counts per processing status, optionally scoped to a folder."""
    params: dict[str, Any] = {}
    where = ""
    if folder:
        where = "WHERE fr.folder = :folder"
        params["folder"] = folder

    sql = text(f"""
        SELECT pq.status, COUNT(*) AS n
          FROM processing_queue pq
          JOIN file_registry fr ON fr.id = pq.file_id
         {where}
         GROUP BY pq.status
    """)

    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {row[0]: row[1] for row in rows}


def list_folders() -> list[str]:
    """Return all distinct top-level folders in the file registry."""
    sql = text("SELECT DISTINCT folder FROM file_registry ORDER BY folder")
    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [row[0] for row in rows]


def graph_snapshot(scope: str = "all") -> dict[str, Any] | None:
    """Return the latest Sigma.js graph snapshot for a scope."""
    sql = text("""
        SELECT id, scope, source_hash, extraction_version, payload,
               node_count, edge_count, created_at
          FROM graph_snapshots
         WHERE scope = :scope
           AND is_current = true
         ORDER BY created_at DESC
         LIMIT 1
    """)
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(sql, {"scope": scope}).fetchone()
    if row is None:
        return None
    result = dict(row._mapping)
    result["created_at"] = result["created_at"].isoformat()
    return result


def graph_status(scope: str = "all") -> dict[str, Any]:
    """Return graph extraction and snapshot status."""
    engine = _get_engine()
    with engine.connect() as conn:
        state_rows = conn.execute(text("""
            SELECT status, COUNT(*) AS n
              FROM graph_extraction_state
             GROUP BY status
        """)).fetchall()
        snapshot = conn.execute(text("""
            SELECT id, scope, source_hash, extraction_version,
                   node_count, edge_count, created_at
              FROM graph_snapshots
             WHERE scope = :scope
               AND is_current = true
             ORDER BY created_at DESC
             LIMIT 1
        """), {"scope": scope}).fetchone()

    snapshot_dict = dict(snapshot._mapping) if snapshot else None
    if snapshot_dict:
        snapshot_dict["created_at"] = snapshot_dict["created_at"].isoformat()
    return {
        "scope": scope,
        "extraction": {row[0]: row[1] for row in state_rows},
        "snapshot": snapshot_dict,
    }


def search_entities(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search canonical entities and aliases.

    Matches the deployed schema (no mention_count/node_weight columns; those
    arrive with migration 0003). Ranks by how many files mention the entity,
    derived live from entity_mentions, falling back to the entity name.
    """
    like = f"%{query}%"
    sql = text("""
        SELECT e.id, e.canonical_name, e.entity_type, e.aliases, e.metadata,
               COUNT(DISTINCT em.file_id) AS file_count
          FROM entities e
          LEFT JOIN entity_mentions em ON em.entity_id = e.id
         WHERE e.canonical_name ILIKE :like
            OR e.aliases::text ILIKE :like
         GROUP BY e.id, e.canonical_name, e.entity_type, e.aliases, e.metadata
         ORDER BY file_count DESC, e.canonical_name
         LIMIT :limit
    """)
    with _get_engine().connect() as conn:
        rows = conn.execute(sql, {"like": like, "limit": limit}).fetchall()
    return [dict(row._mapping) for row in rows]


def search_relationships(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search typed relationships and evidence.

    Matches the deployed schema (no edge_weight/evidence_count columns; those
    arrive with migration 0003). Ranks by confidence and tolerates an empty
    relationship_evidence table.
    """
    like = f"%{query}%"
    sql = text("""
        SELECT r.id,
               se.canonical_name AS source,
               se.entity_type AS source_type,
               r.relationship_type,
               te.canonical_name AS target,
               te.entity_type AS target_type,
               r.confidence,
               jsonb_agg(DISTINCT jsonb_build_object(
                    'file_id', re.file_id,
                    'chunk_id', re.chunk_id,
                    'section_id', re.section_id,
                    'evidence_text', re.evidence_text
               )) FILTER (WHERE re.id IS NOT NULL) AS evidence
          FROM relationships r
          JOIN entities se ON se.id = r.source_entity_id
          JOIN entities te ON te.id = r.target_entity_id
          LEFT JOIN relationship_evidence re ON re.relationship_id = r.id
         WHERE se.canonical_name ILIKE :like
            OR te.canonical_name ILIKE :like
            OR r.relationship_type ILIKE :like
            OR re.evidence_text ILIKE :like
         GROUP BY r.id, se.canonical_name, se.entity_type,
                  r.relationship_type, te.canonical_name, te.entity_type,
                  r.confidence
         ORDER BY r.confidence DESC NULLS LAST
         LIMIT :limit
    """)
    with _get_engine().connect() as conn:
        rows = conn.execute(sql, {"like": like, "limit": limit}).fetchall()
    return [dict(row._mapping) for row in rows]


def search_communities(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search community summaries and members.

    The communities/community_members tables only exist after migration 0003.
    When they are absent (current deployed schema), return an empty list
    instead of erroring.
    """
    like = f"%{query}%"
    with _get_engine().connect() as conn:
        if conn.execute(text("SELECT to_regclass('public.communities')")).scalar() is None:
            return []
        sql = text("""
            SELECT c.id, c.name, c.summary, c.algorithm, c.algorithm_version,
                   COUNT(cm.id) AS member_count
              FROM communities c
              LEFT JOIN community_members cm ON cm.community_id = c.id
              LEFT JOIN entities e ON e.id = cm.entity_id
             WHERE c.name ILIKE :like
                OR c.summary ILIKE :like
                OR e.canonical_name ILIKE :like
             GROUP BY c.id, c.name, c.summary, c.algorithm, c.algorithm_version
             ORDER BY member_count DESC, c.name
             LIMIT :limit
        """)
        rows = conn.execute(sql, {"like": like, "limit": limit}).fetchall()
    return [dict(row._mapping) for row in rows]


def get_document_summary(file_id: int | None = None, file_name: str | None = None) -> dict[str, Any] | None:
    """Return the latest document summary for a file id or name fragment."""
    conditions = []
    params: dict[str, Any] = {}
    if file_id is not None:
        conditions.append("fr.id = :file_id")
        params["file_id"] = file_id
    if file_name:
        conditions.append("fr.file_name ILIKE :file_name")
        params["file_name"] = f"%{file_name}%"
    where = " OR ".join(conditions) if conditions else "TRUE"
    sql = text(f"""
        SELECT ds.id, ds.file_id, fr.file_name, fr.folder, ds.summary,
               ds.model, ds.prompt_version, ds.source_hash, ds.metadata,
               ds.created_at
          FROM document_summaries ds
          JOIN file_registry fr ON fr.id = ds.file_id
         WHERE {where}
         ORDER BY ds.created_at DESC
         LIMIT 1
    """)
    with _get_engine().connect() as conn:
        row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    out = dict(row._mapping)
    out["created_at"] = out["created_at"].isoformat()
    return out


def get_section_summary(section_id: int) -> dict[str, Any] | None:
    """Return the latest section summary."""
    sql = text("""
        SELECT ss.id, ss.section_id, ss.file_id, fr.file_name,
               ds.section_path, ss.summary, ss.model, ss.prompt_version,
               ss.source_hash, ss.metadata, ss.created_at
          FROM section_summaries ss
          JOIN file_registry fr ON fr.id = ss.file_id
          JOIN document_sections ds ON ds.id = ss.section_id
         WHERE ss.section_id = :section_id
         ORDER BY ss.created_at DESC
         LIMIT 1
    """)
    with _get_engine().connect() as conn:
        row = conn.execute(sql, {"section_id": section_id}).fetchone()
    if row is None:
        return None
    out = dict(row._mapping)
    out["created_at"] = out["created_at"].isoformat()
    return out


def get_entity_neighbors(entity_id: int, limit: int = 25) -> dict[str, Any]:
    """Return graph neighbors and evidence for one entity."""
    sql_entity = text("""
        SELECT id, canonical_name, entity_type, aliases, metadata
          FROM entities
         WHERE id = :entity_id
    """)
    sql_edges = text("""
        SELECT r.id,
               r.source_entity_id,
               se.canonical_name AS source,
               r.relationship_type,
               r.target_entity_id,
               te.canonical_name AS target,
               r.confidence
          FROM relationships r
          JOIN entities se ON se.id = r.source_entity_id
          JOIN entities te ON te.id = r.target_entity_id
         WHERE r.source_entity_id = :entity_id
            OR r.target_entity_id = :entity_id
         ORDER BY r.confidence DESC NULLS LAST
         LIMIT :limit
    """)
    with _get_engine().connect() as conn:
        entity = conn.execute(sql_entity, {"entity_id": entity_id}).fetchone()
        edges = conn.execute(sql_edges, {
            "entity_id": entity_id,
            "limit": limit,
        }).fetchall()
    return {
        "entity": dict(entity._mapping) if entity else None,
        "relationships": [dict(row._mapping) for row in edges],
    }


def get_graph_subgraph(
    entity_id: int | None = None,
    scope: str = "all",
    limit: int = 100,
) -> dict[str, Any]:
    """Return a graph export, optionally narrowed to one entity neighborhood."""
    snapshot = graph_snapshot(scope=scope)
    if snapshot is None:
        return {"nodes": [], "edges": [], "metadata": {"scope": scope}}
    payload = snapshot["payload"]
    if entity_id is None:
        return payload

    center = f"entity:{entity_id}"
    related = {center}
    edges = []
    for edge in payload.get("edges", []):
        if edge.get("source") == center or edge.get("target") == center:
            related.add(edge["source"])
            related.add(edge["target"])
            edges.append(edge)
            if len(edges) >= limit:
                break
    nodes = [
        node for node in payload.get("nodes", [])
        if node.get("key") in related or node.get("id") in related
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "scope": scope,
            "center_entity_id": entity_id,
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
    }


def _safe(fn, default):
    """Run a graph/summary channel, degrading to ``default`` if its backing
    table or columns are missing (schema drift) rather than failing the
    whole knowledge packet."""
    try:
        return fn()
    except Exception:
        return default


def knowledge_search(
    query: str,
    query_embedding: list[float],
    top_k: int | None = None,
    folder: str | None = None,
) -> dict[str, Any]:
    """Return a V3 knowledge packet, not just similar chunks.

    Hybrid chunk retrieval is the always-on backbone. The graph and summary
    channels are best-effort: until the knowledge graph is populated (Phase 2),
    they degrade to empty lists instead of erroring.
    """
    if top_k is None:
        top_k = config.default_top_k()
    chunks = search(
        query=query,
        query_embedding=query_embedding,
        top_k=top_k,
        folder=folder,
        context_window=2,
    )
    entities = _safe(lambda: search_entities(query, limit=top_k), [])
    relationships = _safe(lambda: search_relationships(query, limit=top_k), [])
    communities = _safe(lambda: search_communities(query, limit=top_k), [])
    summaries = []
    for hit in chunks[:top_k]:
        summary = _safe(lambda: get_document_summary(file_name=hit.get("file_name")), None)
        if summary:
            summaries.append(summary)
    return {
        "query": query,
        "intent": {
            "mode": "knowledge_packet",
            "channels": [
                "vector_chunks",
                "entities",
                "relationships",
                "communities",
                "summaries",
            ],
        },
        "document_summaries": summaries,
        "entities": entities,
        "relationships": relationships,
        "communities": communities,
        "supporting_chunks": chunks,
        "provenance": {
            "folder": folder,
            "top_k": top_k,
        },
    }
