"""Database layer. All SQL lives here; the rest of the app calls these functions."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from career_history import config
from career_history import envfile


_engine: Engine | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_connection_string(), pool_pre_ping=True, future=True)
    return _engine


def _connection_string() -> str:
    """Prefer database settings from .env, falling back to config.yaml."""
    envfile.load()
    keys = {
        "host": "ERA_VAULT_DB_HOST",
        "port": "ERA_VAULT_DB_PORT",
        "name": "ERA_VAULT_DB_NAME",
        "user": "ERA_VAULT_DB_USER",
        "password": "ERA_VAULT_DB_PASSWORD",
    }
    values = {name: os.environ.get(key, "") for name, key in keys.items()}
    if all(values.values()):
        return (
            f"postgresql://{values['user']}:{values['password']}"
            f"@{values['host']}:{values['port']}/{values['name']}"
        )
    return config.get()["database"]["connection_string"]


@contextmanager
def conn() -> Iterator[Any]:
    """Connection context: commit on success, rollback on error."""
    with engine().connect() as c:
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def init_schema(
    schema_path: str | Path = "schema.sql",
    *,
    apply_migrations: bool = True,
) -> None:
    sql = _strip_sql_comments(Path(schema_path).read_text())
    with conn() as c:
        _execute_sql(c, sql)
    if apply_migrations:
        migrate()


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    )


def _default_migrations_dir() -> Path:
    cwd_migrations = Path("migrations")
    if cwd_migrations.exists():
        return cwd_migrations
    return Path(__file__).resolve().parents[1] / "migrations"


def _migration_files(migrations_dir: str | Path | None = None) -> list[Path]:
    root = Path(migrations_dir) if migrations_dir else _default_migrations_dir()
    if not root.exists():
        return []
    return sorted(
        p for p in root.glob("*.sql")
        if not p.name.endswith(".rollback.sql")
    )


def _execute_sql(c: Any, sql: str) -> None:
    for stmt in _strip_sql_comments(sql).split(";"):
        s = stmt.strip()
        if s:
            c.execute(text(s))


def _ensure_migrations_table(c: Any) -> None:
    c.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            checksum    TEXT NOT NULL,
            applied_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def migrate(migrations_dir: str | Path | None = None) -> list[str]:
    applied: list[str] = []
    with conn() as c:
        _ensure_migrations_table(c)
        rows = c.execute(text(
            "SELECT version, checksum FROM schema_migrations"
        )).fetchall()
        known = {row[0]: row[1] for row in rows}
        for path in _migration_files(migrations_dir):
            version = path.stem
            sql = path.read_text()
            checksum = _checksum(sql)
            if version in known:
                if known[version] != checksum:
                    raise RuntimeError(
                        f"Migration checksum mismatch for {version}. "
                        "Create a new migration instead of editing an applied one."
                    )
                continue
            _execute_sql(c, sql)
            c.execute(text("""
                INSERT INTO schema_migrations (version, checksum)
                VALUES (:version, :checksum)
            """), {"version": version, "checksum": checksum})
            applied.append(version)
    return applied


_INDEX_DATA_TABLES = (
    "community_members",
    "graph_metadata",
    "communities",
    "graph_snapshots",
    "graph_extraction_state",
    "relationship_evidence",
    "entity_mentions",
    "relationships",
    "entities",
    "section_summaries",
    "document_summaries",
    "parent_chunks",
    "document_chunks",
    "document_sections",
    "documents",
    "processing_artifacts",
    "speaker_segments",
    "processing_queue",
    "file_registry",
    "known_speakers",
)


def truncate_index_data(
    *,
    confirm: str,
    expected_database: str = "era_vault",
) -> dict[str, Any]:
    """Clear all indexed Era Vault data while preserving schema and migrations.

    This is intentionally guarded because it is destructive. It keeps tables,
    indexes, pgvector, and ``schema_migrations`` intact, but removes registry
    rows, queue state, chunks, embeddings, cached conversions, graph data, and
    speaker rows. After running this, use ``update-documents`` or ``update`` to
    rebuild from the filesystem.

    Args:
        confirm: Must be exactly ``"TRUNCATE_ERA_VAULT_DATA"``.
        expected_database: Refuse to run unless ``current_database()`` matches.

    Returns:
        Row counts before truncation plus the database name.
    """
    if confirm != "TRUNCATE_ERA_VAULT_DATA":
        raise ValueError("Refusing to truncate index data without explicit confirmation.")

    table_counts_sql = "\nUNION ALL\n".join(
        f"SELECT '{table_name}' AS table_name, COUNT(*) AS row_count FROM {table_name}"
        for table_name in _INDEX_DATA_TABLES
    )
    truncate_sql = f"""
        TRUNCATE TABLE {", ".join(_INDEX_DATA_TABLES)}
        RESTART IDENTITY CASCADE
    """

    with conn() as c:
        database = c.execute(text("SELECT current_database()")).scalar_one()
        if database != expected_database:
            raise RuntimeError(
                f"Refusing to truncate {database!r}; expected {expected_database!r}."
            )

        counts = c.execute(text(table_counts_sql)).fetchall()
        before = {row.table_name: row.row_count for row in counts}
        c.execute(text(truncate_sql))

    return {
        "database": database,
        "tables": list(_INDEX_DATA_TABLES),
        "rows_before": before,
    }


def upsert_file(
    file_path: str,
    file_name: str,
    file_type: str,
    file_hash: str,
    folder: str,
    is_audio: bool,
    mod_time: datetime,
) -> tuple[int, bool]:
    with conn() as c:
        existing = c.execute(text(
            "SELECT id, file_hash FROM file_registry WHERE file_path = :p"
        ), {"p": file_path}).fetchone()
        if existing and existing[1] == file_hash:
            return existing[0], False
        row = c.execute(text("""
            INSERT INTO file_registry
                (file_path, file_name, file_type, file_hash, folder, is_audio, last_modified_at)
            VALUES (:path, :name, :type, :hash, :folder, :is_audio, :mod)
            ON CONFLICT (file_path) DO UPDATE SET
                file_hash = EXCLUDED.file_hash,
                file_name = EXCLUDED.file_name,
                file_type = EXCLUDED.file_type,
                folder = EXCLUDED.folder,
                is_audio = EXCLUDED.is_audio,
                last_modified_at = EXCLUDED.last_modified_at,
                last_processed_at = NOW()
            RETURNING id
        """), {
            "path": file_path, "name": file_name, "type": file_type,
            "hash": file_hash, "folder": folder, "is_audio": is_audio,
            "mod": mod_time,
        }).fetchone()
        return row[0], True


def delete_file(file_path: str) -> None:
    with conn() as c:
        c.execute(text("DELETE FROM file_registry WHERE file_path = :p"), {"p": file_path})


def all_registered_paths() -> list[str]:
    with conn() as c:
        return [r[0] for r in c.execute(text("SELECT file_path FROM file_registry")).fetchall()]


def enqueue(file_id: int) -> None:
    with conn() as c:
        c.execute(text("""
            INSERT INTO processing_queue (file_id, status, attempt_count)
            VALUES (:fid, 'pending', 0)
            ON CONFLICT (file_id) DO UPDATE SET
                status = 'pending',
                error_message = NULL,
                attempt_count = 0,
                discovered_at = NOW(),
                started_at = NULL,
                completed_at = NULL,
                stage_timings = '{}'::jsonb
        """), {"fid": file_id})


def pending_files(
    folder: str | None = None,
    limit: int | None = None,
    run_settings: config.RunSettings | None = None,
) -> list[dict[str, Any]]:
    settings = config.normalize_run_settings(run_settings)
    where = "pq.status NOT IN ('done', 'failed')"
    params: dict[str, Any] = {}
    if folder:
        where += " AND fr.folder = :folder"
        params["folder"] = folder
    if settings["file_kind"] == "documents":
        where += " AND fr.is_audio = false"
    elif settings["file_kind"] == "audio":
        where += " AND fr.is_audio = true"
    sql = f"""
        SELECT pq.id AS id, pq.file_id, pq.status, pq.attempt_count,
               fr.file_path, fr.file_name, fr.file_type, fr.is_audio, fr.folder,
               fr.file_hash
          FROM processing_queue pq
          JOIN file_registry fr ON fr.id = pq.file_id
         WHERE {where}
         ORDER BY fr.folder, fr.file_name
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), params).fetchall()]


def set_status(
    queue_id: int,
    status: str,
    error: str | None = None,
    stage: str | None = None,
    stage_seconds: float | None = None,
) -> None:
    with conn() as c:
        if status == "done":
            c.execute(text("""
                UPDATE processing_queue
                   SET status = 'done', completed_at = NOW(), error_message = NULL
                 WHERE id = :id
            """), {"id": queue_id})
        elif status == "failed":
            c.execute(text("""
                UPDATE processing_queue
                   SET status = 'failed', error_message = :err,
                       completed_at = NOW(), attempt_count = attempt_count + 1
                 WHERE id = :id
            """), {"id": queue_id, "err": error})
        else:
            c.execute(text("""
                UPDATE processing_queue
                   SET status = :s,
                       started_at = COALESCE(started_at, NOW())
                 WHERE id = :id
            """), {"id": queue_id, "s": status})
        if stage and stage_seconds is not None:
            c.execute(text("""
                UPDATE processing_queue
                   SET stage_timings = stage_timings || jsonb_build_object(:k, :v)
                 WHERE id = :id
            """), {"id": queue_id, "k": stage, "v": stage_seconds})


def status_summary(folder: str | None = None) -> dict[str, int]:
    params: dict[str, Any] = {}
    where = ""
    if folder:
        where = "WHERE fr.folder = :folder"
        params["folder"] = folder
    with conn() as c:
        rows = c.execute(text(f"""
            SELECT pq.status, COUNT(*) AS n
              FROM processing_queue pq
              JOIN file_registry fr ON fr.id = pq.file_id
             {where}
             GROUP BY pq.status
        """), params).fetchall()
        return {r[0]: r[1] for r in rows}


def retry_failed(folder: str | None = None) -> int:
    where = "status = 'failed'"
    params: dict[str, Any] = {}
    if folder:
        where += " AND file_id IN (SELECT id FROM file_registry WHERE folder = :folder)"
        params["folder"] = folder
    with conn() as c:
        result = c.execute(text(f"""
            UPDATE processing_queue
               SET status = 'pending', error_message = NULL,
                   started_at = NULL, completed_at = NULL
             WHERE {where}
        """), params)
        return result.rowcount


def reindex_documents_v2(
    folder: str | None = None,
    limit: int | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    candidates = _v2_reindex_candidates(folder=folder, limit=limit)
    if dry_run or not candidates:
        return {"dry_run": dry_run, "folder": folder, "matched": len(candidates), "enqueued": 0, "candidates": candidates}
    enqueued = 0
    with conn() as c:
        for row in candidates:
            c.execute(text("""
                INSERT INTO processing_queue (file_id, status, attempt_count)
                VALUES (:file_id, 'pending', 0)
                ON CONFLICT (file_id) DO UPDATE SET
                    status = 'pending',
                    error_message = NULL,
                    attempt_count = 0,
                    discovered_at = NOW(),
                    started_at = NULL,
                    completed_at = NULL,
                    stage_timings = '{}'::jsonb
            """), {"file_id": row["file_id"]})
            enqueued += 1
    return {"dry_run": dry_run, "folder": folder, "matched": len(candidates), "enqueued": enqueued, "candidates": candidates}


def _v2_reindex_candidates(folder: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where = ["fr.is_audio = false", "(pq.status IS NULL OR pq.status IN ('done', 'failed', 'pending'))"]
    where.append("""
        (
            d.file_id IS NULL
            OR COALESCE(sec.section_count, 0) = 0
            OR COALESCE(ch.total_chunks, 0) = 0
            OR COALESCE(ch.chunks_with_sections, 0) < COALESCE(ch.total_chunks, 0)
        )
    """)
    if folder:
        where.append("fr.folder = :folder")
        params["folder"] = folder
    sql = f"""
        SELECT fr.id AS file_id, fr.file_name, fr.file_path, fr.folder,
               COALESCE(pq.status, 'unqueued') AS queue_status,
               d.structure_version,
               COALESCE(sec.section_count, 0) AS section_count,
               COALESCE(ch.total_chunks, 0) AS total_chunks,
               COALESCE(ch.chunks_with_sections, 0) AS chunks_with_sections
          FROM file_registry fr
          LEFT JOIN processing_queue pq ON pq.file_id = fr.id
          LEFT JOIN documents d ON d.file_id = fr.id
          LEFT JOIN (
                SELECT file_id, COUNT(*) AS section_count
                  FROM document_sections GROUP BY file_id
          ) sec ON sec.file_id = fr.id
          LEFT JOIN (
                SELECT file_id, COUNT(*) AS total_chunks,
                       COUNT(section_id) AS chunks_with_sections
                  FROM document_chunks GROUP BY file_id
          ) ch ON ch.file_id = fr.id
         WHERE {" AND ".join(where)}
         ORDER BY fr.folder, fr.file_name
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), params).fetchall()]


def reindex_documents(
    folder: str | None = None,
    limit: int | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Re-enqueue existing document files for full conversion and embedding."""
    candidates = _document_reindex_candidates(folder=folder, limit=limit)
    if dry_run or not candidates:
        return {
            "dry_run": dry_run,
            "folder": folder,
            "matched": len(candidates),
            "enqueued": 0,
            "candidates": candidates,
        }
    enqueued = 0
    with conn() as c:
        for row in candidates:
            c.execute(text("""
                INSERT INTO processing_queue (file_id, status, attempt_count)
                VALUES (:file_id, 'pending', 0)
                ON CONFLICT (file_id) DO UPDATE SET
                    status = 'pending',
                    error_message = NULL,
                    attempt_count = 0,
                    discovered_at = NOW(),
                    started_at = NULL,
                    completed_at = NULL,
                    stage_timings = '{}'::jsonb
            """), {"file_id": row["file_id"]})
            enqueued += 1
    return {
        "dry_run": dry_run,
        "folder": folder,
        "matched": len(candidates),
        "enqueued": enqueued,
        "candidates": candidates,
    }


def _document_reindex_candidates(
    folder: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where = [
        "fr.is_audio = false",
        "(pq.status IS NULL OR pq.status IN ('done', 'failed', 'pending'))",
    ]
    if folder:
        where.append("fr.folder = :folder")
        params["folder"] = folder
    sql = f"""
        SELECT fr.id AS file_id, fr.file_name, fr.file_path, fr.folder,
               COALESCE(pq.status, 'unqueued') AS queue_status
          FROM file_registry fr
          LEFT JOIN processing_queue pq ON pq.file_id = fr.id
         WHERE {" AND ".join(where)}
         ORDER BY fr.folder, fr.file_name
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), params).fetchall()]


def reindex_audio(
    folder: str | None = None,
    limit: int | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Re-enqueue existing audio files for full re-transcription and embedding.

    Useful after changing the transcription backend or decode settings (e.g. the
    MLX Whisper switch): already-`done` audio is not otherwise re-processed.
    """
    candidates = _audio_reindex_candidates(folder=folder, limit=limit)
    if dry_run or not candidates:
        return {
            "dry_run": dry_run,
            "folder": folder,
            "matched": len(candidates),
            "enqueued": 0,
            "candidates": candidates,
        }
    enqueued = 0
    with conn() as c:
        for row in candidates:
            c.execute(text("""
                INSERT INTO processing_queue (file_id, status, attempt_count)
                VALUES (:file_id, 'pending', 0)
                ON CONFLICT (file_id) DO UPDATE SET
                    status = 'pending',
                    error_message = NULL,
                    attempt_count = 0,
                    discovered_at = NOW(),
                    started_at = NULL,
                    completed_at = NULL,
                    stage_timings = '{}'::jsonb
            """), {"file_id": row["file_id"]})
            enqueued += 1
    return {
        "dry_run": dry_run,
        "folder": folder,
        "matched": len(candidates),
        "enqueued": enqueued,
        "candidates": candidates,
    }


def _audio_reindex_candidates(
    folder: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where = [
        "fr.is_audio = true",
        "(pq.status IS NULL OR pq.status IN ('done', 'failed', 'pending'))",
    ]
    if folder:
        where.append("fr.folder = :folder")
        params["folder"] = folder
    sql = f"""
        SELECT fr.id AS file_id, fr.file_name, fr.file_path, fr.folder,
               COALESCE(pq.status, 'unqueued') AS queue_status
          FROM file_registry fr
          LEFT JOIN processing_queue pq ON pq.file_id = fr.id
         WHERE {" AND ".join(where)}
         ORDER BY fr.folder, fr.file_name
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), params).fetchall()]


def get_converted_markdown(
    file_id: int, source_hash: str, version: str
) -> str | None:
    """Return cached Docling markdown for this file+content+conversion version."""
    with conn() as c:
        row = c.execute(text("""
            SELECT payload->>'markdown' AS markdown
              FROM processing_artifacts
             WHERE file_id = :fid
               AND artifact_type = 'converted_markdown'
               AND artifact_version = :ver
               AND source_hash = :hash
             LIMIT 1
        """), {"fid": file_id, "ver": version, "hash": source_hash}).fetchone()
        return row[0] if row else None


def put_converted_markdown(
    file_id: int, source_hash: str, version: str, markdown: str
) -> None:
    """Persist Docling markdown so future re-embeds can skip conversion."""
    with conn() as c:
        c.execute(text("""
            INSERT INTO processing_artifacts
                (file_id, artifact_type, artifact_version, source_hash,
                 payload, updated_at)
            VALUES (:fid, 'converted_markdown', :ver, :hash,
                    CAST(:payload AS jsonb), NOW())
            ON CONFLICT (file_id, artifact_type, artifact_version, source_hash)
            DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
        """), {
            "fid": file_id,
            "ver": version,
            "hash": source_hash,
            "payload": json.dumps({"markdown": markdown}),
        })


def replace_parent_chunks(
    file_id: int,
    parents: list[dict[str, Any]],
    section_ids: dict[int, int],
) -> dict[int, int]:
    """Replace this file's parent chunks; return {local_id: parent_chunk_id}.

    Old children's parent_chunk_id is cleared first so deleting old parents does
    not violate the FK (it is ON DELETE SET NULL, but clearing is explicit and
    keeps behavior obvious). Children are re-inserted by replace_chunks after.
    """
    id_map: dict[int, int] = {}
    with conn() as c:
        c.execute(
            text("UPDATE document_chunks SET parent_chunk_id = NULL WHERE file_id = :fid"),
            {"fid": file_id},
        )
        c.execute(text("DELETE FROM parent_chunks WHERE file_id = :fid"), {"fid": file_id})
        for parent in parents:
            local_section = parent.get("section_local_id")
            row = c.execute(text("""
                INSERT INTO parent_chunks
                    (file_id, section_id, ordinal, content, token_estimate, metadata)
                VALUES (:fid, :section_id, :ordinal, :content, :token_estimate,
                        CAST(:metadata AS jsonb))
                RETURNING id
            """), {
                "fid": file_id,
                "section_id": section_ids.get(local_section) if local_section is not None else None,
                "ordinal": parent.get("ordinal", 0),
                "content": parent["content"],
                "token_estimate": parent.get("token_estimate"),
                "metadata": json.dumps(parent.get("metadata", {})),
            }).fetchone()
            id_map[parent["local_id"]] = row[0]
        return id_map


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


def replace_chunks(file_id: int, chunks: list[dict[str, Any]]) -> None:
    uses_v2_columns = any(
        any(key in ch for key in (
            "section_id", "chunk_type", "content_raw", "content_contextual",
            "embedding_content_version", "token_estimate", "parent_chunk_id",
        ))
        for ch in chunks
    )
    with conn() as c:
        c.execute(text("DELETE FROM document_chunks WHERE file_id = :fid"), {"fid": file_id})
        for i, ch in enumerate(chunks):
            params = {
                "fid": file_id,
                "idx": i,
                "content": ch["content"],
                "emb": _vec_literal(ch["embedding"]),
                "sid": ch.get("segment_id"),
                "meta": json.dumps(ch.get("metadata", {})),
            }
            if not uses_v2_columns:
                c.execute(text("""
                    INSERT INTO document_chunks
                        (file_id, chunk_index, content, embedding,
                         speaker_segment_id, metadata)
                    VALUES (:fid, :idx, :content, CAST(:emb AS vector), :sid, CAST(:meta AS jsonb))
                """), params)
                continue
            params.update({
                "section_id": ch.get("section_id"),
                "parent_chunk_id": ch.get("parent_chunk_id"),
                "chunk_type": ch.get("chunk_type"),
                "content_raw": ch.get("content_raw"),
                "content_contextual": ch.get("content_contextual"),
                "embedding_content_version": ch.get("embedding_content_version"),
                "token_estimate": ch.get("token_estimate"),
                "search_text": ch.get("search_text")
                or ch.get("content_raw")
                or ch["content"],
            })
            c.execute(text("""
                INSERT INTO document_chunks
                    (file_id, chunk_index, content, embedding,
                     speaker_segment_id, metadata, section_id, parent_chunk_id,
                     chunk_type, content_raw, content_contextual,
                     embedding_content_version, token_estimate, search_vector)
                VALUES (
                    :fid, :idx, :content, CAST(:emb AS vector), :sid,
                    CAST(:meta AS jsonb), :section_id, :parent_chunk_id,
                    :chunk_type, :content_raw, :content_contextual,
                    :embedding_content_version, :token_estimate,
                    to_tsvector('simple', COALESCE(:search_text, ''))
                )
            """), params)


def replace_document_structure(file_id: int, document: dict[str, Any]) -> dict[int, int]:
    sections = document.get("sections", [])
    with conn() as c:
        c.execute(text("""
            INSERT INTO documents
                (file_id, title, structure_version, parse_metadata, updated_at)
            VALUES (:fid, :title, :structure_version, CAST(:parse_metadata AS jsonb), NOW())
            ON CONFLICT (file_id) DO UPDATE SET
                title = EXCLUDED.title,
                structure_version = EXCLUDED.structure_version,
                parse_metadata = EXCLUDED.parse_metadata,
                updated_at = NOW()
        """), {
            "fid": file_id,
            "title": document.get("title"),
            "structure_version": document.get("structure_version"),
            "parse_metadata": json.dumps(document.get("parse_metadata", {})),
        })
        c.execute(text("DELETE FROM document_sections WHERE file_id = :fid"), {"fid": file_id})
        id_map: dict[int, int] = {}
        for section in sections:
            parent_local_id = section.get("parent_local_id")
            row = c.execute(text("""
                INSERT INTO document_sections
                    (file_id, parent_section_id, level, title, section_path,
                     ordinal, start_offset, end_offset, metadata)
                VALUES (
                    :fid, :parent_section_id, :level, :title, :section_path,
                    :ordinal, :start_offset, :end_offset, CAST(:metadata AS jsonb)
                )
                RETURNING id
            """), {
                "fid": file_id,
                "parent_section_id": id_map.get(parent_local_id) if parent_local_id is not None else None,
                "level": section["level"],
                "title": section["title"],
                "section_path": section["section_path"],
                "ordinal": section["ordinal"],
                "start_offset": section.get("start_offset"),
                "end_offset": section.get("end_offset"),
                "metadata": json.dumps(section.get("metadata", {})),
            }).fetchone()
            id_map[section["local_id"]] = row[0]
        return id_map


def v2_document_status(file_query: str) -> dict[str, Any]:
    with conn() as c:
        row = c.execute(text("""
            SELECT id, file_name, file_path, folder, is_audio
              FROM file_registry
             WHERE file_path = :query
                OR file_name = :query
                OR file_path ILIKE :like_query
             ORDER BY last_processed_at DESC
             LIMIT 1
        """), {"query": file_query, "like_query": f"%{file_query}%"}).fetchone()
        if row is None:
            return {"found": False, "query": file_query}
        file_id = row[0]
        doc = c.execute(text("""
            SELECT title, structure_version, parse_metadata, updated_at
              FROM documents WHERE file_id = :fid
        """), {"fid": file_id}).fetchone()
        section_count = c.execute(text("""
            SELECT COUNT(*) FROM document_sections WHERE file_id = :fid
        """), {"fid": file_id}).scalar_one()
        chunk_row = c.execute(text("""
            SELECT COUNT(*) AS total_chunks,
                   COUNT(section_id) AS chunks_with_sections,
                   COUNT(content_raw) AS chunks_with_raw,
                   COUNT(content_contextual) AS chunks_with_contextual,
                   COUNT(search_vector) AS chunks_with_search_vector,
                   COUNT(DISTINCT chunk_type) AS chunk_type_count
              FROM document_chunks WHERE file_id = :fid
        """), {"fid": file_id}).fetchone()
        chunk_types = c.execute(text("""
            SELECT COALESCE(chunk_type, 'unknown') AS chunk_type, COUNT(*) AS n
              FROM document_chunks WHERE file_id = :fid
             GROUP BY COALESCE(chunk_type, 'unknown')
             ORDER BY n DESC, chunk_type
        """), {"fid": file_id}).fetchall()
        return {
            "found": True,
            "file_id": file_id,
            "file_name": row[1],
            "file_path": row[2],
            "folder": row[3],
            "is_audio": row[4],
            "document": dict(doc._mapping) if doc else None,
            "section_count": section_count,
            "chunks": dict(chunk_row._mapping),
            "chunk_types": [dict(r._mapping) for r in chunk_types],
        }


def graph_chunks_for_extraction(
    folder: str | None = None,
    limit: int | None = None,
    extractor_version: str = "entity-relationship-v1",
    force: bool = False,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"extractor_version": extractor_version}
    where = ["dc.content IS NOT NULL", "length(trim(dc.content)) > 0"]
    if folder:
        where.append("fr.folder = :folder")
        params["folder"] = folder
    if not force:
        where.append("""
            (
                ges.chunk_id IS NULL
                OR ges.extractor_version <> :extractor_version
                OR ges.status = 'failed'
            )
        """)
    sql = f"""
        SELECT dc.id AS chunk_id, dc.file_id, dc.section_id,
               dc.chunk_index, dc.content, dc.metadata,
               fr.file_name, fr.folder, fr.file_hash,
               ds.section_path,
               ges.content_hash AS prior_content_hash,
               ges.status AS prior_status
          FROM document_chunks dc
          JOIN file_registry fr ON fr.id = dc.file_id
          LEFT JOIN document_sections ds ON ds.id = dc.section_id
          LEFT JOIN graph_extraction_state ges ON ges.chunk_id = dc.id
         WHERE {" AND ".join(where)}
         ORDER BY fr.folder, fr.file_name, dc.chunk_index
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn() as c:
        rows = c.execute(text(sql), params).fetchall()
        items = [dict(r._mapping) for r in rows]
        for item in items:
            item["content_hash"] = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
        return [
            item for item in items
            if force
            or item.get("prior_content_hash") != item["content_hash"]
            or item.get("prior_content_hash") is None
            or item.get("prior_status") == "failed"
        ]


def documents_for_extraction(
    folder: str | None = None,
    limit: int | None = None,
    extractor_version: str = "doc-entity-facts-v1",
    force: bool = False,
    max_chars: int = 12000,
) -> list[dict[str, Any]]:
    """One row per FILE for document-level extraction: representative (first)
    chunk id, the file's chunks concatenated + capped to ``max_chars``, and a
    content hash over the full text. Incremental + folder-scoped: skips files
    whose representative chunk is already extracted at ``extractor_version`` with
    the same content (unless ``force``)."""
    params: dict[str, Any] = {"extractor_version": extractor_version, "max_chars": max_chars}
    doc_where = ["dc.content IS NOT NULL", "length(trim(dc.content)) > 0"]
    if folder:
        doc_where.append("fr.folder = :folder")
        params["folder"] = folder
    state_where = "" if force else (
        "WHERE ges.chunk_id IS NULL "
        "OR ges.extractor_version <> :extractor_version "
        "OR ges.content_hash <> d.content_hash "
        "OR ges.status = 'failed'"
    )
    sql = f"""
        WITH docs AS (
            SELECT fr.id AS file_id, fr.file_name, fr.folder,
                   min(dc.id) AS rep_chunk_id,
                   left(string_agg(dc.content, ' ' ORDER BY dc.chunk_index), :max_chars) AS content,
                   md5(string_agg(coalesce(dc.content, ''), '' ORDER BY dc.chunk_index)) AS content_hash
              FROM document_chunks dc
              JOIN file_registry fr ON fr.id = dc.file_id
             WHERE {" AND ".join(doc_where)}
             GROUP BY fr.id, fr.file_name, fr.folder
        )
        SELECT d.file_id, d.file_name, d.folder, d.rep_chunk_id, d.content, d.content_hash
          FROM docs d
          LEFT JOIN graph_extraction_state ges ON ges.chunk_id = d.rep_chunk_id
         {state_where}
         ORDER BY d.folder, d.file_name
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn() as c:
        rows = c.execute(text(sql), params).fetchall()
    return [dict(r._mapping) for r in rows]


def clear_chunk_graph_data(chunk_id: int) -> None:
    with conn() as c:
        c.execute(text("DELETE FROM relationship_evidence WHERE chunk_id = :chunk_id"), {"chunk_id": chunk_id})
        c.execute(text("DELETE FROM entity_mentions WHERE chunk_id = :chunk_id"), {"chunk_id": chunk_id})
        c.execute(text("DELETE FROM knowledge_facts WHERE chunk_id = :chunk_id"), {"chunk_id": chunk_id})


def mark_graph_chunk_extracted(
    chunk_id: int,
    content_hash: str,
    extractor_version: str,
    status: str = "done",
    error_message: str | None = None,
) -> None:
    with conn() as c:
        c.execute(text("""
            INSERT INTO graph_extraction_state
                (chunk_id, content_hash, extractor_version, status, error_message, extracted_at)
            VALUES (:chunk_id, :content_hash, :extractor_version, :status, :error_message, NOW())
            ON CONFLICT (chunk_id) DO UPDATE SET
                content_hash = EXCLUDED.content_hash,
                extractor_version = EXCLUDED.extractor_version,
                status = EXCLUDED.status,
                error_message = EXCLUDED.error_message,
                extracted_at = NOW()
        """), {
            "chunk_id": chunk_id,
            "content_hash": content_hash,
            "extractor_version": extractor_version,
            "status": status,
            "error_message": error_message,
        })


def upsert_entity(
    canonical_name: str,
    entity_type: str,
    aliases: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    with conn() as c:
        row = c.execute(text("""
            INSERT INTO entities
                (canonical_name, entity_type, aliases, metadata, updated_at)
            VALUES (:canonical_name, :entity_type, CAST(:aliases AS jsonb),
                    CAST(:metadata AS jsonb), NOW())
            ON CONFLICT (canonical_name, entity_type) DO UPDATE SET
                aliases = COALESCE((
                    SELECT jsonb_agg(DISTINCT value)
                      FROM jsonb_array_elements_text(
                        entities.aliases || EXCLUDED.aliases
                      ) AS merged_aliases(value)
                ), '[]'::jsonb),
                metadata = entities.metadata || EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
        """), {
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "aliases": json.dumps(aliases or []),
            "metadata": json.dumps(metadata or {}),
        }).fetchone()
        return row[0]


def insert_entity_mention(
    entity_id: int,
    file_id: int,
    chunk_id: int,
    section_id: int | None,
    mention_text: str,
    confidence: float,
    extractor_version: str,
) -> int:
    with conn() as c:
        row = c.execute(text("""
            INSERT INTO entity_mentions
                (entity_id, file_id, chunk_id, section_id, mention_text,
                 confidence, extractor_version)
            VALUES
                (:entity_id, :file_id, :chunk_id, :section_id, :mention_text,
                 :confidence, :extractor_version)
            RETURNING id
        """), {
            "entity_id": entity_id,
            "file_id": file_id,
            "chunk_id": chunk_id,
            "section_id": section_id,
            "mention_text": mention_text,
            "confidence": confidence,
            "extractor_version": extractor_version,
        }).fetchone()
        return row[0]


def upsert_relationship(
    source_entity_id: int,
    relationship_type: str,
    target_entity_id: int,
    confidence: float,
    metadata: dict[str, Any] | None = None,
) -> int:
    with conn() as c:
        row = c.execute(text("""
            INSERT INTO relationships
                (source_entity_id, relationship_type, target_entity_id,
                 confidence, metadata, updated_at)
            VALUES
                (:source_entity_id, :relationship_type, :target_entity_id,
                 :confidence, CAST(:metadata AS jsonb), NOW())
            ON CONFLICT (source_entity_id, relationship_type, target_entity_id)
            DO UPDATE SET
                confidence = GREATEST(
                    COALESCE(relationships.confidence, 0),
                    COALESCE(EXCLUDED.confidence, 0)
                ),
                metadata = relationships.metadata || EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
        """), {
            "source_entity_id": source_entity_id,
            "relationship_type": relationship_type,
            "target_entity_id": target_entity_id,
            "confidence": confidence,
            "metadata": json.dumps(metadata or {}),
        }).fetchone()
        return row[0]


def insert_relationship_evidence(
    relationship_id: int,
    file_id: int,
    chunk_id: int,
    section_id: int | None,
    evidence_text: str,
    extractor_version: str,
) -> int:
    with conn() as c:
        row = c.execute(text("""
            INSERT INTO relationship_evidence
                (relationship_id, file_id, chunk_id, section_id,
                 evidence_text, extractor_version)
            VALUES
                (:relationship_id, :file_id, :chunk_id, :section_id,
                 :evidence_text, :extractor_version)
            RETURNING id
        """), {
            "relationship_id": relationship_id,
            "file_id": file_id,
            "chunk_id": chunk_id,
            "section_id": section_id,
            "evidence_text": evidence_text,
            "extractor_version": extractor_version,
        }).fetchone()
        return row[0]


def files_for_seeding(folder: str | None = None) -> list[dict[str, Any]]:
    """All registered files (id + path) for deterministic entity seeding."""
    sql = "SELECT id AS file_id, file_path FROM file_registry"
    params: dict[str, Any] = {}
    if folder:
        sql += " WHERE folder = :folder"
        params["folder"] = folder
    with conn() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), params).fetchall()]


def clear_seed_mentions(extractor_version: str, folder: str | None = None) -> None:
    """Remove prior deterministic-seed mentions so re-seeding never duplicates."""
    sql = "DELETE FROM entity_mentions WHERE extractor_version = :v"
    params: dict[str, Any] = {"v": extractor_version}
    if folder:
        sql += " AND file_id IN (SELECT id FROM file_registry WHERE folder = :folder)"
        params["folder"] = folder
    with conn() as c:
        c.execute(text(sql), params)


def insert_fact(
    kind: str,
    statement: str,
    file_id: int,
    chunk_id: int | None,
    subject_entity_id: int | None = None,
    object_entity_id: int | None = None,
    project_entity_id: int | None = None,
    attributes: dict[str, Any] | None = None,
    occurred_at: str | None = None,
    source_quote: str | None = None,
    confidence: float | None = None,
    extractor_version: str = "entity-rel-facts-v2",
) -> int:
    """Insert one structured fact (decision/commitment/event). Facts are cleared
    per-chunk before re-extraction (see clear_chunk_graph_data), so no upsert."""
    with conn() as c:
        row = c.execute(text("""
            INSERT INTO knowledge_facts
                (kind, statement, subject_entity_id, object_entity_id, project_entity_id,
                 attributes, occurred_at, file_id, chunk_id, source_quote, confidence,
                 extractor_version)
            VALUES
                (:kind, :statement, :subject_entity_id, :object_entity_id, :project_entity_id,
                 CAST(:attributes AS jsonb), CAST(:occurred_at AS timestamp), :file_id, :chunk_id,
                 :source_quote, :confidence, :extractor_version)
            RETURNING id
        """), {
            "kind": kind,
            "statement": statement,
            "subject_entity_id": subject_entity_id,
            "object_entity_id": object_entity_id,
            "project_entity_id": project_entity_id,
            "attributes": json.dumps(attributes or {}),
            "occurred_at": occurred_at,
            "file_id": file_id,
            "chunk_id": chunk_id,
            "source_quote": source_quote,
            "confidence": confidence,
            "extractor_version": extractor_version,
        }).fetchone()
        return row[0]


def cleanup_orphan_graph_rows() -> None:
    with conn() as c:
        c.execute(text("""
            DELETE FROM relationships r
             WHERE NOT EXISTS (
                SELECT 1 FROM relationship_evidence re
                 WHERE re.relationship_id = r.id
             )
        """))
        c.execute(text("""
            DELETE FROM entities e
             WHERE NOT EXISTS (
                SELECT 1 FROM entity_mentions em WHERE em.entity_id = e.id
             )
             AND NOT EXISTS (
                SELECT 1 FROM relationships r
                 WHERE r.source_entity_id = e.id OR r.target_entity_id = e.id
             )
        """))


def graph_snapshot_rows(folder: str | None = None) -> dict[str, list[dict[str, Any]]]:
    params: dict[str, Any] = {}
    mention_where = ""
    evidence_where = ""
    if folder:
        params["folder"] = folder
        mention_where = "WHERE fr.folder = :folder"
        evidence_where = "WHERE fr.folder = :folder"
    with conn() as c:
        entities_rows = c.execute(text(f"""
            SELECT e.id, e.canonical_name, e.entity_type, e.aliases, e.metadata,
                   COUNT(em.id) AS mention_count,
                   COUNT(DISTINCT em.file_id) AS file_count,
                   AVG(COALESCE(em.confidence, 0)) AS avg_confidence
              FROM entities e
              JOIN entity_mentions em ON em.entity_id = e.id
              JOIN file_registry fr ON fr.id = em.file_id
             {mention_where}
             GROUP BY e.id, e.canonical_name, e.entity_type, e.aliases, e.metadata
             ORDER BY mention_count DESC, e.canonical_name
        """), params).fetchall()
        file_rows = c.execute(text(f"""
            SELECT fr.id, fr.file_name, fr.folder, fr.is_audio,
                   COUNT(DISTINCT em.entity_id) AS entity_count,
                   COUNT(em.id) AS mention_count
              FROM file_registry fr
              JOIN entity_mentions em ON em.file_id = fr.id
             {"WHERE fr.folder = :folder" if folder else ""}
             GROUP BY fr.id, fr.file_name, fr.folder, fr.is_audio
             ORDER BY mention_count DESC, fr.file_name
        """), params).fetchall()
        mention_edges = c.execute(text(f"""
            SELECT em.entity_id, em.file_id, COUNT(*) AS mention_count,
                   AVG(COALESCE(em.confidence, 0)) AS avg_confidence
              FROM entity_mentions em
              JOIN file_registry fr ON fr.id = em.file_id
             {mention_where}
             GROUP BY em.entity_id, em.file_id
        """), params).fetchall()
        relationship_rows = c.execute(text(f"""
            SELECT r.id, r.source_entity_id, r.target_entity_id,
                   r.relationship_type, r.confidence, r.metadata,
                   COUNT(re.id) AS evidence_count,
                   COUNT(DISTINCT re.file_id) AS file_count
              FROM relationships r
              JOIN relationship_evidence re ON re.relationship_id = r.id
              JOIN file_registry fr ON fr.id = re.file_id
             {evidence_where}
             GROUP BY r.id, r.source_entity_id, r.target_entity_id,
                      r.relationship_type, r.confidence, r.metadata
             ORDER BY evidence_count DESC, r.relationship_type
        """), params).fetchall()
        community_rows = c.execute(text("""
            SELECT c.id, c.name, c.summary, c.algorithm, c.algorithm_version,
                   COUNT(cm.id) AS member_count
              FROM communities c
              LEFT JOIN community_members cm ON cm.community_id = c.id
             GROUP BY c.id, c.name, c.summary, c.algorithm, c.algorithm_version
             ORDER BY member_count DESC, c.name
        """)).fetchall()
        metadata_rows = c.execute(text("""
            SELECT object_type, object_id, node_type, node_weight,
                   node_degree, edge_weight, edge_confidence,
                   export_eligible, metrics
              FROM graph_metadata
             WHERE export_eligible = true
        """)).fetchall()
    return {
        "entities": [dict(r._mapping) for r in entities_rows],
        "files": [dict(r._mapping) for r in file_rows],
        "mentions": [dict(r._mapping) for r in mention_edges],
        "relationships": [dict(r._mapping) for r in relationship_rows],
        "communities": [dict(r._mapping) for r in community_rows],
        "graph_metadata": [dict(r._mapping) for r in metadata_rows],
    }


def save_graph_snapshot(
    scope: str,
    source_hash: str,
    extraction_version: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    node_count = len(payload.get("nodes", []))
    edge_count = len(payload.get("edges", []))
    with conn() as c:
        c.execute(text("""
            UPDATE graph_snapshots
               SET is_current = false
             WHERE scope = :scope AND is_current = true
        """), {"scope": scope})
        row = c.execute(text("""
            INSERT INTO graph_snapshots
                (scope, source_hash, extraction_version, payload,
                 node_count, edge_count, is_current)
            VALUES
                (:scope, :source_hash, :extraction_version, CAST(:payload AS jsonb),
                 :node_count, :edge_count, true)
            RETURNING id, scope, source_hash, extraction_version,
                      node_count, edge_count, created_at
        """), {
            "scope": scope,
            "source_hash": source_hash,
            "extraction_version": extraction_version,
            "payload": json.dumps(payload),
            "node_count": node_count,
            "edge_count": edge_count,
        }).fetchone()
        return dict(row._mapping)


def latest_graph_snapshot(scope: str = "all") -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute(text("""
            SELECT id, scope, source_hash, extraction_version, payload,
                   node_count, edge_count, created_at
              FROM graph_snapshots
             WHERE scope = :scope AND is_current = true
             ORDER BY created_at DESC LIMIT 1
        """), {"scope": scope}).fetchone()
        return dict(row._mapping) if row else None


def graph_status(scope: str = "all") -> dict[str, Any]:
    with conn() as c:
        states = c.execute(text("""
            SELECT status, COUNT(*) AS n
              FROM graph_extraction_state GROUP BY status
        """)).fetchall()
        snapshot = c.execute(text("""
            SELECT id, scope, source_hash, extraction_version,
                   node_count, edge_count, created_at
              FROM graph_snapshots
             WHERE scope = :scope AND is_current = true
             ORDER BY created_at DESC LIMIT 1
        """), {"scope": scope}).fetchone()
    return {
        "scope": scope,
        "extraction": {row[0]: row[1] for row in states},
        "snapshot": dict(snapshot._mapping) if snapshot else None,
    }


def v3_documents_for_summary(folder: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where = ["d.id IS NOT NULL"]
    if folder:
        where.append("fr.folder = :folder")
        params["folder"] = folder
    sql = f"""
        SELECT d.id AS document_id, d.file_id,
               COALESCE(d.title, fr.file_name) AS title,
               fr.file_name, fr.folder, fr.file_hash,
               string_agg(dc.content, E'\n\n' ORDER BY dc.chunk_index) AS content
          FROM documents d
          JOIN file_registry fr ON fr.id = d.file_id
          JOIN document_chunks dc ON dc.file_id = fr.id
         WHERE {" AND ".join(where)}
         GROUP BY d.id, d.file_id, d.title, fr.file_name, fr.folder, fr.file_hash
         ORDER BY fr.folder, fr.file_name
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), params).fetchall()]


def v3_sections_for_summary(folder: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where = ["ds.id IS NOT NULL"]
    if folder:
        where.append("fr.folder = :folder")
        params["folder"] = folder
    sql = f"""
        SELECT ds.id AS section_id, ds.file_id, ds.title, ds.section_path,
               fr.file_name, fr.folder, fr.file_hash,
               string_agg(dc.content, E'\n\n' ORDER BY dc.chunk_index) AS content
          FROM document_sections ds
          JOIN file_registry fr ON fr.id = ds.file_id
          JOIN document_chunks dc ON dc.section_id = ds.id
         WHERE {" AND ".join(where)}
         GROUP BY ds.id, ds.file_id, ds.title, ds.section_path,
                  fr.file_name, fr.folder, fr.file_hash
         ORDER BY fr.folder, fr.file_name, ds.ordinal
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), params).fetchall()]


def upsert_document_summary(
    file_id: int,
    summary: str,
    model: str,
    prompt_version: str,
    source_hash: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    with conn() as c:
        row = c.execute(text("""
            INSERT INTO document_summaries
                (file_id, summary, model, prompt_version, source_hash, metadata)
            VALUES (:file_id, :summary, :model, :prompt_version, :source_hash,
                    CAST(:metadata AS jsonb))
            ON CONFLICT (file_id, model, prompt_version, source_hash)
            DO UPDATE SET summary = EXCLUDED.summary, metadata = EXCLUDED.metadata
            RETURNING id
        """), {
            "file_id": file_id, "summary": summary, "model": model,
            "prompt_version": prompt_version, "source_hash": source_hash,
            "metadata": json.dumps(metadata or {}),
        }).fetchone()
        return row[0]


def upsert_section_summary(
    section_id: int,
    file_id: int,
    summary: str,
    model: str,
    prompt_version: str,
    source_hash: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    with conn() as c:
        row = c.execute(text("""
            INSERT INTO section_summaries
                (section_id, file_id, summary, model, prompt_version,
                 source_hash, metadata)
            VALUES (:section_id, :file_id, :summary, :model, :prompt_version,
                    :source_hash, CAST(:metadata AS jsonb))
            ON CONFLICT (section_id, model, prompt_version, source_hash)
            DO UPDATE SET summary = EXCLUDED.summary, metadata = EXCLUDED.metadata
            RETURNING id
        """), {
            "section_id": section_id, "file_id": file_id,
            "summary": summary, "model": model,
            "prompt_version": prompt_version, "source_hash": source_hash,
            "metadata": json.dumps(metadata or {}),
        }).fetchone()
        return row[0]


def sync_v3_chunk_aliases(folder: str | None = None) -> int:
    params: dict[str, Any] = {}
    folder_exists = ""
    if folder:
        folder_exists = """
        AND EXISTS (
            SELECT 1 FROM file_registry fr
             WHERE fr.id = dc.file_id AND fr.folder = :folder
        )
        """
        params["folder"] = folder
    with conn() as c:
        result = c.execute(text(f"""
            UPDATE document_chunks dc
               SET document_id = d.id,
                   raw_content = COALESCE(dc.raw_content, dc.content_raw, dc.content),
                   contextual_content = COALESCE(dc.contextual_content, dc.content_contextual, dc.content),
                   heading_path = COALESCE(dc.heading_path, ds.section_path, dc.metadata->>'section_path'),
                   subsection_title = COALESCE(dc.subsection_title, dc.metadata->>'subsection_title')
              FROM documents d
              LEFT JOIN document_sections ds ON ds.id = dc.section_id
             WHERE d.file_id = dc.file_id
               {folder_exists}
        """), params)
        return result.rowcount


def v3_relationship_rows(folder: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where = ""
    if folder:
        where = "WHERE fr.folder = :folder"
        params["folder"] = folder
    with conn() as c:
        rows = c.execute(text(f"""
            SELECT r.id AS relationship_id, r.source_entity_id, r.target_entity_id,
                   r.relationship_type, COALESCE(r.confidence, 0) AS confidence,
                   se.canonical_name AS source_name, se.entity_type AS source_type,
                   te.canonical_name AS target_name, te.entity_type AS target_type,
                   COUNT(re.id) AS evidence_count,
                   COUNT(DISTINCT re.file_id) AS file_count
              FROM relationships r
              JOIN entities se ON se.id = r.source_entity_id
              JOIN entities te ON te.id = r.target_entity_id
              LEFT JOIN relationship_evidence re ON re.relationship_id = r.id
              LEFT JOIN file_registry fr ON fr.id = re.file_id
             {where}
             GROUP BY r.id, r.source_entity_id, r.target_entity_id,
                      r.relationship_type, r.confidence,
                      se.canonical_name, se.entity_type,
                      te.canonical_name, te.entity_type
        """), params).fetchall()
        return [dict(r._mapping) for r in rows]


def replace_communities(
    communities: list[dict[str, Any]],
    algorithm: str,
    algorithm_version: str,
) -> dict[str, int]:
    with conn() as c:
        old_rows = c.execute(text("""
            SELECT id FROM communities
             WHERE algorithm = :algorithm AND algorithm_version = :algorithm_version
        """), {"algorithm": algorithm, "algorithm_version": algorithm_version}).fetchall()
        for row in old_rows:
            c.execute(text("DELETE FROM community_members WHERE community_id = :id"), {"id": row[0]})
        c.execute(text("""
            DELETE FROM communities
             WHERE algorithm = :algorithm AND algorithm_version = :algorithm_version
        """), {"algorithm": algorithm, "algorithm_version": algorithm_version})
        id_map: dict[str, int] = {}
        for community in communities:
            row = c.execute(text("""
                INSERT INTO communities
                    (name, summary, algorithm, algorithm_version,
                     source_hash, metadata, updated_at)
                VALUES (:name, :summary, :algorithm, :algorithm_version,
                        :source_hash, CAST(:metadata AS jsonb), NOW())
                RETURNING id
            """), {
                "name": community["name"],
                "summary": community.get("summary", ""),
                "algorithm": algorithm,
                "algorithm_version": algorithm_version,
                "source_hash": community["source_hash"],
                "metadata": json.dumps(community.get("metadata", {})),
            }).fetchone()
            community_id = row[0]
            id_map[community["name"]] = community_id
            for member in community.get("members", []):
                c.execute(text("""
                    INSERT INTO community_members
                        (community_id, entity_id, document_id, section_id,
                         member_type, membership_weight, provenance)
                    VALUES (:community_id, :entity_id, :document_id, :section_id,
                            :member_type, :membership_weight,
                            CAST(:provenance AS jsonb))
                """), {
                    "community_id": community_id,
                    "entity_id": member.get("entity_id"),
                    "document_id": member.get("document_id"),
                    "section_id": member.get("section_id"),
                    "member_type": member["member_type"],
                    "membership_weight": member.get("membership_weight", 1),
                    "provenance": json.dumps(member.get("provenance", {})),
                })
        return id_map


def recompute_graph_metadata() -> dict[str, int]:
    with conn() as c:
        c.execute(text("DELETE FROM graph_metadata"))
        entity_rows = c.execute(text("""
            SELECT e.id, e.entity_type,
                   COUNT(DISTINCT em.id) AS mention_count,
                   COUNT(DISTINCT r.id) AS degree
              FROM entities e
              LEFT JOIN entity_mentions em ON em.entity_id = e.id
              LEFT JOIN relationships r
                ON r.source_entity_id = e.id OR r.target_entity_id = e.id
             GROUP BY e.id, e.entity_type
        """)).fetchall()
        relationship_rows = c.execute(text("""
            SELECT r.id, COALESCE(r.confidence, 0) AS confidence,
                   COUNT(re.id) AS evidence_count
              FROM relationships r
              LEFT JOIN relationship_evidence re ON re.relationship_id = r.id
             GROUP BY r.id, r.confidence
        """)).fetchall()
        community_rows = c.execute(text("""
            SELECT c.id, COUNT(cm.id) AS member_count
              FROM communities c
              LEFT JOIN community_members cm ON cm.community_id = c.id
             GROUP BY c.id
        """)).fetchall()
        for row in entity_rows:
            mention_count = int(row[2] or 0)
            degree = int(row[3] or 0)
            node_weight = max(1, mention_count + degree)
            c.execute(text("""
                INSERT INTO graph_metadata
                    (object_type, object_id, node_type, node_weight,
                     node_degree, metrics)
                VALUES ('entity', :id, :node_type, :node_weight,
                        :node_degree, CAST(:metrics AS jsonb))
            """), {
                "id": row[0], "node_type": row[1],
                "node_weight": node_weight, "node_degree": degree,
                "metrics": json.dumps({"mention_count": mention_count, "degree": degree}),
            })
            c.execute(text("""
                UPDATE entities
                   SET mention_count = :mention_count, node_weight = :node_weight
                 WHERE id = :id
            """), {"id": row[0], "mention_count": mention_count, "node_weight": node_weight})
        for row in relationship_rows:
            evidence_count = int(row[2] or 0)
            confidence = float(row[1] or 0)
            edge_weight = max(1, evidence_count) * max(confidence, 0.1)
            c.execute(text("""
                INSERT INTO graph_metadata
                    (object_type, object_id, edge_weight,
                     edge_confidence, metrics)
                VALUES ('relationship', :id, :edge_weight,
                        :edge_confidence, CAST(:metrics AS jsonb))
            """), {
                "id": row[0], "edge_weight": edge_weight,
                "edge_confidence": confidence,
                "metrics": json.dumps({"evidence_count": evidence_count}),
            })
            c.execute(text("""
                UPDATE relationships
                   SET edge_weight = :edge_weight, evidence_count = :evidence_count
                 WHERE id = :id
            """), {"id": row[0], "edge_weight": edge_weight, "evidence_count": evidence_count})
        for row in community_rows:
            member_count = int(row[1] or 0)
            c.execute(text("""
                INSERT INTO graph_metadata
                    (object_type, object_id, node_type, node_weight,
                     node_degree, metrics)
                VALUES ('community', :id, 'community', :node_weight,
                        :node_degree, CAST(:metrics AS jsonb))
            """), {
                "id": row[0],
                "node_weight": max(1, member_count),
                "node_degree": member_count,
                "metrics": json.dumps({"member_count": member_count}),
            })
    return {
        "entities": len(entity_rows),
        "relationships": len(relationship_rows),
        "communities": len(community_rows),
    }


def v3_status() -> dict[str, int]:
    tables = [
        "documents", "document_sections", "document_summaries",
        "section_summaries", "document_chunks", "entities",
        "entity_mentions", "relationships", "relationship_evidence",
        "communities", "community_members", "graph_metadata",
    ]
    out: dict[str, int] = {}
    with conn() as c:
        for table in tables:
            out[table] = c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
    return out


def replace_segments(file_id: int, segments: list[dict[str, Any]]) -> list[int]:
    with conn() as c:
        c.execute(text("DELETE FROM speaker_segments WHERE file_id = :fid"), {"fid": file_id})
        ids: list[int] = []
        for s in segments:
            row = c.execute(text("""
                INSERT INTO speaker_segments
                    (file_id, speaker_label, start_time, end_time, text, confidence)
                VALUES (:fid, :spk, :start, :end, :txt, :conf)
                RETURNING id
            """), {
                "fid": file_id,
                "spk": s["speaker"],
                "start": s["start"],
                "end": s["end"],
                "txt": s.get("text"),
                "conf": s.get("confidence"),
            }).fetchone()
            ids.append(row[0])
        return ids
