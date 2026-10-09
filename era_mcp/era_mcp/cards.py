"""Reads over the indexer's Document Intelligence Cards (document_cards,
document_relations) for the agent: card-first search, lookups by file / topic /
date range, section text. Every function returns [] / None when the tables are
not built yet, so the server is safe to deploy before migration 0017."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from era_mcp import config, projects, retrieval
from era_mcp.retrieval import _vec_literal, lexical_terms

_CARD_COLS = ("dc.file_id, fr.file_name, fr.file_path, fr.folder, dc.title, dc.doc_type, dc.summary, dc.keywords, "
              "dc.topics, dc.entities, dc.projects, dc.people, dc.customers, dc.products, dc.technologies, dc.dates, "
              "dc.doc_date, dc.decisions, dc.risks, dc.actions, dc.outcomes, dc.\"references\", dc.related_file_ids, "
              "dc.built_at")


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in result.fetchall()]


def present() -> bool:
    return projects._present("document_cards")


def search_cards(query: str, embedding: list[float] | None, top_k: int = 10, folder: str | None = None,
                 project_id: int | None = None) -> list[dict[str, Any]]:
    """Card-first retrieval: RRF over card embedding cosine, card full-text,
    and exact topic/keyword hits. Each row carries ``card_score`` (0-1 cosine
    when available) and ``card_rank``."""
    if not present():
        return []
    terms = lexical_terms(query)
    params: dict[str, Any] = {"k": top_k, "rrf_k": config.rrf_k(), "qtext": " | ".join(terms) or "x",
                              "topic_terms": [t for t in terms][:8]}
    where = ["fr.deleted_at IS NULL"]
    if folder:
        where.append("fr.folder = :folder"); params["folder"] = folder
    if project_id is not None:
        where.append("EXISTS (SELECT 1 FROM project_files pf WHERE pf.file_id = dc.file_id AND pf.project_id = :pid)")
        params["pid"] = project_id
    w = " AND ".join(where)
    vec_cte = "SELECT NULL::int AS file_id, NULL::int AS rank, NULL::float AS cosine WHERE FALSE"
    if embedding is not None:
        params["qvec"] = _vec_literal(embedding)
        vec_cte = f"""
            SELECT dc.file_id, ROW_NUMBER() OVER (ORDER BY dc.embedding <=> CAST(:qvec AS vector)) AS rank,
                   1 - (dc.embedding <=> CAST(:qvec AS vector)) AS cosine
              FROM document_cards dc JOIN file_registry fr ON fr.id = dc.file_id
             WHERE dc.embedding IS NOT NULL AND {w}
             ORDER BY dc.embedding <=> CAST(:qvec AS vector) LIMIT 40"""
    sql = text(f"""
        WITH vec AS ({vec_cte}),
        fts AS (
            SELECT dc.file_id, ROW_NUMBER() OVER (ORDER BY ts_rank(dc.search_vector, to_tsquery('simple', :qtext)) DESC) AS rank
              FROM document_cards dc JOIN file_registry fr ON fr.id = dc.file_id
             WHERE dc.search_vector @@ to_tsquery('simple', :qtext) AND {w}
             LIMIT 40),
        topic AS (
            SELECT dc.file_id, 1 AS rank
              FROM document_cards dc JOIN file_registry fr ON fr.id = dc.file_id
             WHERE {w} AND EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(dc.topics || dc.keywords) t(v)
                 WHERE lower(t.v) = ANY(CAST(:topic_terms AS text[])))
             LIMIT 40),
        fused AS (
            SELECT COALESCE(v.file_id, f.file_id, t.file_id) AS file_id,
                   COALESCE(1.0 / (:rrf_k + v.rank), 0) + COALESCE(0.7 / (:rrf_k + f.rank), 0)
                     + COALESCE(0.5 / (:rrf_k + t.rank), 0) AS score,
                   v.cosine
              FROM vec v FULL OUTER JOIN fts f ON f.file_id = v.file_id
                         FULL OUTER JOIN topic t ON t.file_id = COALESCE(v.file_id, f.file_id))
        SELECT {_CARD_COLS}, fused.score AS rrf, fused.cosine AS card_score
          FROM fused JOIN document_cards dc ON dc.file_id = fused.file_id
          JOIN file_registry fr ON fr.id = dc.file_id
         ORDER BY fused.score DESC, fused.cosine DESC NULLS LAST
         LIMIT :k
    """)
    with retrieval._get_engine().connect() as conn:
        rows = _rows(conn.execute(sql, params))
    for i, r in enumerate(rows, start=1):
        r["card_rank"] = i
        if r.get("card_score") is not None:
            r["card_score"] = round(float(r["card_score"]), 4)
    return rows


def get_card(file_id: int) -> dict[str, Any] | None:
    if not present():
        return None
    with retrieval._get_engine().connect() as conn:
        rows = _rows(conn.execute(text(f"""
            SELECT {_CARD_COLS} FROM document_cards dc JOIN file_registry fr ON fr.id = dc.file_id
             WHERE dc.file_id = :f"""), {"f": file_id}))
    return rows[0] if rows else None


def cards_for_files(file_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not present() or not file_ids:
        return {}
    with retrieval._get_engine().connect() as conn:
        rows = _rows(conn.execute(text(f"""
            SELECT {_CARD_COLS} FROM document_cards dc JOIN file_registry fr ON fr.id = dc.file_id
             WHERE dc.file_id = ANY(CAST(:ids AS int[]))"""), {"ids": list(file_ids)}))
    return {r["file_id"]: r for r in rows}


def card_by_name(name: str) -> dict[str, Any] | None:
    """Exact file name first, then the best ILIKE fragment (newest)."""
    if not present() or not name:
        return None
    with retrieval._get_engine().connect() as conn:
        rows = _rows(conn.execute(text(f"""
            SELECT {_CARD_COLS} FROM document_cards dc JOIN file_registry fr ON fr.id = dc.file_id
             WHERE fr.deleted_at IS NULL AND (fr.file_name = :n OR fr.file_name ILIKE :like)
             ORDER BY (fr.file_name = :n) DESC, fr.last_modified_at DESC LIMIT 1"""),
            {"n": name, "like": f"%{name}%"}))
    return rows[0] if rows else None


def cards_by_topic(topic: str, limit: int = 10) -> list[dict[str, Any]]:
    if not present() or not topic:
        return []
    with retrieval._get_engine().connect() as conn:
        return _rows(conn.execute(text(f"""
            SELECT {_CARD_COLS}, 1.0 AS card_score FROM document_cards dc JOIN file_registry fr ON fr.id = dc.file_id
             WHERE fr.deleted_at IS NULL AND (
                   EXISTS (SELECT 1 FROM jsonb_array_elements_text(dc.topics || dc.keywords) t(v) WHERE t.v ILIKE :like)
                OR EXISTS (SELECT 1 FROM jsonb_array_elements(dc.entities) e WHERE e->>'name' ILIKE :like))
             ORDER BY dc.doc_date DESC NULLS LAST LIMIT :k"""), {"like": f"%{topic}%", "k": limit}))


def cards_in_range(start: str | None, end: str | None, project_id: int | None = None,
                   limit: int = 20) -> list[dict[str, Any]]:
    if not present():
        return []
    params: dict[str, Any] = {"k": limit, "start": start or "1900-01-01", "end": end or "2999-12-31"}
    where = ["fr.deleted_at IS NULL", "COALESCE(dc.doc_date, CAST(fr.last_modified_at AS date)) BETWEEN CAST(:start AS date) AND CAST(:end AS date)"]
    if project_id is not None:
        where.append("EXISTS (SELECT 1 FROM project_files pf WHERE pf.file_id = dc.file_id AND pf.project_id = :pid)")
        params["pid"] = project_id
    with retrieval._get_engine().connect() as conn:
        return _rows(conn.execute(text(f"""
            SELECT {_CARD_COLS}, 0.8 AS card_score FROM document_cards dc JOIN file_registry fr ON fr.id = dc.file_id
             WHERE {" AND ".join(where)}
             ORDER BY COALESCE(dc.doc_date, CAST(fr.last_modified_at AS date)) DESC LIMIT :k"""), params))


def facts_in_range(start: str | None, end: str | None, project_id: int | None = None,
                   kinds: list[str] | None = None, limit: int = 30) -> list[dict[str, Any]]:
    if not projects._present("knowledge_facts"):
        return []
    params: dict[str, Any] = {"k": limit, "start": start or "1900-01-01", "end": end or "2999-12-31"}
    where = ["kf.occurred_at BETWEEN CAST(:start AS timestamp) AND CAST(:end AS timestamp) + INTERVAL '1 day'"]
    if project_id is not None:
        where.append("EXISTS (SELECT 1 FROM project_files pf WHERE pf.file_id = kf.file_id AND pf.project_id = :pid)")
        params["pid"] = project_id
    if kinds:
        where.append("kf.kind = ANY(CAST(:kinds AS text[]))"); params["kinds"] = kinds
    with retrieval._get_engine().connect() as conn:
        return _rows(conn.execute(text(f"""
            SELECT kf.id, kf.kind, kf.statement, kf.status, kf.occurred_at, kf.attributes, kf.source_quote, kf.confidence,
                   kf.file_id, fr.file_name, fr.file_path, fr.folder, o.canonical_name AS owner
              FROM knowledge_facts kf JOIN file_registry fr ON fr.id = kf.file_id
              LEFT JOIN entities o ON o.id = kf.owner_entity_id
             WHERE {" AND ".join(where)}
             ORDER BY kf.occurred_at LIMIT :k"""), params))


def section_text(file_id: int, section_id: int | None = None, heading: str | None = None,
                 max_chars: int = 6000) -> dict[str, Any] | None:
    """Chunks of one section (by id or heading fragment) in reading order, else
    the parent chunk by section."""
    params: dict[str, Any] = {"f": file_id}
    where = ["dc.file_id = :f"]
    if section_id is not None:
        where.append("dc.section_id = :sid"); params["sid"] = section_id
    elif heading:
        where.append("COALESCE(dc.heading_path, dc.metadata->>'section_path') ILIKE :h"); params["h"] = f"%{heading}%"
    with retrieval._get_engine().connect() as conn:
        rows = _rows(conn.execute(text(f"""
            SELECT dc.chunk_index, COALESCE(dc.content_raw, dc.content) AS content, dc.section_id, dc.page_number,
                   COALESCE(dc.heading_path, dc.metadata->>'section_path') AS heading_path, fr.file_name, fr.file_path,
                   fr.folder, fr.last_modified_at
              FROM document_chunks dc JOIN file_registry fr ON fr.id = dc.file_id
             WHERE {" AND ".join(where)}
             ORDER BY dc.chunk_index LIMIT 40"""), params))
    if not rows:
        return None
    body = ""
    for r in rows:
        if len(body) + len(r["content"] or "") > max_chars:
            break
        body += (r["content"] or "") + "\n"
    first = rows[0]
    return {"file_id": file_id, "file_name": first["file_name"], "file_path": first["file_path"],
            "folder": first["folder"], "section": first.get("heading_path"), "section_id": first.get("section_id"),
            "page": first.get("page_number"), "date": _iso(first.get("last_modified_at")), "text": body.strip(),
            "chunks": len(rows)}


def file_meta(file_id: int) -> dict[str, Any] | None:
    with retrieval._get_engine().connect() as conn:
        rows = _rows(conn.execute(text("""
            SELECT fr.id AS file_id, fr.file_name, fr.file_path, fr.folder, fr.file_type, fr.file_hash,
                   fr.last_modified_at, fr.deleted_at,
                   (SELECT COUNT(*) FROM document_chunks dc WHERE dc.file_id = fr.id) AS chunks,
                   (SELECT COUNT(*) FROM knowledge_facts kf WHERE kf.file_id = fr.id) AS facts
              FROM file_registry fr WHERE fr.id = :f"""), {"f": file_id}))
    return rows[0] if rows else None


def project_file_ids(project_id: int) -> list[int]:
    if not projects._present("project_files"):
        return []
    with retrieval._get_engine().connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT file_id FROM project_files WHERE project_id = :p"),
                                           {"p": project_id}).fetchall()]


def latest_weekly_digest() -> dict[str, Any] | None:
    if not projects._present("digests"):
        return None
    with retrieval._get_engine().connect() as conn:
        has_kind = conn.execute(text("""SELECT 1 FROM information_schema.columns
                                        WHERE table_name = 'digests' AND column_name = 'kind'""")).fetchone() is not None
        sql = ("SELECT id, markdown, stats, created_at, kind, run_id FROM digests WHERE kind = 'weekly' "
               "ORDER BY created_at DESC LIMIT 1") if has_kind else \
              "SELECT id, markdown, stats, created_at, 'attention' AS kind, NULL AS run_id FROM digests ORDER BY created_at DESC LIMIT 1"
        rows = _rows(conn.execute(text(sql)))
        if not rows and has_kind:
            rows = _rows(conn.execute(text("SELECT id, markdown, stats, created_at, kind, run_id FROM digests ORDER BY created_at DESC LIMIT 1")))
    return rows[0] if rows else None


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10] if value else None
