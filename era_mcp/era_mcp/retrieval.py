"""Retrieval layer: embed a query via Ollama, search pgvector, return results."""
from __future__ import annotations

import asyncio
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
    """Embed a single query string via the Ollama HTTP API.

    qwen3-embedding is instruction-tuned: the query is wrapped with a task
    instruction while the indexer embeds documents raw. This query/document
    asymmetry matches how the model was trained and improves retrieval; toggle
    via QUERY_INSTRUCTION_ENABLED (off for non-instruction models like bge-m3).
    """
    text_to_embed = text_input
    if config.query_instruction_enabled():
        text_to_embed = f"Instruct: {config.query_instruction()}\nQuery: {text_input}"
    url = f"{config.ollama_base_url()}/api/embed"
    payload = {"model": config.embedding_model(), "input": text_to_embed}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["embeddings"][0]


def _use_parent() -> bool:
    """Whether to collapse matched children to parent chunks ("small-to-big")."""
    return config.parent_context_enabled() and _parent_chunks_available()


def _fused_candidates(
    query: str,
    query_embedding: list[float],
    folder: str | None,
    kind: str | None,
    cand: int,
    limit: int,
    use_parent: bool,
) -> list[dict[str, Any]]:
    """Fetch the RRF-fused candidate pool (dense vector + lexical full-text).

    Two channels are pulled independently -- the top ``cand`` chunks by cosine
    similarity and the top ``cand`` by full-text ``ts_rank`` (same ``'simple'``
    config the index was built with) -- then merged by RRF score
    ``sum(1 / (rrf_k + rank))`` and returned (up to ``limit``) ordered by that
    score, WITHOUT parent/neighbor expansion. Shared by the sync ``search`` path
    and the async rerank path (``search_async``).
    """
    vec = _vec_literal(query_embedding)

    conditions = []
    params: dict[str, Any] = {
        "qvec": vec,
        "qtext": query or "",
        "cand": cand,
        "rrf_k": config.rrf_k(),
        "w_vec": config.rrf_vector_weight(),
        "w_fts": config.rrf_fts_weight(),
        "final_limit": limit,
    }

    if folder:
        conditions.append("fr.folder = :folder")
        params["folder"] = folder
    if kind:
        conditions.append("dc.metadata->>'kind' = :kind")
        params["kind"] = kind

    where = (" AND ".join(conditions)) if conditions else "TRUE"

    # Lexical channel: optionally also match file_name + folder + file_path, not
    # just the chunk body, so short queries (acronyms, customer names, RFP ids)
    # hit the path a file was filed under even when the body never spells them
    # out. translate() turns '01_IBF' / 'a-b.pdf' separators into spaces so the
    # 'simple' tokenizer emits 'ibf' / 'a' / 'b' / 'pdf'.
    if config.filename_search_enabled():
        _path_tsv = (
            "to_tsvector('simple', translate("
            "coalesce(fr.file_name,'') || ' ' || coalesce(fr.folder,'') || ' ' "
            "|| coalesce(fr.file_path,''), '_/.-', '    '))"
        )
        fts_where = (
            "(dc.search_vector @@ websearch_to_tsquery('simple', :qtext) "
            f"OR {_path_tsv} @@ websearch_to_tsquery('simple', :qtext))"
        )
        fts_rank = (
            "ts_rank(dc.search_vector, websearch_to_tsquery('simple', :qtext)) "
            f"+ :w_path * ts_rank({_path_tsv}, websearch_to_tsquery('simple', :qtext))"
        )
        params["w_path"] = config.lexical_path_weight()
    else:
        fts_where = "dc.search_vector @@ websearch_to_tsquery('simple', :qtext)"
        fts_rank = "ts_rank(dc.search_vector, websearch_to_tsquery('simple', :qtext))"

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
                   ROW_NUMBER() OVER (ORDER BY ({fts_rank}) DESC) AS rank
              FROM document_chunks dc
              JOIN file_registry fr ON dc.file_id = fr.id
             WHERE ({fts_where})
               AND {where}
             ORDER BY ({fts_rank}) DESC
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
    return hits


def _expand_winners(
    hits: list[dict[str, Any]],
    top_k: int,
    context_window: int,
    use_parent: bool,
    doc_first: bool = False,
) -> list[dict[str, Any]]:
    """Expand the chosen candidates to full context.

    Parent-child ("small-to-big"): return the larger parent chunk, de-duplicated
    so each parent appears once even when several of its children matched.
    Children without a parent (audio, flat docs) fall back to chunk-level
    neighbor-window expansion.

    When ``doc_first`` (the /ask path), passages are grouped by document and
    ordered document-by-document instead of as a flat scattered list, so the
    synthesis model sees coherent documents. /search keeps the flat behavior.
    """
    if not hits:
        return []
    engine = _get_engine()
    with engine.connect() as conn:
        if doc_first:
            return _assemble_document_first(
                hits, top_k, context_window, use_parent, conn
            )
        if use_parent:
            return _collapse_to_parents(hits, top_k, context_window, conn)
        if context_window <= 0:
            return [
                _chunk_result(hit, hit["content"], hit["chunk_index"], None)
                for hit in hits[:top_k]
            ]
        results = []
        for hit in hits[:top_k]:
            merged, rng = _neighbor_window(conn, hit, context_window)
            results.append(_chunk_result(hit, merged, hit["chunk_index"], rng))
        return results


def search(
    query: str,
    query_embedding: list[float],
    top_k: int | None = None,
    folder: str | None = None,
    kind: str | None = None,
    context_window: int = 3,
) -> list[dict[str, Any]]:
    """Hybrid search over document_chunks (dense vector + lexical full-text,
    fused with RRF), then parent/neighbor expansion.

    Returns result dicts with content, metadata, file info, cosine ``similarity``
    (None for FTS-only hits), ``rrf_score``, and optional speaker attribution.
    Unchanged public behavior — backs the existing /search and /knowledge/search.
    """
    if top_k is None:
        top_k = config.default_top_k()
    cand = max(config.candidate_pool(), top_k)
    use_parent = _use_parent()
    # When collapsing children to parents, pull a deeper pool so the final list
    # still contains ~top_k distinct parents after de-duplication.
    limit = min(cand, top_k * 3) if use_parent else top_k
    hits = _fused_candidates(query, query_embedding, folder, kind, cand, limit, use_parent)
    return _expand_winners(hits, top_k, context_window, use_parent)


async def search_async(
    query: str,
    query_embedding: list[float],
    top_k: int | None = None,
    folder: str | None = None,
    kind: str | None = None,
    context_window: int = 3,
    rerank_enabled: bool | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search + cross-encoder rerank (async). Used by /ask.

    Pulls the full fused candidate pool, reranks it on the precise child text
    (best-effort: identity order on failure), then expands the winners to parents
    / neighbor windows. Sync DB work runs in a threadpool so the event loop is
    never blocked.
    """
    from fastapi.concurrency import run_in_threadpool

    from era_mcp import rerank as rerank_mod

    if top_k is None:
        top_k = config.default_top_k()
    cand = max(config.candidate_pool(), top_k)
    use_parent = _use_parent()
    # Pull the whole pool so the reranker scores everything before truncation.
    hits = await run_in_threadpool(
        _fused_candidates, query, query_embedding, folder, kind, cand, cand, use_parent
    )
    if not hits:
        return []
    if rerank_enabled is None:
        rerank_enabled = config.rerank_enabled()
    if rerank_enabled:
        hits = await rerank_mod.rerank(query, hits, top_k=len(hits))
    return await run_in_threadpool(
        _expand_winners, hits, top_k, context_window, use_parent,
        config.doc_first_enabled(),
    )


async def multi_search_async(
    queries: list[tuple[str, list[float]]],
    rerank_query: str,
    top_k: int | None = None,
    folder: str | None = None,
    kind: str | None = None,
    context_window: int = 3,
    rerank_enabled: bool | None = None,
) -> list[dict[str, Any]]:
    """Multi-query hybrid search + single rerank (async). Backs /ask.

    Each ``(query_text, query_embedding)`` pair contributes its own fused
    candidate pool; the pools are merged (deduped by chunk, keeping the best RRF
    score), reranked ONCE against ``rerank_query`` (the user's original
    question), then expanded to parents/neighbor windows. With a single pair this
    reduces to ``search_async``. Sub-queries that the rewriter already produces
    are thus actually used instead of discarded.
    """
    from fastapi.concurrency import run_in_threadpool

    from era_mcp import rerank as rerank_mod

    if not queries:
        return []
    if top_k is None:
        top_k = config.default_top_k()
    cand = max(config.candidate_pool(), top_k)
    use_parent = _use_parent()

    pools = await asyncio.gather(*[
        run_in_threadpool(
            _fused_candidates, q_text, q_emb, folder, kind, cand, cand, use_parent
        )
        for q_text, q_emb in queries
    ])

    # Merge pools, deduped by chunk identity, keeping the best RRF score seen.
    merged: dict[tuple[Any, Any], dict[str, Any]] = {}
    for pool in pools:
        for hit in pool:
            key = (hit["file_id"], hit["chunk_index"])
            prev = merged.get(key)
            if prev is None or hit["rrf_score"] > prev["rrf_score"]:
                merged[key] = hit
    hits = sorted(merged.values(), key=lambda h: h["rrf_score"], reverse=True)
    if not hits:
        return []

    if rerank_enabled is None:
        rerank_enabled = config.rerank_enabled()
    if rerank_enabled:
        hits = await rerank_mod.rerank(rerank_query, hits, top_k=len(hits))
    return await run_in_threadpool(
        _expand_winners, hits, top_k, context_window, use_parent,
        config.doc_first_enabled(),
    )


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
    if "rerank_score" in hit:
        result["rerank_score"] = hit["rerank_score"]
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


def _assemble_document_first(
    hits: list[dict[str, Any]],
    top_k: int,
    context_window: int,
    use_parent: bool,
    conn: Any,
) -> list[dict[str, Any]]:
    """Group reranked passages by document and emit them document-by-document.

    Documents are ordered by their best passage (first appearance in the already
    reranked ``hits``). Within each document, matched passages are collapsed to
    parents (deduped) and returned in reading order. Bounded by
    ``DOC_FIRST_MAX_DOCS`` and ``DOC_FIRST_MAX_PARENTS_PER_DOC`` and the overall
    ``top_k`` so one big file can't dominate and the context stays sane for a
    ~9B model. Each result carries ``doc_rank`` (1-based) for grouped synthesis.
    """
    max_docs = config.doc_first_max_docs()
    max_per_doc = config.doc_first_max_parents_per_doc()

    # Group by file, preserving the reranked order of first appearance.
    doc_order: list[Any] = []
    by_doc: dict[Any, list[dict[str, Any]]] = {}
    for hit in hits:
        fid = hit["file_id"]
        if fid not in by_doc:
            by_doc[fid] = []
            doc_order.append(fid)
        by_doc[fid].append(hit)

    results: list[dict[str, Any]] = []
    doc_rank = 0
    for fid in doc_order:
        if doc_rank >= max_docs or len(results) >= top_k:
            break
        seen_parents: set[Any] = set()
        doc_results: list[tuple[int, dict[str, Any]]] = []
        for hit in by_doc[fid]:
            if len(doc_results) >= max_per_doc:
                break
            pid = hit.get("parent_chunk_id")
            if use_parent and pid is not None and hit.get("parent_content"):
                if pid in seen_parents:
                    continue
                seen_parents.add(pid)
                result = _chunk_result(hit, hit["parent_content"], hit["chunk_index"], None)
                result["parent_chunk_id"] = pid
            elif context_window > 0:
                merged, rng = _neighbor_window(conn, hit, context_window)
                result = _chunk_result(hit, merged, hit["chunk_index"], rng)
            else:
                result = _chunk_result(hit, hit["content"], hit["chunk_index"], None)
            doc_results.append((hit["chunk_index"] if hit["chunk_index"] is not None else 0, result))
        if not doc_results:
            continue
        doc_rank += 1
        doc_results.sort(key=lambda t: t[0])  # reading order within the document
        for _, result in doc_results:
            if len(results) >= top_k:
                break
            result["doc_rank"] = doc_rank
            results.append(result)
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


def entities_in_text(q: str, limit: int = 10) -> list[dict[str, Any]]:
    """Entities whose canonical name appears IN the given text.

    For natural-language questions, ``search_entities`` (which matches when the
    entity NAME contains the query) never fires. This reverse match — entity name
    contained in the question — is what powers /ask graph augmentation. The
    length guard avoids noise from very short names.
    """
    sql = text("""
        SELECT e.id, e.canonical_name, e.entity_type, e.aliases, e.metadata,
               COUNT(DISTINCT em.file_id) AS file_count
          FROM entities e
          LEFT JOIN entity_mentions em ON em.entity_id = e.id
         WHERE length(e.canonical_name) >= 3
           AND :q ILIKE '%' || e.canonical_name || '%'
         GROUP BY e.id, e.canonical_name, e.entity_type, e.aliases, e.metadata
         ORDER BY file_count DESC, length(e.canonical_name) DESC
         LIMIT :limit
    """)
    with _get_engine().connect() as conn:
        rows = conn.execute(sql, {"q": q, "limit": limit}).fetchall()
    return [dict(row._mapping) for row in rows]


def relationships_in_text(q: str, limit: int = 10) -> list[dict[str, Any]]:
    """Relationships whose source or target entity name appears IN the text.
    The NL-question counterpart of ``search_relationships``."""
    sql = text("""
        SELECT r.id,
               se.canonical_name AS source,
               se.entity_type AS source_type,
               r.relationship_type,
               te.canonical_name AS target,
               te.entity_type AS target_type,
               r.confidence
          FROM relationships r
          JOIN entities se ON se.id = r.source_entity_id
          JOIN entities te ON te.id = r.target_entity_id
         WHERE (length(se.canonical_name) >= 3 AND :q ILIKE '%' || se.canonical_name || '%')
            OR (length(te.canonical_name) >= 3 AND :q ILIKE '%' || te.canonical_name || '%')
         ORDER BY r.confidence DESC NULLS LAST
         LIMIT :limit
    """)
    with _get_engine().connect() as conn:
        rows = conn.execute(sql, {"q": q, "limit": limit}).fetchall()
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


def _fact_row(row: Any) -> dict[str, Any]:
    d = dict(row._mapping)
    if d.get("occurred_at") is not None:
        d["occurred_at"] = d["occurred_at"].isoformat()
    return d


_FACTS_PRESENT: bool | None = None


def _facts_table_present(conn: Any) -> bool:
    """Whether knowledge_facts exists (migration 0005). Cached; degrades to [] when
    absent so older deployments never error."""
    global _FACTS_PRESENT
    if _FACTS_PRESENT is None:
        _FACTS_PRESENT = conn.execute(
            text("SELECT to_regclass('public.knowledge_facts')")
        ).scalar() is not None
    return _FACTS_PRESENT


_FACT_SELECT = """
    SELECT kf.id, kf.kind, kf.statement, kf.attributes, kf.occurred_at,
           kf.source_quote, kf.confidence,
           subj.canonical_name AS subject,
           obj.canonical_name  AS object,
           proj.canonical_name AS project,
           fr.file_name, fr.folder
      FROM knowledge_facts kf
      LEFT JOIN entities subj ON subj.id = kf.subject_entity_id
      LEFT JOIN entities obj  ON obj.id  = kf.object_entity_id
      LEFT JOIN entities proj ON proj.id = kf.project_entity_id
      JOIN file_registry fr ON fr.id = kf.file_id
"""


def search_facts(query: str, kind: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Search structured facts (decision/commitment/event) by statement/quote text
    and optional kind. Returns [] when knowledge_facts is absent."""
    with _get_engine().connect() as conn:
        if not _facts_table_present(conn):
            return []
        conds = ["(kf.statement ILIKE :like OR kf.source_quote ILIKE :like)"]
        params: dict[str, Any] = {"like": f"%{query}%", "limit": limit}
        if kind:
            conds.append("kf.kind = :kind")
            params["kind"] = kind
        sql = text(f"{_FACT_SELECT} WHERE {' AND '.join(conds)} "
                   "ORDER BY kf.confidence DESC NULLS LAST, kf.id DESC LIMIT :limit")
        rows = conn.execute(sql, params).fetchall()
    return [_fact_row(r) for r in rows]


def facts_in_text(q: str, limit: int = 10) -> list[dict[str, Any]]:
    """Facts whose project/subject/object entity name appears IN the text — the
    natural-language counterpart used by /ask graph augmentation."""
    with _get_engine().connect() as conn:
        if not _facts_table_present(conn):
            return []
        sql = text(f"""{_FACT_SELECT}
             WHERE (proj.canonical_name IS NOT NULL AND length(proj.canonical_name) >= 3
                    AND :q ILIKE '%' || proj.canonical_name || '%')
                OR (subj.canonical_name IS NOT NULL AND length(subj.canonical_name) >= 3
                    AND :q ILIKE '%' || subj.canonical_name || '%')
                OR (obj.canonical_name IS NOT NULL AND length(obj.canonical_name) >= 3
                    AND :q ILIKE '%' || obj.canonical_name || '%')
             ORDER BY kf.confidence DESC NULLS LAST, kf.id DESC
             LIMIT :limit""")
        rows = conn.execute(sql, {"q": q, "limit": limit}).fetchall()
    return [_fact_row(r) for r in rows]


def facts_for_entity(entity_id: int, limit: int = 25) -> list[dict[str, Any]]:
    """All facts where the entity is the subject, object, or project."""
    with _get_engine().connect() as conn:
        if not _facts_table_present(conn):
            return []
        sql = text(f"""{_FACT_SELECT}
             WHERE kf.subject_entity_id = :eid
                OR kf.object_entity_id = :eid
                OR kf.project_entity_id = :eid
             ORDER BY kf.confidence DESC NULLS LAST, kf.id DESC
             LIMIT :limit""")
        rows = conn.execute(sql, {"eid": entity_id, "limit": limit}).fetchall()
    return [_fact_row(r) for r in rows]


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


def graph_only(query: str, top_k: int | None = None) -> dict[str, Any]:
    """Graph channels (entities, relationships, communities) without re-running
    chunk retrieval. Each degrades to [] if its table is absent. Used by /ask to
    augment already-reranked chunks with connect-the-dots context."""
    if top_k is None:
        top_k = config.default_top_k()
    return {
        "entities": _safe(lambda: entities_in_text(query, limit=top_k), []),
        "relationships": _safe(lambda: relationships_in_text(query, limit=top_k), []),
        "communities": _safe(lambda: search_communities(query, limit=top_k), []),
        "facts": _safe(lambda: facts_in_text(query, limit=top_k), []),
    }


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
    # Reverse-contains match so entities/relationships surface for natural-
    # language questions, not only when the query equals an entity name.
    entities = _safe(lambda: entities_in_text(query, limit=top_k), [])
    relationships = _safe(lambda: relationships_in_text(query, limit=top_k), [])
    communities = _safe(lambda: search_communities(query, limit=top_k), [])
    facts = _safe(lambda: facts_in_text(query, limit=top_k), [])
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
                "facts",
                "summaries",
            ],
        },
        "document_summaries": summaries,
        "entities": entities,
        "relationships": relationships,
        "communities": communities,
        "facts": facts,
        "supporting_chunks": chunks,
        "provenance": {
            "folder": folder,
            "top_k": top_k,
        },
    }
