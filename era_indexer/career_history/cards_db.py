"""SQL for Document Intelligence Cards (document_cards / document_relations)."""
from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import text

from career_history.db import conn
from career_history.intel_db import _rows, table_exists


def card_inputs(file_id: int) -> dict[str, Any] | None:
    """Everything a card is assembled from, in one round trip."""
    with conn() as c:
        file_row = c.execute(text("""
            SELECT fr.id AS file_id, fr.file_name, fr.folder, fr.file_type, fr.file_hash, fr.file_path,
                   fr.last_modified_at, d.title
              FROM file_registry fr
              LEFT JOIN documents d ON d.file_id = fr.id
             WHERE fr.id = :f AND fr.deleted_at IS NULL
        """), {"f": file_id}).fetchone()
        if file_row is None:
            return None
        facts = _rows(c.execute(text("""
            SELECT id, kind, statement, status, priority, occurred_at, attributes, confidence
              FROM knowledge_facts WHERE file_id = :f ORDER BY id
        """), {"f": file_id}))
        mentions = _rows(c.execute(text("""
            SELECT e.id, e.canonical_name AS name, e.entity_type AS type, COUNT(*) AS mention_count
              FROM entity_mentions em JOIN entities e ON e.id = em.entity_id
             WHERE em.file_id = :f
             GROUP BY e.id ORDER BY mention_count DESC, e.canonical_name
             LIMIT 60
        """), {"f": file_id}))
        projects = _rows(c.execute(text("""
            SELECT p.id, p.name, p.project_key FROM project_files pf JOIN projects p ON p.id = pf.project_id
             WHERE pf.file_id = :f
        """), {"f": file_id})) if table_exists("project_files") else []
        versions = _rows(c.execute(text("""
            SELECT v2.file_id, v2.version_label, v2.version_rank, v2.is_latest
              FROM document_versions v1 JOIN document_versions v2
                ON v2.scope_key = v1.scope_key AND v2.family_key = v1.family_key
             WHERE v1.file_id = :f AND v2.file_id <> :f
        """), {"f": file_id})) if table_exists("document_versions") else []
        existing = c.execute(text("SELECT llm_card, model FROM document_cards WHERE file_id = :f"),
                             {"f": file_id}).fetchone() if table_exists("document_cards") else None
    return {"file": dict(file_row._mapping), "facts": facts, "mentions": mentions, "projects": projects,
            "versions": versions,
            "existing_llm_card": (existing.llm_card if existing else None) or None,
            "existing_model": existing.model if existing else None}


def upsert_card(row: dict[str, Any], embedding: list[float] | None) -> None:
    js = {k: json.dumps(row.get(k) or ([] if k != "llm_card" else {}), default=str)
          for k in ("keywords", "topics", "entities", "projects", "people", "customers", "products", "technologies",
                    "dates", "decisions", "risks", "actions", "outcomes", "references", "related_file_ids", "llm_card")}
    with conn() as c:
        c.execute(text(f"""
            INSERT INTO document_cards
                (file_id, source_hash, intelligence_version, inputs_hash, title, doc_type, summary,
                 keywords, topics, entities, projects, people, customers, products, technologies,
                 dates, doc_date, decisions, risks, actions, outcomes, "references", related_file_ids,
                 card_text, embedding, model, llm_card, built_at)
            VALUES (:file_id, :source_hash, :intelligence_version, :inputs_hash, :title, :doc_type, :summary,
                    CAST(:keywords AS jsonb), CAST(:topics AS jsonb), CAST(:entities AS jsonb), CAST(:projects AS jsonb),
                    CAST(:people AS jsonb), CAST(:customers AS jsonb), CAST(:products AS jsonb), CAST(:technologies AS jsonb),
                    CAST(:dates AS jsonb), :doc_date, CAST(:decisions AS jsonb), CAST(:risks AS jsonb), CAST(:actions AS jsonb),
                    CAST(:outcomes AS jsonb), CAST(:references AS jsonb), CAST(:related_file_ids AS jsonb),
                    :card_text, {"CAST(:embedding AS vector)" if embedding is not None else "NULL"}, :model, CAST(:llm_card AS jsonb), NOW())
            ON CONFLICT (file_id) DO UPDATE SET
                source_hash = EXCLUDED.source_hash, intelligence_version = EXCLUDED.intelligence_version,
                inputs_hash = EXCLUDED.inputs_hash, title = EXCLUDED.title, doc_type = EXCLUDED.doc_type,
                summary = EXCLUDED.summary, keywords = EXCLUDED.keywords, topics = EXCLUDED.topics,
                entities = EXCLUDED.entities, projects = EXCLUDED.projects, people = EXCLUDED.people,
                customers = EXCLUDED.customers, products = EXCLUDED.products, technologies = EXCLUDED.technologies,
                dates = EXCLUDED.dates, doc_date = EXCLUDED.doc_date, decisions = EXCLUDED.decisions,
                risks = EXCLUDED.risks, actions = EXCLUDED.actions, outcomes = EXCLUDED.outcomes,
                "references" = EXCLUDED."references", related_file_ids = EXCLUDED.related_file_ids,
                card_text = EXCLUDED.card_text,
                embedding = COALESCE(EXCLUDED.embedding, document_cards.embedding),
                model = COALESCE(EXCLUDED.model, document_cards.model), llm_card = EXCLUDED.llm_card, built_at = NOW()
        """), {**{k: row.get(k) for k in ("file_id", "source_hash", "intelligence_version", "inputs_hash", "title",
                                           "doc_type", "summary", "doc_date", "card_text", "model")},
               **js, "embedding": _vec(embedding) if embedding is not None else None})


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def existing_card_text(file_id: int) -> str | None:
    with conn() as c:
        row = c.execute(text("SELECT card_text FROM document_cards WHERE file_id = :f"), {"f": file_id}).fetchone()
    return row[0] if row else None


def backfill_candidates(intelligence_version: str, folder: str | None = None, limit: int | None = None,
                        first_window_chars: int = 12000) -> list[dict[str, Any]]:
    """Files extracted (facts done) whose card is missing or at an older version;
    returns the first window of text for the card-only prompt."""
    params: dict[str, Any] = {"iv": intelligence_version, "chars": first_window_chars}
    where = ["des.status = 'done'", "des.intelligence_version IS DISTINCT FROM :iv", "fr.deleted_at IS NULL"]
    if folder:
        where.append("fr.folder = :folder"); params["folder"] = folder
    sql = f"""
        SELECT fr.id AS file_id, fr.file_name, fr.folder, fr.file_type,
               left(string_agg(dc.content, ' ' ORDER BY dc.chunk_index), :chars) AS content
          FROM document_extraction_state des
          JOIN file_registry fr ON fr.id = des.file_id
          JOIN document_chunks dc ON dc.file_id = fr.id
         WHERE {" AND ".join(where)}
         GROUP BY fr.id, fr.file_name, fr.folder, fr.file_type, fr.last_modified_at
         ORDER BY fr.last_modified_at DESC NULLS LAST
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn() as c:
        return _rows(c.execute(text(sql), params))


def stale_input_cards(limit: int | None = None) -> list[int]:
    """Cards whose deterministic inputs moved since they were built (new facts,
    file re-processed, entity merges): re-assembled without an LLM call."""
    sql = """
        SELECT dc.file_id FROM document_cards dc
          JOIN file_registry fr ON fr.id = dc.file_id
         WHERE fr.deleted_at IS NULL AND (
               fr.last_processed_at > dc.built_at
            OR EXISTS (SELECT 1 FROM knowledge_facts kf WHERE kf.file_id = dc.file_id AND kf.created_at > dc.built_at)
            OR EXISTS (SELECT 1 FROM entity_merges m WHERE m.merged_at > dc.built_at)
            OR EXISTS (SELECT 1 FROM document_versions dv WHERE dv.file_id = dc.file_id AND dv.updated_at > dc.built_at))
         ORDER BY fr.last_modified_at DESC NULLS LAST
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn() as c:
        return [r[0] for r in c.execute(text(sql)).fetchall()]


def mark_card_version(file_id: int, intelligence_version: str) -> None:
    with conn() as c:
        c.execute(text("""
            UPDATE document_extraction_state SET intelligence_version = :iv WHERE file_id = :f
        """), {"iv": intelligence_version, "f": file_id})
        c.execute(text("UPDATE file_registry SET intelligence_version = :iv WHERE id = :f"),
                  {"iv": intelligence_version, "f": file_id})


# --- relations -------------------------------------------------------------------

def card_neighbors(file_id: int, k: int = 5, min_cosine: float = 0.6) -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT b.file_id, 1 - (a.embedding <=> b.embedding) AS cosine
              FROM document_cards a, document_cards b
             WHERE a.file_id = :f AND b.file_id <> :f AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL
               AND (1 - (a.embedding <=> b.embedding)) >= :min
             ORDER BY a.embedding <=> b.embedding
             LIMIT :k
        """), {"f": file_id, "k": k, "min": min_cosine}))


def project_siblings(file_id: int, k: int = 5) -> list[dict[str, Any]]:
    """Files in the same project(s), ranked by shared entity mentions."""
    with conn() as c:
        return _rows(c.execute(text("""
            WITH mine AS (SELECT DISTINCT entity_id FROM entity_mentions WHERE file_id = :f),
                 proj AS (SELECT project_id FROM project_files WHERE file_id = :f)
            SELECT pf.file_id, COUNT(DISTINCT em.entity_id) AS shared
              FROM project_files pf
              JOIN proj ON proj.project_id = pf.project_id
              LEFT JOIN entity_mentions em ON em.file_id = pf.file_id AND em.entity_id IN (SELECT entity_id FROM mine)
             WHERE pf.file_id <> :f
             GROUP BY pf.file_id
             ORDER BY shared DESC, pf.file_id
             LIMIT :k
        """), {"f": file_id, "k": k}))


def replace_relations(file_id: int, rows: Iterable[dict[str, Any]]) -> None:
    with conn() as c:
        c.execute(text("DELETE FROM document_relations WHERE file_id = :f"), {"f": file_id})
        for r in rows:
            c.execute(text("""
                INSERT INTO document_relations (file_id, related_file_id, relation, score)
                VALUES (:f, :r, :rel, :s)
                ON CONFLICT (file_id, related_file_id, relation) DO UPDATE SET score = EXCLUDED.score, computed_at = NOW()
            """), {"f": file_id, "r": r["file_id"], "rel": r["relation"], "s": r.get("score")})
        c.execute(text("""
            UPDATE document_cards SET related_file_ids = CAST(:rel AS jsonb) WHERE file_id = :f
        """), {"f": file_id, "rel": json.dumps(list(rows)[:10], default=str)})


def card_count() -> dict[str, int]:
    if not table_exists("document_cards"):
        return {"cards": 0, "embedded": 0}
    with conn() as c:
        row = c.execute(text("""
            SELECT COUNT(*) AS cards, COUNT(embedding) AS embedded FROM document_cards
        """)).fetchone()
    return dict(row._mapping)


def get_card(file_id: int) -> dict[str, Any] | None:
    if not table_exists("document_cards"):
        return None
    with conn() as c:
        row = c.execute(text("SELECT * FROM document_cards WHERE file_id = :f"), {"f": file_id}).fetchone()
    return dict(row._mapping) if row else None


# --- project record inputs (project_state §13) ----------------------------------------

def project_cards(project_id: int, limit: int = 12) -> list[dict[str, Any]]:
    if not table_exists("document_cards"):
        return []
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT dc.file_id, fr.file_name, dc.title, dc.doc_type, dc.summary, dc.doc_date, dc.topics,
                   (SELECT COUNT(*) FROM knowledge_facts kf WHERE kf.file_id = dc.file_id) AS fact_count
              FROM document_cards dc
              JOIN project_files pf ON pf.file_id = dc.file_id
              JOIN file_registry fr ON fr.id = dc.file_id
             WHERE pf.project_id = :p
             ORDER BY fact_count DESC, dc.doc_date DESC NULLS LAST
             LIMIT :limit
        """), {"p": project_id, "limit": limit}))


def project_events(project_id: int, limit: int = 60) -> list[dict[str, Any]]:
    if not table_exists("vault_events"):
        return []
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT ve.kind, ve.detected_at, ve.file_id, fr.file_name
              FROM vault_events ve
              JOIN project_files pf ON pf.file_id = ve.file_id
              LEFT JOIN file_registry fr ON fr.id = ve.file_id
             WHERE pf.project_id = :p
             ORDER BY ve.detected_at DESC
             LIMIT :limit
        """), {"p": project_id, "limit": limit}))


def related_projects(project_id: int, limit: int = 5) -> list[dict[str, Any]]:
    if not table_exists("project_similarity"):
        return []
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT ps.other_project_id AS project_id, p.name, ps.score, ps.shared_entities
              FROM project_similarity ps JOIN projects p ON p.id = ps.other_project_id
             WHERE ps.project_id = :p
             ORDER BY ps.score DESC
             LIMIT :limit
        """), {"p": project_id, "limit": limit}))
