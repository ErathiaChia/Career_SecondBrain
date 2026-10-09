"""Reads over the indexer's career layer (role_assignments, achievements,
skill_evidence) for the agent's career tools. Empty when migration 0018 has not
been applied / the layer has not been built."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from era_mcp import projects, retrieval


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in result.fetchall()]


def role_history(me_only: bool = True) -> list[dict[str, Any]]:
    if not projects._present("role_assignments"):
        return []
    with retrieval._get_engine().connect() as conn:
        return _rows(conn.execute(text(f"""
            SELECT ra.id, ra.project_id, p.name AS project, p.project_key, p.client, p.status AS project_status,
                   p.first_activity, p.last_activity, e.canonical_name AS person, ra.is_me, ra.role, ra.role_label,
                   ra.period_start, ra.period_end, ra.confidence, ra.status, ra.method, ra.sources
              FROM role_assignments ra
              JOIN projects p ON p.id = ra.project_id
              JOIN entities e ON e.id = ra.person_entity_id
             WHERE ra.status <> 'rejected' {"AND ra.is_me" if me_only else ""}
             ORDER BY COALESCE(ra.period_start, CAST(p.first_activity AS date)) NULLS LAST, p.name, ra.confidence DESC
        """)))


def achievements(project_id: int | None = None, query: str | None = None, with_metric: bool = False,
                 me_only: bool = True, limit: int = 20) -> list[dict[str, Any]]:
    if not projects._present("achievements"):
        return []
    params: dict[str, Any] = {"k": limit}
    where = ["a.status IN ('proposed', 'confirmed')"]
    if me_only:
        where.append("a.is_me")
    if project_id is not None:
        where.append("a.project_id = :p"); params["p"] = project_id
    if with_metric:
        where.append("a.metric IS NOT NULL")
    if query:
        where.append("(a.statement ILIKE :q OR p.name ILIKE :q OR p.client ILIKE :q)"); params["q"] = f"%{query}%"
    with retrieval._get_engine().connect() as conn:
        rows = _rows(conn.execute(text(f"""
            SELECT a.id, a.project_id, p.name AS project, p.client, a.statement, a.metric, a.outcome_kind, a.is_me,
                   a.evidence_fact_ids, a.evidence_file_ids, a.confidence, a.period_start, a.period_end, a.status
              FROM achievements a LEFT JOIN projects p ON p.id = a.project_id
             WHERE {" AND ".join(where)}
             ORDER BY a.confidence DESC, a.period_end DESC NULLS LAST LIMIT :k"""), params))
    # attach one evidence file name per achievement for citations
    file_ids = sorted({fid for r in rows for fid in (r.get("evidence_file_ids") or [])[:1]})
    names: dict[int, dict[str, Any]] = {}
    if file_ids:
        with retrieval._get_engine().connect() as conn:
            for r in _rows(conn.execute(text("SELECT id, file_name, file_path, folder FROM file_registry WHERE id = ANY(CAST(:ids AS int[]))"),
                                        {"ids": file_ids})):
                names[r["id"]] = r
    for r in rows:
        fid = (r.get("evidence_file_ids") or [None])[0]
        r["file"] = names.get(fid) if fid else None
    return rows


def skill_evidence(capability: str | None = None, limit: int = 15) -> list[dict[str, Any]]:
    if not projects._present("skill_evidence"):
        return []
    params: dict[str, Any] = {"k": limit}
    where = ["1=1"]
    if capability:
        where.append("(e.canonical_name ILIKE :q OR se.skill_kind ILIKE :q OR p.name ILIKE :q OR se.role ILIKE :q)")
        params["q"] = f"%{capability}%"
    with retrieval._get_engine().connect() as conn:
        return _rows(conn.execute(text(f"""
            SELECT se.id, e.canonical_name AS skill, se.skill_kind, se.project_id, p.name AS project, p.client,
                   se.role, se.mention_count, se.evidence_fact_ids, se.evidence_file_ids, se.strength,
                   se.first_seen, se.last_seen
              FROM skill_evidence se JOIN entities e ON e.id = se.entity_id JOIN projects p ON p.id = se.project_id
             WHERE {" AND ".join(where)}
             ORDER BY se.strength DESC LIMIT :k"""), params))


def contribution_facts(capability: str, limit: int = 15) -> list[dict[str, Any]]:
    """Facts of kind contribution/outcome/lesson owned by me whose statement or
    project mentions the capability."""
    if not projects._present("knowledge_facts"):
        return []
    with retrieval._get_engine().connect() as conn:
        return _rows(conn.execute(text("""
            SELECT kf.id, kf.kind, kf.statement, kf.status, kf.occurred_at, kf.attributes, kf.source_quote,
                   kf.confidence, kf.file_id, fr.file_name, fr.file_path, fr.folder, o.canonical_name AS owner,
                   (SELECT p.name FROM project_files pf JOIN projects p ON p.id = pf.project_id
                     WHERE pf.file_id = kf.file_id LIMIT 1) AS project
              FROM knowledge_facts kf
              JOIN file_registry fr ON fr.id = kf.file_id
              JOIN entities o ON o.id = kf.owner_entity_id
             WHERE kf.kind IN ('contribution', 'outcome', 'lesson')
               AND COALESCE(o.metadata ->> 'is_me', '') = 'true'
               AND (kf.statement ILIKE :q OR COALESCE(kf.attributes ->> 'activity', '') ILIKE :q
                    OR COALESCE(kf.attributes ->> 'role_hint', '') ILIKE :q)
             ORDER BY kf.confidence DESC NULLS LAST, kf.occurred_at DESC NULLS LAST LIMIT :k"""),
            {"q": f"%{capability}%", "k": limit}))


def my_projects() -> list[dict[str, Any]]:
    """Projects where I hold a (non-rejected) role, with activity window."""
    if not projects._present("role_assignments"):
        return []
    with retrieval._get_engine().connect() as conn:
        return _rows(conn.execute(text("""
            SELECT DISTINCT p.id, p.name, p.project_key, p.client, p.status, p.first_activity, p.last_activity,
                   ra.role, ra.confidence, ra.status AS role_status
              FROM role_assignments ra JOIN projects p ON p.id = ra.project_id
             WHERE ra.is_me AND ra.status <> 'rejected'
             ORDER BY p.first_activity NULLS LAST""")))
