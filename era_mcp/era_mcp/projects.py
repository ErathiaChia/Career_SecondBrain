"""Project-intelligence reads: projects, documents/versions, state, typed facts,
timeline, changes, conflicts, staleness, similarity and reuse.

Read-only over tables the indexer builds (migrations 0006+). Every function
degrades to an empty result when its table is absent, so older deployments keep
working. Never reads ``auditor_*`` tables; reuse data comes from the neutral
``vault_reusable_assets`` export.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from era_mcp import retrieval

_PRESENT: dict[str, bool] = {}


def _present(table: str) -> bool:
    if table not in _PRESENT:
        try:
            with retrieval._get_engine().connect() as conn:
                _PRESENT[table] = conn.execute(
                    text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
                ).scalar() is not None
        except Exception:
            return False
    return _PRESENT[table]


def _clean(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with retrieval._get_engine().connect() as conn:
        rows = conn.execute(text(sql), params or {}).fetchall()
    return [_clean(dict(r._mapping)) for r in rows]


# --- Projects -----------------------------------------------------------------

_PROJECT_COLS = """p.id, p.project_key, p.name, p.client, p.project_type, p.status,
    p.lifecycle, p.owner, p.source_folder, p.first_activity, p.last_activity,
    p.file_count, p.confidence, p.field_sources, p.aliases"""


def list_projects(status: str | None = None, client: str | None = None,
                  include_removed: bool = False) -> list[dict[str, Any]]:
    if not _present("projects"):
        return []
    where = ["TRUE"]
    params: dict[str, Any] = {}
    if not include_removed:
        where.append("p.status IS DISTINCT FROM 'REMOVED'")
    if status:
        where.append("upper(p.status) = upper(:status)")
        params["status"] = status
    if client:
        where.append("p.client ILIKE :client")
        params["client"] = f"%{client}%"
    return _query(f"SELECT {_PROJECT_COLS} FROM projects p WHERE {' AND '.join(where)} "
                  "ORDER BY p.last_activity DESC NULLS LAST", params)


def resolve_project(ref: str | int) -> dict[str, Any] | None:
    """Find a project by id, key, name, alias, or a name fragment."""
    if not _present("projects") or ref is None or str(ref).strip() == "":
        return None
    r = str(ref).strip()
    if r.isdigit():
        rows = _query(f"SELECT {_PROJECT_COLS} FROM projects p WHERE p.id = :id", {"id": int(r)})
        if rows:
            return rows[0]
    rows = _query(f"""
        SELECT {_PROJECT_COLS},
               CASE WHEN p.project_key = :r OR lower(p.name) = lower(:r) THEN 0
                    WHEN EXISTS (SELECT 1 FROM jsonb_array_elements_text(p.aliases) a(v)
                                  WHERE lower(a.v) = lower(:r)) THEN 1
                    ELSE 2 END AS match_rank
          FROM projects p
         WHERE p.project_key = :r
            OR p.name ILIKE :like
            OR p.client ILIKE :like
            OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(p.aliases) a(v) WHERE a.v ILIKE :like)
         ORDER BY match_rank, (p.status = 'ACTIVE') DESC, p.file_count DESC
         LIMIT 1
    """, {"r": r, "like": f"%{r}%"})
    if not rows:
        return _resolve_by_tokens(r) or _resolve_by_documents(r)
    rows[0].pop("match_rank", None)
    return rows[0]


_PATH_TSV = ("to_tsvector('simple', translate(coalesce(fr.file_name,'') || ' ' || "
             "coalesce(fr.file_path,''), '_/.-', '    '))")


def _resolve_by_documents(ref: str) -> dict[str, Any] | None:
    """Last resort: the project whose files are named after ``ref``. People call a
    project by its deliverable ("C3 Chatbot", "Eye Center") rather than its registry
    name; the files usually carry that name. Every token must appear in the file
    name or path; the project with the most such files wins."""
    if not _present("project_files"):
        return None
    wanted = sorted(_tokens(ref))
    if not wanted:
        return None
    rows = _query(f"""
        SELECT pf.project_id, count(*) AS n
          FROM project_files pf
          JOIN file_registry fr ON fr.id = pf.file_id
          JOIN projects p ON p.id = pf.project_id
         WHERE p.status IS DISTINCT FROM 'REMOVED'
           AND {retrieval.live_files_filter('fr')}
           AND {_PATH_TSV} @@ to_tsquery('simple', :q)
         GROUP BY pf.project_id
         ORDER BY n DESC
         LIMIT 2
    """, {"q": " & ".join(wanted)})
    if not rows or (len(rows) > 1 and rows[1]["n"] * 2 > rows[0]["n"]):
        return None
    found = _query(f"SELECT {_PROJECT_COLS} FROM projects p WHERE p.id = :id", {"id": rows[0]["project_id"]})
    return found[0] if found else None


def project_suggestions(ref: str, limit: int = 5) -> list[dict[str, Any]]:
    """Projects sharing any token with ``ref`` (for a helpful 404)."""
    wanted = _tokens(ref)
    scored = []
    for p in list_projects():
        hay = _tokens(" ".join([p.get("name") or "", p.get("project_key") or "", p.get("client") or ""]))
        hit = len(wanted & hay)
        if hit:
            scored.append((hit, p))
    scored.sort(key=lambda t: -t[0])
    return [{"project_key": p["project_key"], "name": p["name"], "client": p.get("client")}
            for _, p in scored[:limit]]


def fact_coverage(project_id: int) -> dict[str, int]:
    """How much of a project has been through fact extraction. Zero facts means
    the structured tools cannot answer, not that nothing is open."""
    if not (_present("project_files") and _present("knowledge_facts")):
        return {"files": 0, "files_with_facts": 0, "facts": 0}
    row = _query("""
        SELECT count(DISTINCT pf.file_id) AS files,
               count(DISTINCT kf.file_id) AS files_with_facts,
               count(DISTINCT kf.id) AS facts
          FROM project_files pf
          LEFT JOIN knowledge_facts kf ON kf.file_id = pf.file_id
         WHERE pf.project_id = :p
    """, {"p": project_id})
    return row[0] if row else {"files": 0, "files_with_facts": 0, "facts": 0}


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _resolve_by_tokens(ref: str) -> dict[str, Any] | None:
    """Punctuation-insensitive fallback: 'CPX AI Use Case' -> 'CL89 CPX AI Use Case',
    'CL87 eye center' -> 'CL87 Eye Clinic' (CL87). A project qualifies when at least
    two-thirds of the tokens of ``ref`` (and at least two, unless ``ref`` is a single
    token) appear in its name/key/client/aliases; best coverage wins."""
    wanted = _tokens(ref)
    if not wanted:
        return None
    need = len(wanted) if len(wanted) == 1 else max(2, -(-2 * len(wanted) // 3))
    best, best_score = None, 0.0
    for p in list_projects():
        aliases = p.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        hay = " ".join([p.get("name") or "", p.get("project_key") or "", p.get("client") or "",
                        *aliases])
        hit = wanted & _tokens(hay)
        if len(hit) < need:
            continue
        score = len(hit) + len(hit) / len(_tokens(p.get("name") or "") | wanted)
        if p.get("status") == "ACTIVE":
            score += 0.01
        if score > best_score:
            best, best_score = p, score
    return best


def project_documents(project_id: int, group: str = "version") -> dict[str, Any]:
    """A project's documents, grouped into version families when ``group='version'``."""
    if not _present("project_files"):
        return {"families": [], "documents": []}
    has_versions = _present("document_versions")
    version_cols = ("dv.family_key, dv.version_label, dv.version_rank, dv.is_latest, dv.family_size"
                    if has_versions else
                    "NULL AS family_key, NULL AS version_label, 1 AS version_rank, TRUE AS is_latest, 1 AS family_size")
    version_join = "LEFT JOIN document_versions dv ON dv.file_id = fr.id" if has_versions else ""
    docs = _query(f"""
        SELECT fr.id AS file_id, fr.file_name, fr.file_path, fr.file_type, fr.last_modified_at,
               {version_cols}
          FROM project_files pf
          JOIN file_registry fr ON fr.id = pf.file_id
          {version_join}
         WHERE pf.project_id = :p AND {retrieval.live_files_filter('fr')}
         ORDER BY fr.last_modified_at DESC NULLS LAST
    """, {"p": project_id})
    if group != "version":
        return {"documents": docs}
    families: dict[tuple, dict[str, Any]] = {}
    for d in docs:
        key = (d.get("family_key") or d["file_name"], d.get("file_type"))
        fam = families.setdefault(key, {"family_key": key[0], "file_type": key[1], "versions": []})
        fam["versions"].append(d)
    out = []
    for fam in families.values():
        fam["versions"].sort(key=lambda d: d.get("version_rank") or 1)
        fam["latest"] = fam["versions"][-1]["file_name"]
        fam["version_count"] = len(fam["versions"])
        out.append(fam)
    out.sort(key=lambda f: (-f["version_count"], f["family_key"]))
    return {"families": out, "document_count": len(docs)}


def project_entities(project_id: int, entity_type: str | None = None,
                     limit: int = 50) -> list[dict[str, Any]]:
    """People, organisations, technologies... mentioned in a project's files."""
    if not _present("projects"):
        return []
    params: dict[str, Any] = {"p": project_id, "limit": limit}
    type_filter = ""
    if entity_type:
        type_filter = "AND e.entity_type = :t"
        params["t"] = entity_type
    return _query(f"""
        SELECT e.id, e.canonical_name, e.entity_type, e.aliases,
               pe.mention_count, pe.file_count
          FROM project_entities pe
          JOIN entities e ON e.id = pe.entity_id
         WHERE pe.project_id = :p {type_filter}
         ORDER BY pe.file_count DESC, pe.mention_count DESC
         LIMIT :limit
    """, params)


# --- State, typed facts, timeline ---------------------------------------------

OPEN_EXCLUDED = ("done", "cancelled", "rejected", "mitigated")


def project_state(project_id: int) -> dict[str, Any] | None:
    if not _present("project_state"):
        return None
    rows = _query("""
        SELECT state, health, model, built_at FROM project_state
         WHERE project_id = :p AND is_current
    """, {"p": project_id})
    return rows[0] if rows else None


def project_facts(project_id: int, kinds: list[str] | None = None, open_only: bool = False,
                  limit: int = 50) -> list[dict[str, Any]]:
    """Typed facts for a project, newest evidence first, each with its source file,
    whether that file is the latest version, stale reasons and conflict ids."""
    if not _present("projects"):
        return []
    where = ["pf.project_id = :p"]
    params: dict[str, Any] = {"p": project_id, "limit": limit}
    if kinds:
        where.append("pf.kind = ANY(CAST(:kinds AS text[]))")
        params["kinds"] = kinds
    if open_only:
        where.append("COALESCE(to_jsonb(pf) ->> 'status', '') <> ALL(CAST(:closed AS text[]))")
        params["closed"] = list(OPEN_EXCLUDED)
    has_versions = _present("document_versions")
    has_stale = _present("stale_flags")
    has_conflicts = _present("fact_conflicts")
    latest = "COALESCE(dv.is_latest, TRUE)" if has_versions else "TRUE"
    version_join = "LEFT JOIN document_versions dv ON dv.file_id = pf.file_id" if has_versions else ""
    stale = ("""(SELECT COALESCE(jsonb_agg(sf.reason), '[]'::jsonb) FROM stale_flags sf
                  WHERE sf.object_type = 'fact' AND sf.object_id = pf.id)""" if has_stale else "'[]'::jsonb")
    conflicts = ("""(SELECT COALESCE(jsonb_agg(c.id), '[]'::jsonb) FROM fact_conflicts c
                      WHERE (c.fact_a_id = pf.id OR c.fact_b_id = pf.id)
                        AND c.status IN ('needs_confirmation', 'confirmed'))""" if has_conflicts else "'[]'::jsonb")
    return _query(f"""
        SELECT pf.id AS fact_id, pf.kind, pf.statement,
               to_jsonb(pf) ->> 'topic' AS topic,
               to_jsonb(pf) ->> 'status' AS status,
               to_jsonb(pf) ->> 'priority' AS priority,
               COALESCE(owner.canonical_name, pf.attributes ->> 'owner') AS owner,
               pf.attributes, pf.occurred_at,
               COALESCE(to_jsonb(pf) ->> 'last_verified_at', CAST(fr.last_modified_at AS text)) AS last_verified,
               pf.confidence, pf.source_quote,
               to_jsonb(pf) ->> 'supersedes_fact_id' AS supersedes_fact_id,
               fr.id AS file_id, fr.file_name,
               {latest} AS from_latest_version,
               {stale} AS stale_reasons,
               {conflicts} AS conflict_ids
          FROM project_facts pf
          JOIN file_registry fr ON fr.id = pf.file_id
          LEFT JOIN entities owner ON owner.id = CAST(to_jsonb(pf) ->> 'owner_entity_id' AS integer)
          {version_join}
         WHERE {' AND '.join(where)}
         ORDER BY COALESCE(CAST(to_jsonb(pf) ->> 'last_verified_at' AS timestamp), pf.occurred_at,
                           fr.last_modified_at) DESC NULLS LAST, pf.id DESC
         LIMIT :limit
    """, params)


def project_timeline(project_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Dated events for a project: events, milestones, decisions and due dates
    from facts, file additions, and detected changes. Oldest first."""
    if not _present("projects"):
        return []
    parts = ["""
        SELECT COALESCE(pf.occurred_at,
                        CAST(substring(pf.attributes ->> 'due_at' from '\\d{4}-\\d{2}-\\d{2}') AS timestamp)) AS at,
               pf.kind AS type, pf.statement AS summary, pf.id AS fact_id, fr.file_name,
               CASE WHEN pf.occurred_at IS NULL THEN 'due' ELSE 'occurred' END AS date_kind
          FROM project_facts pf
          JOIN file_registry fr ON fr.id = pf.file_id
         WHERE pf.project_id = :p
           AND pf.kind IN ('event', 'milestone', 'decision', 'commitment', 'action_item')
    """, """
        SELECT fr.last_modified_at AS at, 'document' AS type,
               'Document updated: ' || fr.file_name AS summary, NULL AS fact_id, fr.file_name,
               'modified' AS date_kind
          FROM project_files pf JOIN file_registry fr ON fr.id = pf.file_id
         WHERE pf.project_id = :p AND fr.last_modified_at IS NOT NULL
    """]
    if _present("project_changes"):
        parts.append("""
        SELECT pc.detected_at AS at, pc.change_type AS type, pc.summary, NULL AS fact_id,
               fr.file_name, 'detected' AS date_kind
          FROM project_changes pc LEFT JOIN file_registry fr ON fr.id = pc.file_id
         WHERE pc.project_id = :p AND pc.change_type NOT IN ('file_modified', 'file_added')
        """)
    return _query(f"""
        SELECT * FROM ({' UNION ALL '.join(parts)}) t
         WHERE at IS NOT NULL
         ORDER BY at DESC
         LIMIT :limit
    """, {"p": project_id, "limit": limit})[::-1]


_SEVERITY = ["info", "notice", "warning", "critical"]


def project_changes(project_id: int | None = None, since_days: int = 14,
                    min_severity: str = "info", limit: int = 100) -> list[dict[str, Any]]:
    """Detected changes (newest first) with their batch impact card."""
    if not _present("project_changes"):
        return []
    levels = _SEVERITY[_SEVERITY.index(min_severity):] if min_severity in _SEVERITY else _SEVERITY
    where = ["pc.detected_at > NOW() - make_interval(days => :days)",
             "pc.severity = ANY(CAST(:levels AS text[]))"]
    params: dict[str, Any] = {"days": since_days, "levels": levels, "limit": limit}
    if project_id is not None:
        where.append("pc.project_id = :p")
        params["p"] = project_id
    return _query(f"""
        SELECT pc.id, pc.project_id, p.name AS project, pc.change_type, pc.summary,
               pc.severity, pc.impact, pc.batch_id, pc.detected_at,
               pc.file_id, fr.file_name
          FROM project_changes pc
          LEFT JOIN projects p ON p.id = pc.project_id
          LEFT JOIN file_registry fr ON fr.id = pc.file_id
         WHERE {' AND '.join(where)}
         ORDER BY pc.detected_at DESC, pc.id DESC
         LIMIT :limit
    """, params)


def project_conflicts(project_id: int, include_resolved: bool = False,
                      limit: int = 50) -> list[dict[str, Any]]:
    """Contradicting fact pairs with both statements, their sources, and which is
    likely the latest. Status needs_confirmation means a person should decide."""
    if not _present("fact_conflicts"):
        return []
    statuses = ["needs_confirmation", "confirmed"] + (["dismissed"] if include_resolved else [])
    return _query("""
        SELECT c.id, c.conflict_type, c.explanation, c.confidence, c.status, c.method,
               c.likely_latest_fact_id, c.detected_at,
               a.id AS fact_a_id, a.kind AS fact_a_kind, a.statement AS fact_a, fa.file_name AS fact_a_file,
               b.id AS fact_b_id, b.kind AS fact_b_kind, b.statement AS fact_b, fb.file_name AS fact_b_file
          FROM fact_conflicts c
          JOIN knowledge_facts a ON a.id = c.fact_a_id
          JOIN knowledge_facts b ON b.id = c.fact_b_id
          JOIN file_registry fa ON fa.id = a.file_id
          JOIN file_registry fb ON fb.id = b.file_id
         WHERE c.project_id = :p AND c.status = ANY(CAST(:statuses AS text[]))
         ORDER BY (c.status = 'needs_confirmation') DESC, c.confidence DESC NULLS LAST, c.detected_at DESC
         LIMIT :limit
    """, {"p": project_id, "statuses": statuses, "limit": limit})


def project_stale(project_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Facts flagged stale (superseded, contradicted by newer, from an older
    document version, or open but not re-asserted for a long time)."""
    if not _present("stale_flags"):
        return []
    return _query("""
        SELECT pf.id AS fact_id, pf.kind, pf.statement, fr.file_name,
               jsonb_agg(jsonb_build_object('reason', sf.reason, 'detail', sf.detail,
                                            'newer_evidence_id', sf.newer_evidence_id)) AS flags
          FROM stale_flags sf
          JOIN project_facts pf ON pf.id = sf.object_id AND sf.object_type = 'fact'
          JOIN file_registry fr ON fr.id = pf.file_id
         WHERE pf.project_id = :p
         GROUP BY pf.id, pf.kind, pf.statement, fr.file_name
         ORDER BY pf.id DESC
         LIMIT :limit
    """, {"p": project_id, "limit": limit})


# --- Cross-project ------------------------------------------------------------

def similar_projects(project_id: int, limit: int = 5) -> list[dict[str, Any]]:
    if not _present("project_similarity"):
        return []
    return _query("""
        SELECT o.id, o.name, o.client, o.project_type, o.status, o.last_activity,
               s.score, s.cosine, s.entity_overlap, s.shared_entities
          FROM project_similarity s
          JOIN projects o ON o.id = s.other_project_id
         WHERE s.project_id = :p
         ORDER BY s.score DESC
         LIMIT :limit
    """, {"p": project_id, "limit": limit})


def projects_similar_to_vector(vec: list[float], limit: int = 5) -> list[dict[str, Any]]:
    """Projects whose content vector is closest to a query embedding."""
    if not _present("project_embeddings"):
        return []
    return _query("""
        SELECT p.id, p.name, p.client, p.project_type, p.status, p.last_activity,
               1 - (pe.embedding <=> CAST(:qvec AS vector)) AS cosine
          FROM project_embeddings pe
          JOIN projects p ON p.id = pe.project_id
         WHERE p.status IS DISTINCT FROM 'REMOVED'
         ORDER BY pe.embedding <=> CAST(:qvec AS vector)
         LIMIT :limit
    """, {"qvec": retrieval._vec_literal(vec), "limit": limit})


def reuse_candidates(project: dict[str, Any] | None = None, query: str | None = None,
                     include_similar: bool = True, limit: int = 20) -> list[dict[str, Any]]:
    """Reusable assets (templates, decks, specs reused across projects) from the
    auditor export: assets used by this project, then assets from similar
    projects it does not have yet; or assets matching ``query``."""
    if not _present("vault_reusable_assets"):
        return []
    if query:
        return _query("""
            SELECT asset_key, asset_name, file_type, reuse_score, copy_count,
                   projects, customers, canonical_location, 'query' AS why
              FROM vault_reusable_assets
             WHERE asset_name ILIKE :like OR canonical_location ILIKE :like
             ORDER BY reuse_score DESC, copy_count DESC
             LIMIT :limit
        """, {"like": f"%{query}%", "limit": limit})
    if project is None:
        return _query("""
            SELECT asset_key, asset_name, file_type, reuse_score, copy_count,
                   projects, customers, canonical_location, 'top' AS why
              FROM vault_reusable_assets
             ORDER BY reuse_score DESC, copy_count DESC LIMIT :limit
        """, {"limit": limit})

    def match(alias: str) -> str:
        return f"""(
            EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.paths) x(v)
                     WHERE x.v ILIKE '%/' || trim(both '/' from {alias}.source_folder) || '/%')
            OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.projects) x(v)
                        WHERE lower(x.v) IN (lower({alias}.name), lower({alias}.project_key))))"""

    own = _query(f"""
        SELECT a.asset_key, a.asset_name, a.file_type, a.reuse_score, a.copy_count,
               a.projects, a.customers, a.canonical_location, 'used_in_project' AS why
          FROM vault_reusable_assets a, projects p
         WHERE p.id = :p AND {match('p')}
         ORDER BY a.reuse_score DESC LIMIT :limit
    """, {"p": project["id"], "limit": limit})
    if not include_similar or not _present("project_similarity"):
        return own
    have = {a["asset_key"] for a in own}
    from_similar = _query(f"""
        SELECT DISTINCT ON (a.asset_key)
               a.asset_key, a.asset_name, a.file_type, a.reuse_score, a.copy_count,
               a.projects, a.customers, a.canonical_location,
               'used_in_similar_project: ' || o.name AS why, s.score AS similarity
          FROM project_similarity s
          JOIN projects o ON o.id = s.other_project_id
          JOIN vault_reusable_assets a ON {match('o')}
         WHERE s.project_id = :p
         ORDER BY a.asset_key, s.score DESC
    """, {"p": project["id"]})
    from_similar = [a for a in from_similar if a["asset_key"] not in have]
    from_similar.sort(key=lambda a: (-(a.get("similarity") or 0), -(a.get("reuse_score") or 0)))
    return own + from_similar[: max(0, limit - len(own))]


# --- Proposed actions (the only era_mcp write) ----------------------------------

ACTION_TYPES = {"follow_up", "create_task", "update_status", "resolve_conflict",
                "schedule_meeting", "draft_message", "reverify_fact", "other"}


def propose_action(project_id: int | None, action_type: str, title: str, detail: str | None,
                   payload: dict[str, Any] | None, source_fact_ids: list[int] | None) -> dict[str, Any]:
    """Queue an action for human approval. Nothing is executed here."""
    import json

    if not _present("proposed_actions"):
        raise RuntimeError("proposed_actions table is missing; run the indexer migrations")
    with retrieval._get_engine().begin() as conn:
        row = conn.execute(text("""
            INSERT INTO proposed_actions (project_id, action_type, title, detail, payload, source_fact_ids)
            VALUES (:p, :t, :title, :detail, CAST(:payload AS jsonb), CAST(:facts AS jsonb))
            RETURNING id, status, created_at
        """), {"p": project_id, "t": action_type if action_type in ACTION_TYPES else "other",
               "title": title[:300], "detail": detail, "payload": json.dumps(payload or {}),
               "facts": json.dumps([int(i) for i in (source_fact_ids or [])])}).fetchone()
    return _clean(dict(row._mapping))


def list_proposed_actions(status: str = "pending", project_id: int | None = None,
                          limit: int = 50) -> list[dict[str, Any]]:
    if not _present("proposed_actions"):
        return []
    where = ["a.status = :s"]
    params: dict[str, Any] = {"s": status, "limit": limit}
    if project_id is not None:
        where.append("a.project_id = :p")
        params["p"] = project_id
    return _query(f"""
        SELECT a.*, p.name AS project FROM proposed_actions a
          LEFT JOIN projects p ON p.id = a.project_id
         WHERE {' AND '.join(where)}
         ORDER BY a.created_at DESC LIMIT :limit
    """, params)


def latest_digest() -> dict[str, Any] | None:
    if not _present("digests"):
        return None
    rows = _query("SELECT id, items, markdown, stats, created_at FROM digests ORDER BY created_at DESC LIMIT 1")
    return rows[0] if rows else None


def document_versions(file_id: int) -> dict[str, Any]:
    """The version chain a file belongs to, oldest first."""
    if not _present("document_versions"):
        return {"file_id": file_id, "chain": []}
    chain = _query("""
        SELECT fr.id AS file_id, fr.file_name, fr.file_path, fr.last_modified_at,
               dv.version_label, dv.version_rank, dv.is_latest, dv.previous_file_id
          FROM document_versions me
          JOIN document_versions dv ON dv.scope_key = me.scope_key AND dv.family_key = me.family_key
          JOIN file_registry fr ON fr.id = dv.file_id
         WHERE me.file_id = :f
           AND lower(fr.file_type) = lower((SELECT file_type FROM file_registry WHERE id = :f))
         ORDER BY dv.version_rank
    """, {"f": file_id})
    return {"file_id": file_id, "chain": chain}
