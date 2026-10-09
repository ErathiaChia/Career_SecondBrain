"""SQL for the career layer (role_assignments, achievements, skill_evidence,
career_state, proposed role confirmations). Pure functions in career.py; this
module only reads/writes rows."""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Iterable

from sqlalchemy import text

from career_history.db import conn
from career_history.intel_db import _rows, table_exists


def facts_for_project_with_owner(project_id: int, limit: int = 800) -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT pf.id, pf.kind, pf.statement, pf.topic, pf.status, pf.priority, pf.attributes,
                   pf.occurred_at, pf.last_verified_at, pf.confidence, pf.file_id,
                   pf.owner_entity_id, pf.subject_entity_id, pf.object_entity_id,
                   fr.file_name, fr.last_modified_at,
                   COALESCE(dv.is_latest, TRUE) AS from_latest_version
              FROM project_facts pf
              JOIN file_registry fr ON fr.id = pf.file_id
              LEFT JOIN document_versions dv ON dv.file_id = pf.file_id
             WHERE pf.project_id = :p
             ORDER BY pf.id
             LIMIT :limit
        """), {"p": project_id, "limit": limit}))


def project_file_cards(project_id: int) -> list[dict[str, Any]]:
    """Per-file doc_type / people from document_cards for a project (empty if
    cards are not built yet)."""
    if not table_exists("document_cards"):
        return []
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT dc.file_id, dc.doc_type, dc.people, dc.technologies, dc.doc_date
              FROM document_cards dc
              JOIN project_files pfl ON pfl.file_id = dc.file_id
             WHERE pfl.project_id = :p
        """), {"p": project_id}))


def project_person_mentions(project_id: int) -> list[dict[str, Any]]:
    """Person entities mentioned in a project's files with mention counts."""
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT e.id AS entity_id, e.canonical_name AS name,
                   COALESCE(e.metadata ->> 'is_me', '') = 'true' AS is_me,
                   COUNT(em.id) AS mention_count
              FROM entity_mentions em
              JOIN entities e ON e.id = em.entity_id
              JOIN project_files pfl ON pfl.file_id = em.file_id
             WHERE pfl.project_id = :p AND e.entity_type = 'person'
             GROUP BY e.id
             ORDER BY mention_count DESC
        """), {"p": project_id}))


def me_relationships_in_project(project_id: int, me_id: int) -> list[dict[str, Any]]:
    """Relationships where I am the source (MANAGES/OWNS/DELIVERS ...) with
    evidence inside the project's files."""
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT DISTINCT r.relationship_type, t.entity_type AS target_type, t.canonical_name AS target
              FROM relationships r
              JOIN relationship_evidence re ON re.relationship_id = r.id
              JOIN project_files pfl ON pfl.file_id = re.file_id
              JOIN entities t ON t.id = r.target_entity_id
             WHERE pfl.project_id = :p AND r.source_entity_id = :me
        """), {"p": project_id, "me": me_id}))


def project_technology_mentions(project_id: int) -> list[dict[str, Any]]:
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT e.id AS entity_id, e.canonical_name AS name, e.entity_type,
                   COUNT(em.id) AS mention_count,
                   MIN(fr.last_modified_at) AS first_seen, MAX(fr.last_modified_at) AS last_seen,
                   ARRAY_AGG(DISTINCT em.file_id) AS file_ids
              FROM entity_mentions em
              JOIN entities e ON e.id = em.entity_id
              JOIN project_files pfl ON pfl.file_id = em.file_id
              JOIN file_registry fr ON fr.id = em.file_id
             WHERE pfl.project_id = :p AND e.entity_type IN ('technology', 'product', 'concept', 'process')
             GROUP BY e.id
             ORDER BY mention_count DESC
             LIMIT 60
        """), {"p": project_id}))


# --- role_assignments ---------------------------------------------------------

def list_roles(project_id: int | None = None, me_only: bool = False) -> list[dict[str, Any]]:
    if not table_exists("role_assignments"):
        return []
    where, params = [], {}
    if project_id is not None:
        where.append("ra.project_id = :p"); params["p"] = project_id
    if me_only:
        where.append("ra.is_me")
    with conn() as c:
        return _rows(c.execute(text(f"""
            SELECT ra.*, p.name AS project, p.project_key, e.canonical_name AS person
              FROM role_assignments ra
              JOIN projects p ON p.id = ra.project_id
              JOIN entities e ON e.id = ra.person_entity_id
             {"WHERE " + " AND ".join(where) if where else ""}
             ORDER BY ra.project_id, ra.confidence DESC
        """), params))


def upsert_role_assignment(row: dict[str, Any]) -> int:
    """Insert/update a role unless a human already confirmed/rejected it."""
    with conn() as c:
        existing = c.execute(text("""
            SELECT id, status FROM role_assignments
             WHERE project_id = :project_id AND person_entity_id = :person_entity_id AND role = :role
        """), row).fetchone()
        if existing and existing.status in ("confirmed", "rejected"):
            return existing.id
        res = c.execute(text("""
            INSERT INTO role_assignments
                (project_id, person_entity_id, is_me, role, role_label, period_start, period_end,
                 confidence, signals, sources, method, status)
            VALUES (:project_id, :person_entity_id, :is_me, :role, :role_label, :period_start, :period_end,
                    :confidence, CAST(:signals AS jsonb), CAST(:sources AS jsonb), :method, 'proposed')
            ON CONFLICT (project_id, person_entity_id, role) DO UPDATE SET
                is_me = EXCLUDED.is_me, role_label = COALESCE(EXCLUDED.role_label, role_assignments.role_label),
                period_start = COALESCE(EXCLUDED.period_start, role_assignments.period_start),
                period_end = COALESCE(EXCLUDED.period_end, role_assignments.period_end),
                confidence = EXCLUDED.confidence, signals = EXCLUDED.signals, sources = EXCLUDED.sources,
                method = EXCLUDED.method, updated_at = NOW()
            RETURNING id
        """), {**row, "signals": json.dumps(row.get("signals") or {}, default=str),
               "sources": json.dumps(row.get("sources") or [], default=str)}).fetchone()
        return res[0]


def set_role_status(project_id: int, role: str, status: str, me_id: int) -> bool:
    with conn() as c:
        res = c.execute(text("""
            UPDATE role_assignments SET status = :s, method = CASE WHEN :s = 'confirmed' THEN 'confirmed' ELSE method END,
                   updated_at = NOW()
             WHERE project_id = :p AND person_entity_id = :me AND role = :r
        """), {"s": status, "p": project_id, "me": me_id, "r": role})
        if res.rowcount == 0 and status == "confirmed":
            c.execute(text("""
                INSERT INTO role_assignments (project_id, person_entity_id, is_me, role, confidence, method, status)
                VALUES (:p, :me, TRUE, :r, 1.0, 'confirmed', 'confirmed')
            """), {"p": project_id, "me": me_id, "r": role})
        c.execute(text("""
            UPDATE proposed_actions SET status = 'done', decided_at = NOW()
             WHERE project_id = :p AND action_type = 'confirm_role' AND status = 'pending'
        """), {"p": project_id})
        return True


# --- proposed actions (role confirmations) --------------------------------------

def pending_action_exists(project_id: int, action_type: str) -> bool:
    with conn() as c:
        return c.execute(text("""
            SELECT 1 FROM proposed_actions
             WHERE project_id = :p AND action_type = :t AND status = 'pending' LIMIT 1
        """), {"p": project_id, "t": action_type}).fetchone() is not None


def insert_proposed_action(project_id: int | None, action_type: str, title: str, detail: str | None,
                           payload: dict[str, Any], source_fact_ids: Iterable[int],
                           proposed_by: str = "career") -> int:
    with conn() as c:
        row = c.execute(text("""
            INSERT INTO proposed_actions (project_id, action_type, title, detail, payload, source_fact_ids, proposed_by)
            VALUES (:p, :t, :title, :detail, CAST(:payload AS jsonb), CAST(:ids AS jsonb), :by)
            RETURNING id
        """), {"p": project_id, "t": action_type, "title": title, "detail": detail,
               "payload": json.dumps(payload, default=str), "ids": json.dumps(sorted(set(source_fact_ids))),
               "by": proposed_by}).fetchone()
        return row[0]


# --- achievements ---------------------------------------------------------------

def upsert_achievement(row: dict[str, Any], run_id: str | None) -> int:
    with conn() as c:
        res = c.execute(text("""
            INSERT INTO achievements
                (project_id, statement, metric, outcome_kind, is_me, evidence_fact_ids, evidence_file_ids,
                 confidence, period_start, period_end, source_hash, status, run_id)
            VALUES (:project_id, :statement, CAST(:metric AS jsonb), :outcome_kind, :is_me,
                    CAST(:fact_ids AS jsonb), CAST(:file_ids AS jsonb), :confidence, :period_start, :period_end,
                    :source_hash, 'proposed', :run_id)
            ON CONFLICT (project_id, source_hash) DO UPDATE SET
                statement = EXCLUDED.statement, metric = EXCLUDED.metric, outcome_kind = EXCLUDED.outcome_kind,
                is_me = EXCLUDED.is_me, evidence_file_ids = EXCLUDED.evidence_file_ids,
                confidence = EXCLUDED.confidence, period_start = EXCLUDED.period_start,
                period_end = EXCLUDED.period_end,
                status = CASE WHEN achievements.status = 'orphaned' THEN 'proposed' ELSE achievements.status END,
                updated_at = NOW()
            RETURNING id
        """), {**row, "metric": json.dumps(row.get("metric"), default=str) if row.get("metric") else None,
               "fact_ids": json.dumps(row.get("evidence_fact_ids") or []),
               "file_ids": json.dumps(row.get("evidence_file_ids") or []), "run_id": run_id}).fetchone()
        return res[0]


def orphan_missing_achievements(project_id: int, keep_hashes: Iterable[str]) -> int:
    with conn() as c:
        res = c.execute(text("""
            UPDATE achievements SET status = 'orphaned', updated_at = NOW()
             WHERE project_id = :p AND status IN ('proposed')
               AND NOT (source_hash = ANY(CAST(:keep AS text[])))
        """), {"p": project_id, "keep": list(keep_hashes) or [""]})
        return res.rowcount


def list_achievements(project_id: int | None = None, me_only: bool = False,
                      limit: int = 200) -> list[dict[str, Any]]:
    if not table_exists("achievements"):
        return []
    where, params = ["a.status <> 'rejected'"], {"limit": limit}
    if project_id is not None:
        where.append("a.project_id = :p"); params["p"] = project_id
    if me_only:
        where.append("a.is_me")
    with conn() as c:
        return _rows(c.execute(text(f"""
            SELECT a.*, p.name AS project, p.project_key
              FROM achievements a LEFT JOIN projects p ON p.id = a.project_id
             WHERE {" AND ".join(where)}
             ORDER BY a.confidence DESC, a.id
             LIMIT :limit
        """), params))


# --- skill evidence -------------------------------------------------------------

def upsert_skill_evidence(row: dict[str, Any]) -> None:
    with conn() as c:
        c.execute(text("""
            INSERT INTO skill_evidence
                (entity_id, project_id, skill_kind, role, mention_count, evidence_fact_ids, evidence_file_ids,
                 strength, first_seen, last_seen)
            VALUES (:entity_id, :project_id, :skill_kind, :role, :mention_count, CAST(:fact_ids AS jsonb),
                    CAST(:file_ids AS jsonb), :strength, :first_seen, :last_seen)
            ON CONFLICT (entity_id, project_id) DO UPDATE SET
                skill_kind = EXCLUDED.skill_kind, role = EXCLUDED.role, mention_count = EXCLUDED.mention_count,
                evidence_fact_ids = EXCLUDED.evidence_fact_ids, evidence_file_ids = EXCLUDED.evidence_file_ids,
                strength = EXCLUDED.strength, first_seen = EXCLUDED.first_seen, last_seen = EXCLUDED.last_seen,
                updated_at = NOW()
        """), {**row, "fact_ids": json.dumps(row.get("evidence_fact_ids") or []),
               "file_ids": json.dumps(row.get("evidence_file_ids") or [])})


def list_skills(limit: int = 300) -> list[dict[str, Any]]:
    if not table_exists("skill_evidence"):
        return []
    with conn() as c:
        return _rows(c.execute(text("""
            SELECT se.*, e.canonical_name AS skill, p.name AS project
              FROM skill_evidence se
              JOIN entities e ON e.id = se.entity_id
              JOIN projects p ON p.id = se.project_id
             ORDER BY se.strength DESC
             LIMIT :limit
        """), {"limit": limit}))


# --- career_state (incremental guard) -------------------------------------------

def career_hash(project_id: int) -> str | None:
    if not table_exists("career_state"):
        return None
    with conn() as c:
        row = c.execute(text("SELECT source_hash FROM career_state WHERE project_id = :p"), {"p": project_id}).fetchone()
    return row[0] if row else None


def save_career_hash(project_id: int, source_hash: str) -> None:
    with conn() as c:
        c.execute(text("""
            INSERT INTO career_state (project_id, source_hash, built_at) VALUES (:p, :h, NOW())
            ON CONFLICT (project_id) DO UPDATE SET source_hash = EXCLUDED.source_hash, built_at = NOW()
        """), {"p": project_id, "h": source_hash})


def _d(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None
