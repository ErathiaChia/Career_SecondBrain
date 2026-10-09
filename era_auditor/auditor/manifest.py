"""Vault Manifest export: the neutral hand-off from the auditor to the indexer and
era_mcp (see era_mcp/docs/agentic_mcp_design.md, section 5).

Writes two plain tables that other components read instead of ``auditor_*``:

- ``vault_manifest``: one row per registered project (and its customer), carrying
  the human-curated client, lifecycle, archetype, and folder path.
- ``vault_reusable_assets``: assets reused across projects/customers, for
  cross-project reuse suggestions.

Both are fully rewritten on each export and stamped with ``manifest_version`` /
``generated_at`` so readers can detect staleness.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

_DDL = """
CREATE TABLE IF NOT EXISTS vault_manifest (
    path TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT,
    parent TEXT,
    project_key TEXT,
    customer_code TEXT,
    customer_name TEXT,
    status TEXT,
    lifecycle TEXT,
    initiative_type TEXT,
    year INTEGER,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    manifest_version INTEGER NOT NULL DEFAULT 1,
    generated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS vault_reusable_assets (
    asset_key TEXT PRIMARY KEY,
    asset_name TEXT NOT NULL,
    file_type TEXT,
    reuse_score INTEGER NOT NULL DEFAULT 0,
    copy_count INTEGER NOT NULL DEFAULT 1,
    paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    projects JSONB NOT NULL DEFAULT '[]'::jsonb,
    customers JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical_location TEXT,
    generated_at TIMESTAMP NOT NULL DEFAULT NOW()
)
"""


def manifest_rows(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project registry rows -> vault_manifest rows (pure; unit-tested)."""
    out: dict[str, dict[str, Any]] = {}
    for p in projects:
        path = str(p.get("folder_path") or p.get("canonical_path") or "").strip("/")
        if not path:
            continue
        parent = path.rsplit("/", 1)[0] if "/" in path else None
        metadata = p.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata or "{}")
        out[path] = {
            "path": path,
            "name": p.get("initiative_name") or path.rsplit("/", 1)[-1],
            "kind": "project",
            "parent": parent,
            "project_key": p.get("project_id"),
            "customer_code": p.get("customer_code"),
            "customer_name": p.get("customer_name"),
            "status": p.get("status"),
            "lifecycle": metadata.get("lifecycle") or p.get("lifecycle"),
            "initiative_type": p.get("initiative_type"),
            "year": p.get("year"),
            "tags": json.dumps(p.get("tags") or []),
            "metadata": json.dumps({k: v for k, v in metadata.items() if k != "lifecycle"}),
        }
        if parent and p.get("customer_code") and parent not in out:
            out[parent] = {
                "path": parent, "name": p.get("customer_name") or p.get("customer_code"),
                "kind": "customer", "parent": parent.rsplit("/", 1)[0] if "/" in parent else None,
                "project_key": None, "customer_code": p.get("customer_code"),
                "customer_name": p.get("customer_name"), "status": None, "lifecycle": None,
                "initiative_type": None, "year": p.get("year"), "tags": "[]", "metadata": "{}",
            }
    return list(out.values())


def export_manifest(database: Any, min_reuse_score: int = 1) -> dict[str, int]:
    engine = database.engine
    with engine.begin() as conn:
        for stmt in _DDL.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
        projects = [dict(r._mapping) for r in conn.execute(text("SELECT * FROM auditor_projects")).fetchall()]
        version = (conn.execute(text("SELECT COALESCE(MAX(manifest_version), 0) FROM vault_manifest")).scalar() or 0) + 1
        rows = manifest_rows(projects)
        conn.execute(text("DELETE FROM vault_manifest"))
        for row in rows:
            conn.execute(text("""
                INSERT INTO vault_manifest
                    (path, name, kind, parent, project_key, customer_code, customer_name,
                     status, lifecycle, initiative_type, year, tags, metadata, manifest_version)
                VALUES (:path, :name, :kind, :parent, :project_key, :customer_code, :customer_name,
                        :status, :lifecycle, :initiative_type, :year, CAST(:tags AS jsonb),
                        CAST(:metadata AS jsonb), :version)
            """), {**row, "version": version})
        assets = conn.execute(text("""
            SELECT asset_key, asset_name, file_type, reuse_score, copy_count, paths,
                   projects, customers, canonical_location
              FROM auditor_assets
             WHERE reuse_score >= :min_score
        """), {"min_score": min_reuse_score}).fetchall()
        conn.execute(text("DELETE FROM vault_reusable_assets"))
        for a in assets:
            conn.execute(text("""
                INSERT INTO vault_reusable_assets
                    (asset_key, asset_name, file_type, reuse_score, copy_count, paths,
                     projects, customers, canonical_location)
                VALUES (:asset_key, :asset_name, :file_type, :reuse_score, :copy_count,
                        CAST(:paths AS jsonb), CAST(:projects AS jsonb), CAST(:customers AS jsonb),
                        :canonical_location)
            """), {
                **dict(a._mapping),
                "paths": json.dumps(a.paths or []),
                "projects": json.dumps(a.projects or []),
                "customers": json.dumps(a.customers or []),
            })
    return {"manifest_rows": len(rows), "reusable_assets": len(assets), "manifest_version": version}
