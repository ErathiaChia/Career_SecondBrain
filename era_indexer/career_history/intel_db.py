"""Data layer for project intelligence (projects, events, versions, entity
resolution, typed facts, state, changes, conflicts, similarity, digests).

Kept separate from ``db.py`` so the indexing pipeline's SQL stays readable; uses
the same connection helper. Assumes migrations 0006+ are applied
(``python -m career_history.cli migrate``).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import text

from career_history.db import conn


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in result.fetchall()]


def table_exists(name: str) -> bool:
    with conn() as c:
        return c.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{name}"}).scalar() is not None


# --- Projects -----------------------------------------------------------------

def manifest_projects() -> list[dict[str, Any]]:
    if not table_exists("vault_manifest"):
        return []
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT path, name, kind, parent, project_key, customer_code, customer_name,
                   status, lifecycle, initiative_type, year, tags, metadata, generated_at
              FROM vault_manifest
             WHERE kind = 'project'
        """)))


def live_files() -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT id AS file_id, file_path, file_name, file_type, folder, last_modified_at
              FROM file_registry
             WHERE deleted_at IS NULL
        """)))


def upsert_project(p: dict[str, Any]) -> int:
    with conn() as c:
        row = c.execute(text("""
            INSERT INTO projects
                (project_key, name, client, project_type, status, lifecycle, owner,
                 source_folder, entity_id, first_activity, last_activity, file_count,
                 confidence, field_sources, aliases, metadata, updated_at)
            VALUES
                (:project_key, :name, :client, :project_type, :status, :lifecycle, :owner,
                 :source_folder, :entity_id, :first_activity, :last_activity, :file_count,
                 :confidence, CAST(:field_sources AS jsonb), CAST(:aliases AS jsonb),
                 CAST(:metadata AS jsonb), NOW())
            ON CONFLICT (project_key) DO UPDATE SET
                name = EXCLUDED.name,
                -- LLM-enriched fields survive re-discovery unless a deterministic
                -- source now provides a value.
                client = COALESCE(EXCLUDED.client, projects.client),
                project_type = COALESCE(EXCLUDED.project_type, projects.project_type),
                status = EXCLUDED.status,
                lifecycle = EXCLUDED.lifecycle,
                owner = COALESCE(EXCLUDED.owner, projects.owner),
                source_folder = EXCLUDED.source_folder,
                entity_id = EXCLUDED.entity_id,
                first_activity = EXCLUDED.first_activity,
                last_activity = EXCLUDED.last_activity,
                file_count = EXCLUDED.file_count,
                confidence = EXCLUDED.confidence,
                field_sources = projects.field_sources || EXCLUDED.field_sources,
                aliases = EXCLUDED.aliases,
                metadata = projects.metadata || EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
        """), {
            **p,
            "field_sources": json.dumps(p.get("field_sources", {})),
            "aliases": json.dumps(p.get("aliases", [])),
            "metadata": json.dumps(p.get("metadata", {}), default=str),
        }).fetchone()
        return row[0]


def replace_project_files(project_id: int, file_ids: Iterable[int]) -> None:
    ids = sorted(set(file_ids))
    with conn() as c:
        c.execute(text("DELETE FROM project_files WHERE project_id = :p"), {"p": project_id})
        if ids:
            c.execute(text("""
                INSERT INTO project_files (project_id, file_id)
                SELECT :p, unnest(CAST(:ids AS integer[]))
                ON CONFLICT DO NOTHING
            """), {"p": project_id, "ids": ids})


def mark_missing_projects(active_keys: Iterable[str]) -> int:
    """Projects whose folder disappeared keep their history but lose their files."""
    keys = list(active_keys)
    with conn() as c:
        ids = [r[0] for r in c.execute(text("""
            SELECT id FROM projects
             WHERE NOT (project_key = ANY(CAST(:keys AS text[])))
               AND status IS DISTINCT FROM 'REMOVED'
        """), {"keys": keys}).fetchall()]
        if ids:
            c.execute(text("DELETE FROM project_files WHERE project_id = ANY(CAST(:ids AS integer[]))"), {"ids": ids})
            c.execute(text("""
                UPDATE projects SET status = 'REMOVED', file_count = 0, updated_at = NOW()
                 WHERE id = ANY(CAST(:ids AS integer[]))
            """), {"ids": ids})
        return len(ids)


def list_projects(include_removed: bool = False) -> list[dict[str, Any]]:
    where = "" if include_removed else "WHERE status IS DISTINCT FROM 'REMOVED'"
    with conn() as c:
        return _rows(c.execute(text(f"SELECT * FROM projects {where} ORDER BY name")))


def get_project(ref: str | int) -> dict[str, Any] | None:
    with conn() as c:
        if isinstance(ref, int) or str(ref).isdigit():
            row = c.execute(text("SELECT * FROM projects WHERE id = :id"), {"id": int(ref)}).fetchone()
        else:
            row = c.execute(text("""
                SELECT * FROM projects
                 WHERE project_key = :r OR name ILIKE :r OR aliases ? :r
                 ORDER BY file_count DESC LIMIT 1
            """), {"r": str(ref)}).fetchone()
        return dict(row._mapping) if row else None


def project_fact_samples(project_id: int, limit: int = 15) -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT kind, statement FROM project_facts
             WHERE project_id = :p
             ORDER BY confidence DESC NULLS LAST, id DESC LIMIT :limit
        """), {"p": project_id, "limit": limit}))


def project_file_names(project_id: int, limit: int = 40) -> list[str]:
    with conn() as c:
        return [r[0] for r in c.execute(text("""
            SELECT fr.file_name FROM project_files pf
              JOIN file_registry fr ON fr.id = pf.file_id
             WHERE pf.project_id = :p
             ORDER BY fr.last_modified_at DESC NULLS LAST LIMIT :limit
        """), {"p": project_id, "limit": limit}).fetchall()]


def update_project_fields(project_id: int, fields: dict[str, Any], sources: dict[str, str],
                          confidence: float | None) -> None:
    allowed = {"client", "project_type", "owner", "status"}
    sets = [f"{k} = :{k}" for k in fields if k in allowed]
    if not sets:
        return
    params = {k: v for k, v in fields.items() if k in allowed}
    params.update({"id": project_id, "sources": json.dumps(sources), "confidence": confidence})
    with conn() as c:
        c.execute(text(f"""
            UPDATE projects
               SET {", ".join(sets)},
                   field_sources = field_sources || CAST(:sources AS jsonb),
                   confidence = COALESCE(:confidence, confidence),
                   updated_at = NOW()
             WHERE id = :id
        """), params)


def project_ids_for_files(file_ids: Iterable[int]) -> dict[int, int]:
    ids = sorted(set(file_ids))
    if not ids:
        return {}
    with conn() as c:
        rows = c.execute(text("""
            SELECT file_id, project_id FROM project_files
             WHERE file_id = ANY(CAST(:ids AS integer[]))
        """), {"ids": ids}).fetchall()
    return {r[0]: r[1] for r in rows}


# --- Vault events -------------------------------------------------------------

def insert_event(c: Any, kind: str, file_path: str, file_id: int | None = None,
                 old_hash: str | None = None, new_hash: str | None = None,
                 payload: dict[str, Any] | None = None) -> None:
    """Append one vault event inside an existing transaction ``c``."""
    c.execute(text("""
        INSERT INTO vault_events (kind, file_id, file_path, old_hash, new_hash, payload)
        VALUES (:kind, :file_id, :file_path, :old_hash, :new_hash, CAST(:payload AS jsonb))
    """), {"kind": kind, "file_id": file_id, "file_path": file_path,
           "old_hash": old_hash, "new_hash": new_hash,
           "payload": json.dumps(payload or {}, default=str)})


def record_event(kind: str, file_path: str, file_id: int | None = None,
                 old_hash: str | None = None, new_hash: str | None = None,
                 payload: dict[str, Any] | None = None) -> None:
    with conn() as c:
        insert_event(c, kind, file_path, file_id, old_hash, new_hash, payload)


def unprocessed_events(limit: int = 5000) -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT ve.*, fr.file_name, pf.project_id AS current_project_id
              FROM vault_events ve
              LEFT JOIN file_registry fr ON fr.id = ve.file_id
              LEFT JOIN project_files pf ON pf.file_id = ve.file_id
             WHERE ve.processed_at IS NULL
             ORDER BY ve.detected_at, ve.id
             LIMIT :limit
        """), {"limit": limit}))


def mark_events_processed(event_ids: Iterable[int]) -> None:
    ids = sorted(set(event_ids))
    if not ids:
        return
    with conn() as c:
        c.execute(text("""
            UPDATE vault_events SET processed_at = NOW()
             WHERE id = ANY(CAST(:ids AS bigint[]))
        """), {"ids": ids})


# --- Document versions --------------------------------------------------------

def version_candidates() -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT fr.id AS file_id, fr.file_path, fr.file_name, fr.file_type,
                   fr.last_modified_at, pf.project_id, p.project_key
              FROM file_registry fr
              LEFT JOIN project_files pf ON pf.file_id = fr.id
              LEFT JOIN projects p ON p.id = pf.project_id
             WHERE fr.deleted_at IS NULL
        """)))


def existing_version_rows() -> dict[int, dict[str, Any]]:
    with conn() as c:
        rows = _rows(c.execute(text("SELECT * FROM document_versions")))
    return {r["file_id"]: r for r in rows}


def replace_document_versions(rows: list[dict[str, Any]]) -> None:
    with conn() as c:
        c.execute(text("DELETE FROM document_versions"))
        for r in rows:
            c.execute(text("""
                INSERT INTO document_versions
                    (file_id, family_key, scope_key, project_id, version_label,
                     version_rank, previous_file_id, is_latest, family_size, updated_at)
                VALUES (:file_id, :family_key, :scope_key, :project_id, :version_label,
                        :version_rank, :previous_file_id, :is_latest, :family_size, NOW())
            """), r)


# --- Entity resolution --------------------------------------------------------

def entities_for_resolution(entity_types: Iterable[str] | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where = ""
    if entity_types:
        where = "WHERE e.entity_type = ANY(CAST(:types AS text[]))"
        params["types"] = list(entity_types)
    with conn() as c:
        return _rows(c.execute(text(f"""
            SELECT e.id, e.canonical_name, e.entity_type, e.aliases, e.metadata,
                   COUNT(em.id) AS mention_count
              FROM entities e
              LEFT JOIN entity_mentions em ON em.entity_id = e.id
              {where}
             GROUP BY e.id
        """), params))


def merge_entity(source_id: int, target_id: int, method: str, score: float | None) -> None:
    """Fold entity ``source_id`` into ``target_id``: re-point mentions, facts and
    relationships, union aliases, log the merge, delete the source."""
    if source_id == target_id:
        return
    with conn() as c:
        src = c.execute(text("SELECT canonical_name, entity_type, aliases FROM entities WHERE id = :id"),
                        {"id": source_id}).fetchone()
        if src is None:
            return
        c.execute(text("UPDATE entity_mentions SET entity_id = :t WHERE entity_id = :s"),
                  {"s": source_id, "t": target_id})
        for col in ("subject_entity_id", "object_entity_id", "project_entity_id", "owner_entity_id"):
            c.execute(text(f"UPDATE knowledge_facts SET {col} = :t WHERE {col} = :s"),
                      {"s": source_id, "t": target_id})
        c.execute(text("UPDATE projects SET entity_id = :t WHERE entity_id = :s"),
                  {"s": source_id, "t": target_id})
        rels = c.execute(text("""
            SELECT id, source_entity_id, relationship_type, target_entity_id, confidence
              FROM relationships
             WHERE source_entity_id = :s OR target_entity_id = :s
        """), {"s": source_id}).fetchall()
        for rel in rels:
            new_src = target_id if rel.source_entity_id == source_id else rel.source_entity_id
            new_tgt = target_id if rel.target_entity_id == source_id else rel.target_entity_id
            if new_src == new_tgt:
                c.execute(text("DELETE FROM relationships WHERE id = :id"), {"id": rel.id})
                continue
            keeper = c.execute(text("""
                SELECT id FROM relationships
                 WHERE source_entity_id = :a AND relationship_type = :t AND target_entity_id = :b
                   AND id <> :id
            """), {"a": new_src, "t": rel.relationship_type, "b": new_tgt, "id": rel.id}).fetchone()
            if keeper:
                c.execute(text("UPDATE relationship_evidence SET relationship_id = :k WHERE relationship_id = :id"),
                          {"k": keeper[0], "id": rel.id})
                c.execute(text("DELETE FROM relationships WHERE id = :id"), {"id": rel.id})
            else:
                c.execute(text("""
                    UPDATE relationships SET source_entity_id = :a, target_entity_id = :b, updated_at = NOW()
                     WHERE id = :id
                """), {"a": new_src, "b": new_tgt, "id": rel.id})
        aliases = list(src.aliases or []) + [src.canonical_name]
        c.execute(text("""
            UPDATE entities
               SET aliases = COALESCE((
                       SELECT jsonb_agg(DISTINCT v)
                         FROM jsonb_array_elements_text(aliases || CAST(:aliases AS jsonb)) AS a(v)
                   ), '[]'::jsonb),
                   updated_at = NOW()
             WHERE id = :t
        """), {"t": target_id, "aliases": json.dumps(aliases)})
        c.execute(text("""
            INSERT INTO entity_merges (merged_name, merged_type, into_entity_id, method, score)
            VALUES (:n, :ty, :t, :m, :sc)
        """), {"n": src.canonical_name, "ty": src.entity_type, "t": target_id, "m": method, "sc": score})
        c.execute(text("DELETE FROM entities WHERE id = :s"), {"s": source_id})


# --- Typed facts --------------------------------------------------------------

def facts_for_file(file_id: int) -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT id, kind, statement, topic, status, priority, occurred_at,
                   attributes ->> 'due_at' AS due_at, extractor_version
              FROM knowledge_facts WHERE file_id = :f
        """), {"f": file_id}))


def project_facts(project_id: int, kinds: Iterable[str] | None = None,
                  limit: int = 400) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"p": project_id, "limit": limit}
    where = ["pf.project_id = :p"]
    if kinds:
        where.append("pf.kind = ANY(CAST(:kinds AS text[]))")
        params["kinds"] = list(kinds)
    with conn() as c:
        return _rows(c.execute(text(f"""
            SELECT pf.id, pf.kind, pf.statement, pf.topic, pf.status, pf.priority,
                   pf.attributes, pf.occurred_at, pf.last_verified_at, pf.confidence,
                   pf.source_quote, pf.supersedes_fact_id, pf.file_id,
                   fr.file_name, fr.last_modified_at,
                   owner.canonical_name AS owner,
                   COALESCE(dv.is_latest, TRUE) AS from_latest_version
              FROM project_facts pf
              JOIN file_registry fr ON fr.id = pf.file_id
              LEFT JOIN entities owner ON owner.id = pf.owner_entity_id
              LEFT JOIN document_versions dv ON dv.file_id = pf.file_id
             WHERE {" AND ".join(where)}
             ORDER BY COALESCE(pf.last_verified_at, pf.occurred_at, fr.last_modified_at) DESC NULLS LAST,
                      pf.id DESC
             LIMIT :limit
        """), params))


# --- Project state ------------------------------------------------------------

def save_project_state(project_id: int, state: dict[str, Any], health: dict[str, Any],
                       model: str | None, source_hash: str) -> int | None:
    """Store a new current state unless the inputs are unchanged."""
    with conn() as c:
        current = c.execute(text("""
            SELECT id, source_hash FROM project_state
             WHERE project_id = :p AND is_current = TRUE
        """), {"p": project_id}).fetchone()
        if current and current.source_hash == source_hash:
            return None
        c.execute(text("UPDATE project_state SET is_current = FALSE WHERE project_id = :p AND is_current = TRUE"),
                  {"p": project_id})
        row = c.execute(text("""
            INSERT INTO project_state (project_id, state, health, model, source_hash, is_current)
            VALUES (:p, CAST(:state AS jsonb), CAST(:health AS jsonb), :model, :hash, TRUE)
            RETURNING id
        """), {"p": project_id, "state": json.dumps(state, default=str),
               "health": json.dumps(health, default=str), "model": model,
               "hash": source_hash}).fetchone()
        return row[0]


def current_project_state(project_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute(text("""
            SELECT * FROM project_state WHERE project_id = :p AND is_current = TRUE
        """), {"p": project_id}).fetchone()
    return dict(row._mapping) if row else None


def project_counts(project_id: int) -> dict[str, Any]:
    with conn() as c:
        row = c.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM project_files WHERE project_id = :p) AS files,
              (SELECT COUNT(*) FROM document_versions WHERE project_id = :p AND family_size > 1
                  AND is_latest) AS versioned_families,
              (SELECT COUNT(*) FROM document_versions WHERE project_id = :p AND NOT is_latest) AS older_versions,
              (SELECT COUNT(*) FROM fact_conflicts WHERE project_id = :p
                  AND status = 'needs_confirmation') AS open_conflicts,
              (SELECT COUNT(*) FROM stale_flags sf JOIN project_facts f ON f.id = sf.object_id
                  WHERE sf.object_type = 'fact' AND f.project_id = :p) AS stale_facts,
              (SELECT COUNT(*) FROM project_changes WHERE project_id = :p
                  AND detected_at > NOW() - INTERVAL '14 days') AS recent_changes
        """), {"p": project_id}).fetchone()
    return dict(row._mapping)


def project_flags(project_id: int) -> dict[str, Any]:
    """Stale reasons per fact and open conflicts for one project."""
    with conn() as c:
        stale = c.execute(text("""
            SELECT sf.object_id, sf.reason FROM stale_flags sf
              JOIN project_facts f ON f.id = sf.object_id
             WHERE sf.object_type = 'fact' AND f.project_id = :p
        """), {"p": project_id}).fetchall()
        conflicts = _rows(c.execute(text("""
            SELECT id, fact_a_id, fact_b_id, conflict_type, explanation,
                   likely_latest_fact_id, confidence, status
              FROM fact_conflicts
             WHERE project_id = :p AND status IN ('needs_confirmation', 'confirmed')
        """), {"p": project_id}))
    by_fact: dict[int, list[str]] = {}
    for fid, reason in stale:
        by_fact.setdefault(fid, []).append(reason)
    return {"stale": by_fact, "conflicts": conflicts}


# --- Changes ------------------------------------------------------------------

def insert_change(project_id: int | None, file_id: int | None, change_type: str, summary: str,
                  payload: dict[str, Any] | None = None, severity: str = "info") -> int:
    with conn() as c:
        row = c.execute(text("""
            INSERT INTO project_changes (project_id, file_id, change_type, summary, payload, severity)
            VALUES (:p, :f, :t, :s, CAST(:payload AS jsonb), :sev)
            RETURNING id
        """), {"p": project_id, "f": file_id, "t": change_type, "s": summary,
               "payload": json.dumps(payload or {}, default=str), "sev": severity}).fetchone()
        return row[0]


def changes_without_impact(limit: int = 2000) -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT pc.*, fr.file_name FROM project_changes pc
              LEFT JOIN file_registry fr ON fr.id = pc.file_id
             WHERE pc.impact IS NULL AND pc.project_id IS NOT NULL
             ORDER BY pc.project_id, pc.detected_at
             LIMIT :limit
        """), {"limit": limit}))


def set_change_impact(change_ids: Iterable[int], batch_id: str, impact: dict[str, Any],
                      severity: str | None = None) -> None:
    ids = sorted(set(change_ids))
    if not ids:
        return
    with conn() as c:
        c.execute(text("""
            UPDATE project_changes
               SET impact = CAST(:impact AS jsonb), batch_id = :b,
                   severity = COALESCE(:sev, severity)
             WHERE id = ANY(CAST(:ids AS integer[]))
        """), {"impact": json.dumps(impact, default=str), "b": batch_id, "sev": severity, "ids": ids})


# --- Conflicts and staleness --------------------------------------------------

def checked_fact_pairs(project_id: int) -> set[tuple[int, int]]:
    with conn() as c:
        rows = c.execute(text("""
            SELECT fact_a_id, fact_b_id FROM fact_conflicts WHERE project_id = :p
        """), {"p": project_id}).fetchall()
    return {(r[0], r[1]) for r in rows}


def upsert_conflict(row: dict[str, Any]) -> None:
    with conn() as c:
        c.execute(text("""
            INSERT INTO fact_conflicts
                (project_id, fact_a_id, fact_b_id, conflict_type, explanation,
                 likely_latest_fact_id, confidence, status, method)
            VALUES (:project_id, :fact_a_id, :fact_b_id, :conflict_type, :explanation,
                    :likely_latest_fact_id, :confidence, :status, :method)
            ON CONFLICT (fact_a_id, fact_b_id) DO UPDATE SET
                conflict_type = EXCLUDED.conflict_type,
                explanation = EXCLUDED.explanation,
                likely_latest_fact_id = EXCLUDED.likely_latest_fact_id,
                confidence = EXCLUDED.confidence,
                status = CASE WHEN fact_conflicts.status IN ('confirmed', 'dismissed')
                              THEN fact_conflicts.status ELSE EXCLUDED.status END,
                method = EXCLUDED.method,
                detected_at = NOW()
        """), row)


def clear_open_deterministic_conflicts(project_id: int) -> int:
    """Drop unreviewed rule-based conflicts so re-detection can rebuild them;
    confirmed/dismissed rows (human decisions) are kept."""
    with conn() as c:
        result = c.execute(text("""
            DELETE FROM fact_conflicts
             WHERE project_id = :p AND method = 'deterministic' AND status = 'needs_confirmation'
        """), {"p": project_id})
        return result.rowcount


def replace_stale_flags(flags: list[dict[str, Any]], run_id: str | None = None) -> None:
    """Refresh the stale set while PRESERVING flagged_at for flags that already
    existed (so "stale since last week" is real). Before migration 0019 this
    falls back to the old wipe-and-reinsert."""
    run_id = run_id or os.environ.get("ERA_RUN_ID") or f"stale-{uuid.uuid4().hex[:8]}"
    with conn() as c:
        from career_history.db import _column_exists
        if not _column_exists(c, "stale_flags", "last_seen_run"):
            c.execute(text("DELETE FROM stale_flags"))
            for f in flags:
                c.execute(text("""
                    INSERT INTO stale_flags (object_type, object_id, reason, detail, newer_evidence_id)
                    VALUES (:object_type, :object_id, :reason, :detail, :newer_evidence_id)
                    ON CONFLICT (object_type, object_id, reason) DO NOTHING
                """), f)
            return
        for f in flags:
            c.execute(text("""
                INSERT INTO stale_flags (object_type, object_id, reason, detail, newer_evidence_id,
                                         run_id, last_seen_run)
                VALUES (:object_type, :object_id, :reason, :detail, :newer_evidence_id, :run, :run)
                ON CONFLICT (object_type, object_id, reason) DO UPDATE SET
                    detail = EXCLUDED.detail,
                    newer_evidence_id = EXCLUDED.newer_evidence_id,
                    last_seen_run = EXCLUDED.last_seen_run
            """), {**f, "run": run_id})
        c.execute(text("DELETE FROM stale_flags WHERE last_seen_run IS DISTINCT FROM :run"), {"run": run_id})


def set_conflict_status(conflict_id: int, status: str, latest_fact_id: int | None = None) -> bool:
    with conn() as c:
        result = c.execute(text("""
            UPDATE fact_conflicts
               SET status = :s, likely_latest_fact_id = COALESCE(:latest, likely_latest_fact_id)
             WHERE id = :id
        """), {"s": status, "latest": latest_fact_id, "id": conflict_id})
        return result.rowcount > 0


def all_open_conflicts() -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT fact_a_id, fact_b_id, likely_latest_fact_id
              FROM fact_conflicts WHERE status IN ('needs_confirmation', 'confirmed')
        """)))


def all_facts_for_staleness() -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT kf.id, kf.kind, kf.status, kf.file_id, kf.supersedes_fact_id,
                   COALESCE(kf.last_verified_at, kf.occurred_at, fr.last_modified_at) AS evidence_at,
                   dv.is_latest, dv.family_key, dv.scope_key,
                   proj.last_activity AS project_last_activity
              FROM knowledge_facts kf
              JOIN file_registry fr ON fr.id = kf.file_id
              LEFT JOIN document_versions dv ON dv.file_id = kf.file_id
              LEFT JOIN LATERAL (
                  SELECT MAX(p.last_activity) AS last_activity
                    FROM project_files pf JOIN projects p ON p.id = pf.project_id
                   WHERE pf.file_id = kf.file_id
              ) proj ON TRUE
        """)))


def latest_versions_by_family() -> dict[tuple[str, str], int]:
    with conn() as c:
        rows = c.execute(text("""
            SELECT scope_key, family_key, file_id FROM document_versions WHERE is_latest
        """)).fetchall()
    return {(r[0], r[1]): r[2] for r in rows}


# --- Similarity ---------------------------------------------------------------

def refresh_project_embeddings() -> int:
    with conn() as c:
        c.execute(text("DELETE FROM project_embeddings"))
        result = c.execute(text("""
            INSERT INTO project_embeddings (project_id, embedding, chunk_count, updated_at)
            SELECT pf.project_id, AVG(dc.embedding), COUNT(*), NOW()
              FROM project_files pf
              JOIN document_chunks dc ON dc.file_id = pf.file_id
             WHERE dc.embedding IS NOT NULL
             GROUP BY pf.project_id
        """))
        return result.rowcount


def project_vector_neighbors(top_k: int) -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT a.project_id, nb.project_id AS other_project_id, nb.cosine
              FROM project_embeddings a
              CROSS JOIN LATERAL (
                  SELECT b.project_id, 1 - (a.embedding <=> b.embedding) AS cosine
                    FROM project_embeddings b
                   WHERE b.project_id <> a.project_id
                   ORDER BY a.embedding <=> b.embedding
                   LIMIT :k
              ) nb
        """), {"k": top_k}))


def project_entity_sets(entity_types: Iterable[str]) -> dict[int, set[int]]:
    with conn() as c:
        rows = c.execute(text("""
            SELECT pe.project_id, pe.entity_id
              FROM project_entities pe
              JOIN entities e ON e.id = pe.entity_id
             WHERE e.entity_type = ANY(CAST(:types AS text[]))
        """), {"types": list(entity_types)}).fetchall()
    out: dict[int, set[int]] = {}
    for pid, eid in rows:
        out.setdefault(pid, set()).add(eid)
    return out


def entity_names(entity_ids: Iterable[int]) -> dict[int, str]:
    ids = sorted(set(entity_ids))
    if not ids:
        return {}
    with conn() as c:
        rows = c.execute(text("SELECT id, canonical_name FROM entities WHERE id = ANY(CAST(:ids AS integer[]))"),
                         {"ids": ids}).fetchall()
    return {r[0]: r[1] for r in rows}


def replace_project_similarity(rows: list[dict[str, Any]]) -> None:
    with conn() as c:
        c.execute(text("DELETE FROM project_similarity"))
        for r in rows:
            c.execute(text("""
                INSERT INTO project_similarity
                    (project_id, other_project_id, score, cosine, entity_overlap, shared_entities)
                VALUES (:project_id, :other_project_id, :score, :cosine, :entity_overlap,
                        CAST(:shared_entities AS jsonb))
            """), {**r, "shared_entities": json.dumps(r.get("shared_entities", []))})


# --- Proposed actions ---------------------------------------------------------

def list_proposed_actions(status: str = "pending") -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT a.id, a.action_type, a.title, a.detail, a.status, a.created_at, p.name AS project
              FROM proposed_actions a LEFT JOIN projects p ON p.id = a.project_id
             WHERE a.status = :s ORDER BY a.created_at
        """), {"s": status}))


def decide_proposed_action(action_id: int, status: str) -> bool:
    with conn() as c:
        result = c.execute(text("""
            UPDATE proposed_actions SET status = :s, decided_at = NOW() WHERE id = :id
        """), {"s": status, "id": action_id})
        return result.rowcount > 0


# --- Digest -------------------------------------------------------------------

def digest_inputs(since_days: int) -> dict[str, Any]:
    with conn() as c:
        changes = _rows(c.execute(text("""
            SELECT pc.project_id, p.name AS project, pc.batch_id, pc.severity, pc.summary, pc.impact
              FROM project_changes pc JOIN projects p ON p.id = pc.project_id
             WHERE pc.detected_at > NOW() - make_interval(days => :d) AND pc.impact IS NOT NULL
             ORDER BY pc.detected_at DESC
        """), {"d": since_days}))
        states = _rows(c.execute(text("""
            SELECT p.id AS project_id, p.name AS project, ps.health,
                   ps.state -> 'overdue' -> 'value' AS overdue,
                   ps.state -> 'upcoming_milestones' -> 'value' AS upcoming
              FROM project_state ps JOIN projects p ON p.id = ps.project_id
             WHERE ps.is_current AND p.status IS DISTINCT FROM 'REMOVED'
        """)))
        conflicts = _rows(c.execute(text("""
            SELECT c.id, c.project_id, p.name AS project, c.conflict_type, c.explanation
              FROM fact_conflicts c JOIN projects p ON p.id = c.project_id
             WHERE c.status = 'needs_confirmation'
        """)))
        proposed = _rows(c.execute(text("""
            SELECT a.id, a.title, p.name AS project FROM proposed_actions a
              LEFT JOIN projects p ON p.id = a.project_id
             WHERE a.status = 'pending'
        """)))
        last = c.execute(text("SELECT items FROM digests ORDER BY created_at DESC LIMIT 1")).fetchone()
    previous = {i.get("key") for i in (last[0] if last else []) if isinstance(i, dict)}
    return {"changes": changes, "states": states, "conflicts": conflicts,
            "proposed": proposed, "previous_keys": previous}


def save_digest(items: list[dict[str, Any]], markdown: str, stats: dict[str, Any],
                kind: str = "attention", run_id: str | None = None) -> int:
    run_id = run_id or os.environ.get("ERA_RUN_ID") or None
    with conn() as c:
        from career_history.db import _column_exists
        if _column_exists(c, "digests", "kind"):
            row = c.execute(text("""
                INSERT INTO digests (items, markdown, stats, kind, run_id)
                VALUES (CAST(:items AS jsonb), :md, CAST(:stats AS jsonb), :kind, :run_id)
                RETURNING id
            """), {"items": json.dumps(items, default=str), "md": markdown,
                   "stats": json.dumps(stats, default=str), "kind": kind, "run_id": run_id}).fetchone()
        else:
            row = c.execute(text("""
                INSERT INTO digests (items, markdown, stats)
                VALUES (CAST(:items AS jsonb), :md, CAST(:stats AS jsonb))
                RETURNING id
            """), {"items": json.dumps(items, default=str), "md": markdown,
                   "stats": json.dumps(stats, default=str)}).fetchone()
        return row[0]


# --- Pipeline runs (weekly / manual / catch-up) ---------------------------------

def start_pipeline_run(run_id: str, kind: str, host: str | None, git_sha: str | None,
                       deadline: datetime | None, model_config: dict[str, Any] | None = None) -> None:
    with conn() as c:
        c.execute(text("""
            INSERT INTO pipeline_runs (run_id, kind, host, git_sha, deadline_at, model_config, stage)
            VALUES (:run_id, :kind, :host, :git_sha, :deadline, CAST(:mc AS jsonb), 'preflight')
        """), {"run_id": run_id, "kind": kind, "host": host, "git_sha": git_sha,
               "deadline": deadline, "mc": json.dumps(model_config or {}, default=str)})


def heartbeat_pipeline_run(run_id: str, stage: str | None = None, stages: dict[str, Any] | None = None,
                           counts: dict[str, Any] | None = None) -> None:
    with conn() as c:
        c.execute(text("""
            UPDATE pipeline_runs
               SET heartbeat_at = NOW(),
                   stage = COALESCE(:stage, stage),
                   stages = COALESCE(CAST(:stages AS jsonb), stages),
                   counts = COALESCE(CAST(:counts AS jsonb), counts)
             WHERE run_id = :run_id
        """), {"run_id": run_id, "stage": stage,
               "stages": json.dumps(stages, default=str) if stages is not None else None,
               "counts": json.dumps(counts, default=str) if counts is not None else None})


def finish_pipeline_run(run_id: str, status: str, stages: dict[str, Any], counts: dict[str, Any],
                        errors: list[str], digest_id: int | None = None, notes: str | None = None) -> None:
    with conn() as c:
        c.execute(text("""
            UPDATE pipeline_runs
               SET status = :status, finished_at = NOW(), heartbeat_at = NOW(), stage = 'finalize',
                   stages = CAST(:stages AS jsonb), counts = CAST(:counts AS jsonb),
                   errors = CAST(:errors AS jsonb), digest_id = :digest_id, notes = :notes
             WHERE run_id = :run_id
        """), {"run_id": run_id, "status": status, "stages": json.dumps(stages, default=str),
               "counts": json.dumps(counts, default=str), "errors": json.dumps(errors, default=str),
               "digest_id": digest_id, "notes": notes})


def latest_pipeline_run(kinds: Iterable[str] | None = None) -> dict[str, Any] | None:
    if not table_exists("pipeline_runs"):
        return None
    with conn() as c:
        if kinds:
            rows = _rows(c.execute(text("""
                SELECT * FROM pipeline_runs WHERE kind = ANY(CAST(:kinds AS text[]))
                 ORDER BY started_at DESC LIMIT 1"""), {"kinds": list(kinds)}))
        else:
            rows = _rows(c.execute(text("SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1")))
    return rows[0] if rows else None


def previous_finished_run(before_run_id: str | None = None) -> dict[str, Any] | None:
    """The last run that completed (finished or partial), excluding the current one;
    the weekly report's "since" boundary."""
    if not table_exists("pipeline_runs"):
        return None
    with conn() as c:
        rows = _rows(c.execute(text("""
            SELECT * FROM pipeline_runs
             WHERE status IN ('finished', 'partial') AND run_id IS DISTINCT FROM :cur
             ORDER BY started_at DESC LIMIT 1"""), {"cur": before_run_id}))
    return rows[0] if rows else None


def now() -> datetime:
    return datetime.now()


# --- Weekly report inputs (brief §16) ------------------------------------------------

def weekly_inputs(run_id: str | None = None, since_days_fallback: int = 7) -> dict[str, Any]:
    """Everything the weekly report needs, scoped to the window since the previous
    completed run (fallback: last N days). Run-scoped tables (facts, achievements)
    use run_id when available, so 'new this week' is exact."""
    from career_history.db import _column_exists
    run = None
    if run_id and table_exists("pipeline_runs"):
        with conn() as c:
            rows = _rows(c.execute(text("SELECT * FROM pipeline_runs WHERE run_id = :r"), {"r": run_id}))
        run = rows[0] if rows else None
    prev = previous_finished_run(run_id)
    since = prev["started_at"] if prev else datetime.now() - timedelta(days=since_days_fallback)
    out: dict[str, Any] = {"run": run, "window": {"since": since, "previous_run": (prev or {}).get("run_id")}}
    with conn() as c:
        has_run_col = _column_exists(c, "knowledge_facts", "run_id")
        out["event_counts"] = {r["kind"]: int(r["n"]) for r in _rows(c.execute(text("""
            SELECT kind, COUNT(*) AS n FROM vault_events WHERE detected_at >= :since GROUP BY kind"""), {"since": since}))}
        out["deleted"] = _rows(c.execute(text("""
            SELECT file_path, payload ->> 'file_name' AS file_name FROM vault_events
             WHERE kind = 'deleted' AND detected_at >= :since ORDER BY detected_at DESC LIMIT 20"""), {"since": since}))
        fact_window = ("kf.run_id = :run" if (run_id and has_run_col) else "kf.created_at >= :since")
        params = {"run": run_id, "since": since}
        out["new_decisions"] = _rows(c.execute(text(f"""
            SELECT kf.id, kf.statement, kf.occurred_at, kf.created_at, fr.file_name, p.name AS project
              FROM knowledge_facts kf
              JOIN file_registry fr ON fr.id = kf.file_id
              LEFT JOIN project_files pf ON pf.file_id = kf.file_id
              LEFT JOIN projects p ON p.id = pf.project_id
             WHERE kf.kind = 'decision' AND {fact_window}
             ORDER BY kf.created_at DESC LIMIT 40"""), params))
        out["project_info"] = _rows(c.execute(text(f"""
            SELECT p.name AS project,
                   (SELECT COUNT(DISTINCT ve.file_id) FROM vault_events ve JOIN project_files pf2 ON pf2.file_id = ve.file_id
                     WHERE pf2.project_id = p.id AND ve.kind IN ('added','version_added') AND ve.detected_at >= :since) AS new_docs,
                   COUNT(kf.id) AS new_facts,
                   COUNT(kf.id) FILTER (WHERE kf.kind = 'decision') AS new_decisions
              FROM projects p
              JOIN project_files pf ON pf.project_id = p.id
              JOIN knowledge_facts kf ON kf.file_id = pf.file_id AND ({fact_window})
             WHERE p.status IS DISTINCT FROM 'REMOVED'
             GROUP BY p.id ORDER BY new_facts DESC LIMIT 20"""), params))
        if table_exists("achievements"):
            ach_window = "a.run_id = :run" if run_id else "a.created_at >= :since"
            out["new_achievements"] = _rows(c.execute(text(f"""
                SELECT a.id, a.statement, a.metric, a.is_me, p.name AS project
                  FROM achievements a LEFT JOIN projects p ON p.id = a.project_id
                 WHERE a.status <> 'rejected' AND ({ach_window})
                 ORDER BY a.confidence DESC LIMIT 30"""), params))
        else:
            out["new_achievements"] = []
        out["changed_information"] = _rows(c.execute(text("""
            SELECT pc.summary, pc.impact, pc.change_type, p.name AS project
              FROM project_changes pc JOIN projects p ON p.id = pc.project_id
             WHERE pc.change_type = 'fact_changed' AND pc.detected_at >= :since
             ORDER BY pc.detected_at DESC LIMIT 30"""), {"since": since})) if table_exists("project_changes") else []
        has_conf_run = _column_exists(c, "fact_conflicts", "run_id")
        out["conflicts"] = _rows(c.execute(text(f"""
            SELECT c.id, c.conflict_type, c.likely_latest_fact_id, p.name AS project,
                   a.statement AS statement_a, b.statement AS statement_b
              FROM fact_conflicts c
              LEFT JOIN projects p ON p.id = c.project_id
              JOIN knowledge_facts a ON a.id = c.fact_a_id JOIN knowledge_facts b ON b.id = c.fact_b_id
             WHERE c.status = 'needs_confirmation' AND (c.detected_at >= :since{" OR c.run_id = :run" if (has_conf_run and run_id) else ""})
             ORDER BY c.detected_at DESC LIMIT 30"""), params)) if table_exists("fact_conflicts") else []
        out["open_conflicts_total"] = int(c.execute(text(
            "SELECT COUNT(*) FROM fact_conflicts WHERE status = 'needs_confirmation'")).scalar() or 0) if table_exists("fact_conflicts") else 0
        out["stale"] = _rows(c.execute(text("""
            SELECT sf.reason, sf.newer_evidence_id, kf.statement, p.name AS project
              FROM stale_flags sf
              JOIN knowledge_facts kf ON kf.id = sf.object_id AND sf.object_type = 'fact'
              LEFT JOIN project_files pf ON pf.file_id = kf.file_id
              LEFT JOIN projects p ON p.id = pf.project_id
             WHERE sf.flagged_at >= :since
             ORDER BY sf.flagged_at DESC LIMIT 30"""), {"since": since})) if table_exists("stale_flags") else []
    return out

