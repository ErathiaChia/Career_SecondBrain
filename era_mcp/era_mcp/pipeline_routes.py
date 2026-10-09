"""Pipeline status: how current is the knowledge? Reads ``pipeline_runs``
(written by the indexer's weekly run) plus a live extraction backlog. Degrades
to an empty answer when the table does not exist yet.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text

from era_mcp import projects, retrieval

router = APIRouter()

_RUN_COLUMNS = ("run_id", "kind", "host", "git_sha", "started_at", "finished_at", "deadline_at",
                "heartbeat_at", "status", "stage", "stages", "counts", "errors", "digest_id")


def _stale_hours() -> float:
    return float(os.environ.get("PIPELINE_STALE_HOURS", "3"))


def _fetch_runs(limit: int) -> list[dict[str, Any]]:
    if not projects._present("pipeline_runs"):
        return []
    with retrieval._get_engine().connect() as conn:
        rows = conn.execute(text(f"""
            SELECT {", ".join(_RUN_COLUMNS)} FROM pipeline_runs
             ORDER BY started_at DESC LIMIT :limit
        """), {"limit": limit}).fetchall()
    return [dict(r._mapping) for r in rows]


def _fetch_backlog() -> Optional[int]:
    """Cheap proxy for 'documents still waiting for extraction' (no hashing)."""
    if not projects._present("document_extraction_state"):
        return None
    with retrieval._get_engine().connect() as conn:
        return int(conn.execute(text("""
            SELECT count(*) FROM file_registry fr
              LEFT JOIN document_extraction_state des ON des.file_id = fr.id
             WHERE fr.deleted_at IS NULL
               AND EXISTS (SELECT 1 FROM document_chunks dc WHERE dc.file_id = fr.id)
               AND (des.file_id IS NULL OR des.status = 'failed'
                    OR fr.last_processed_at > des.extracted_at)
        """)).scalar() or 0)


def summarize(runs: list[dict[str, Any]], backlog: Optional[int], now: Optional[datetime] = None,
              stale_hours: Optional[float] = None) -> dict[str, Any]:
    """Pure shaping of the status payload (unit-tested)."""
    now = now or datetime.now()
    stale_hours = _stale_hours() if stale_hours is None else stale_hours
    latest = runs[0] if runs else None
    completed = next((r for r in runs if r.get("status") in ("finished", "partial")), None)
    out: dict[str, Any] = {
        "latest_run": latest,
        "last_completed_run": completed,
        "backlog_documents": backlog,
        "stale": False,
        "knowledge_as_of": (completed or {}).get("finished_at") if completed else None,
    }
    if latest and latest.get("status") == "running":
        hb = latest.get("heartbeat_at")
        if isinstance(hb, str):
            hb = datetime.fromisoformat(hb)
        if hb is not None and (now - hb).total_seconds() > stale_hours * 3600:
            out["stale"] = True
            out["stale_reason"] = (f"run {latest.get('run_id')} reports 'running' but its last heartbeat "
                                   f"was {round((now - hb).total_seconds() / 3600, 1)} h ago")
    if not runs:
        out["note"] = ("No pipeline run recorded yet. The knowledge base is whatever the last manual "
                       "`career_history.cli update` / `extract-documents` produced.")
    return out


@router.get("/pipeline/status", operation_id="pipeline_status")
async def pipeline_status() -> dict:
    """How current the knowledge base is: the latest weekly/manual pipeline run
    (status, stage, counts, errors, finish time), the last completed run (the
    'knowledge as of' time), the number of documents still waiting for
    extraction, and a stale flag when a run claims to be running but stopped
    heartbeating. Call this before answering "is this up to date?"."""
    runs = await run_in_threadpool(_fetch_runs, 5)
    backlog = await run_in_threadpool(_fetch_backlog)
    return summarize(runs, backlog)


@router.get("/pipeline/runs", operation_id="list_pipeline_runs", include_in_schema=False)
async def list_pipeline_runs(limit: int = Query(default=10, ge=1, le=100)) -> dict:
    runs = await run_in_threadpool(_fetch_runs, limit)
    return {"count": len(runs), "runs": runs}
