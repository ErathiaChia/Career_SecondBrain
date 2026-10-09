"""The weekend knowledge pipeline (brief §4, §16): one tracked, deadline-bound,
resumable run that moves every expensive step to the weekend.

    preflight -> migrate -> sync -> extract -> [cards] -> projects -> versions
    -> resolve-entities -> changes -> conflicts -> stale -> similarity
    -> [career] -> state -> [eval] -> digest -> finalize

Stages in [] are hooks that run only when their module exists (later phases).
Every stage is failure-isolated (``monitor._stage``); the run row in
``pipeline_runs`` carries stage results, counts and a heartbeat so a client can
ask /pipeline/status how current the knowledge is.
"""
from __future__ import annotations

import importlib
import os
import platform
import re
import subprocess
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

from rich.console import Console

from career_history import config, db, intel_db, monitor

console = Console()

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# Weekdays 07:00-23:00 are interactive hours: no LLM-heavy stages unless forced.
INTERACTIVE_START, INTERACTIVE_END = 7, 23


def parse_deadline(spec: str | None, now: datetime | None = None) -> datetime | None:
    """'Mon 05:00' (next occurrence, strictly after now), 'HH:MM' (next
    occurrence today/tomorrow), '+12h' / '+90m', or an ISO datetime."""
    now = now or datetime.now()
    if not spec:
        return None
    s = spec.strip()
    m = re.fullmatch(r"\+(\d+)\s*([hm])", s, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        return now + (timedelta(hours=n) if unit == "h" else timedelta(minutes=n))
    m = re.fullmatch(r"([A-Za-z]{3})[a-z]*\s+(\d{1,2}):(\d{2})", s)
    if m and m.group(1).lower() in _WEEKDAYS:
        wd, hh, mm = _WEEKDAYS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
        cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        days = (wd - now.weekday()) % 7
        cand += timedelta(days=days)
        if cand <= now:
            cand += timedelta(days=7)
        return cand
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if m:
        cand = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if cand <= now:
            cand += timedelta(days=1)
        return cand
    return datetime.fromisoformat(s)


def is_interactive_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return now.weekday() < 5 and INTERACTIVE_START <= now.hour < INTERACTIVE_END


def should_catchup(last_run: dict[str, Any] | None, backlog: int, now: datetime | None = None) -> bool:
    """A catch-up run only happens when the last run did not finish (partial or
    failed), or no run happened this week at all, AND there is extraction work."""
    if backlog <= 0:
        return False
    if last_run is None:
        return True
    if last_run.get("status") in ("partial", "failed", "aborted"):
        return True
    now = now or datetime.now()
    started = last_run.get("started_at")
    if isinstance(started, str):
        started = datetime.fromisoformat(started)
    return started is None or (now - started) > timedelta(days=7)


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=5, cwd=os.path.dirname(os.path.dirname(__file__))).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def _model_config() -> dict[str, Any]:
    cfg = config.get()
    models = cfg.get("models") or {}
    return {"graph_extraction_model": models.get("graph_extraction_model"),
            "embedding_model": models.get("embedding_model"),
            "graph_doc_window_chars": models.get("graph_doc_window_chars"),
            "graph_doc_max_windows": models.get("graph_doc_max_windows")}


def _ollama_url() -> str:
    cfg = config.get()
    return ((cfg.get("v2") or {}).get("graph_ollama_base_url")
            or (cfg.get("models") or {}).get("ollama_base_url") or "http://localhost:11434")


def preflight(use_llm: bool) -> dict[str, Any]:
    """Abort early with a clear reason rather than fail halfway through."""
    out: dict[str, Any] = {"ok": True, "checks": {}}
    try:
        with db.conn() as c:
            c.execute(db.text("SELECT 1"))
        out["checks"]["database"] = "ok"
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["checks"]["database"] = f"FAIL: {e}"
    roots = [r for r in config.get_source_directories() if os.path.isdir(r)]
    out["checks"]["vault_roots"] = f"{len(roots)} mounted" if roots else "FAIL: no source directory is mounted"
    if not roots:
        out["ok"] = False  # discover() would see an empty vault; never risk mass soft-deletes
    if use_llm:
        try:
            import httpx
            r = httpx.get(f"{_ollama_url()}/api/tags", timeout=5)
            r.raise_for_status()
            have = {m.get("name") for m in r.json().get("models", [])}
            want = (config.get().get("models") or {}).get("graph_extraction_model")
            ok = (not want) or want in have or f"{want}:latest" in have
            out["checks"]["ollama"] = "ok" if ok else f"FAIL: model {want} not pulled"
            out["ok"] = out["ok"] and ok
        except Exception as e:  # noqa: BLE001
            out["ok"] = False
            out["checks"]["ollama"] = f"FAIL: {e}"
    return out


def _optional_stage(results: dict[str, Any], name: str, module: str, func: str, **kwargs: Any) -> None:
    """Run ``module.func(**kwargs)`` as a stage if the module exists (hooks for
    later phases: cards, career, eval). Missing module -> stage skipped."""
    try:
        mod = importlib.import_module(module)
    except ImportError:
        results[name] = {"ok": True, "skipped": "module not present", "seconds": 0.0, "result": None}
        return
    monitor._stage(results, name, lambda: getattr(mod, func)(**kwargs))


def plan(kind: str, max_docs: int | None, deadline: datetime | None, use_llm: bool,
         catchup: bool) -> dict[str, Any]:
    """What a run would do — printed by --dry-run and logged at start."""
    last = intel_db.latest_pipeline_run()
    backlog = db.extraction_backlog()
    return {
        "kind": kind,
        "deadline": deadline.isoformat(timespec="minutes") if deadline else None,
        "max_docs": max_docs,
        "use_llm": use_llm,
        "backlog_documents": backlog,
        "estimated_extract_hours": round(min(backlog, max_docs or backlog) * 85 / 3600, 1),
        "last_run": {k: last.get(k) for k in ("run_id", "kind", "status", "started_at", "finished_at")} if last else None,
        "catchup_needed": should_catchup(last, backlog) if catchup else None,
        "models": _model_config(),
        "interactive_hours_now": is_interactive_hours(),
    }


def run(
    kind: str = "weekly",
    max_docs: int | None = 1200,
    deadline: str | datetime | None = "Mon 05:00",
    catchup: bool = False,
    dry_run: bool = False,
    skip_sync: bool = False,
    skip_extract: bool = False,
    use_llm: bool = True,
    audio: bool = False,
    threshold: int = 40,
    force_hours: bool = False,
    folder: str | None = None,
) -> dict[str, Any]:
    from career_history import changes, conflicts, project_state, projects, resolve, similarity, versions

    deadline_dt = parse_deadline(deadline) if isinstance(deadline, str) else deadline
    if catchup:
        kind = "catchup"
    summary_plan = plan(kind, max_docs, deadline_dt, use_llm, catchup)
    if dry_run:
        console.print(summary_plan)
        return {"dry_run": True, **summary_plan}
    if catchup and not summary_plan["catchup_needed"]:
        console.log("[dim]catch-up not needed (last run finished and/or no backlog); exiting[/dim]")
        return {"skipped": True, **summary_plan}
    if use_llm and not force_hours and not catchup and is_interactive_hours():
        raise RuntimeError("LLM-heavy stages do not run on weekdays 07:00-23:00; "
                           "pass --force-hours to override (or --no-llm).")

    run_id = f"{kind}-{datetime.now():%Y%m%d-%H%M}-{uuid.uuid4().hex[:6]}"
    os.environ["ERA_RUN_ID"] = run_id  # fact / digest provenance for the weekly report
    results: dict[str, Any] = {}
    counts: dict[str, Any] = {}
    errors: list[str] = []
    started = datetime.now()

    pre = preflight(use_llm)
    results["preflight"] = {"ok": pre["ok"], "seconds": 0.0, "result": pre["checks"]}
    if not pre["ok"]:
        console.log(f"[red]preflight failed:[/red] {pre['checks']}")
        try:
            intel_db.start_pipeline_run(run_id, kind, platform.node(), _git_sha(), deadline_dt, _model_config())
            intel_db.finish_pipeline_run(run_id, "failed", results, counts, [str(pre["checks"])])
        except Exception:  # noqa: BLE001 — the DB itself may be the failure
            pass
        return {"run_id": run_id, "status": "failed", "preflight": pre["checks"]}

    monitor._stage(results, "migrate", lambda: {"applied": db.migrate()})
    intel_db.start_pipeline_run(run_id, kind, platform.node(), _git_sha(), deadline_dt, _model_config())

    def hb(stage: str) -> None:
        try:
            intel_db.heartbeat_pipeline_run(run_id, stage=stage, stages=results, counts=counts)
        except Exception:  # noqa: BLE001
            pass

    hb("sync")
    try:  # freshness probe (brief §23): a vault file carrying this run id
        from career_history import evalprobe
        probe = evalprobe.arm(run_id)
        if probe:
            counts["freshness_probe"] = probe
    except Exception as e:  # noqa: BLE001
        console.log(f"[yellow]freshness probe skipped:[/yellow] {e}")
    if not skip_sync:
        def sync() -> dict[str, Any]:
            from career_history import discover, runner
            settings = config.run_everything() if audio else config.run_documents()
            d = discover.discover(folder=folder, run_settings=settings)
            r = runner.run(folder=folder, limit=None, run_settings=settings)
            counts.update({"files_new_or_changed": d.get("new_or_changed", 0),
                           "files_unchanged": d.get("unchanged", 0),
                           "files_removed": d.get("removed", 0),
                           "files_processed": r.get("processed", 0),
                           "files_failed": r.get("failed", 0)})
            return {**d, **r}
        monitor._stage(results, "sync", sync)

    hb("extract")
    stopped_early = False
    if not skip_extract and use_llm:
        def extract() -> dict[str, Any]:
            from career_history import graph
            last = {"n": 0}

            def progress(done: int, failed: int, total: int) -> None:
                last["n"] += 1
                counts.update({"docs_extracted": done, "docs_failed": failed, "docs_selected": total})
                if last["n"] % 10 == 0:
                    hb("extract")
            out = graph.refresh_documents(folder=folder, limit=max_docs, deadline=deadline_dt,
                                          progress=progress, rebuild_snapshot=False)
            counts.update({"docs_extracted": out["processed_documents"], "docs_failed": out["failed_documents"],
                           "docs_remaining": db.extraction_backlog(folder),
                           "deadline_hit": out.get("stopped_early", False)})
            return out
        monitor._stage(results, "extract", extract)
        stopped_early = bool((results["extract"].get("result") or {}).get("stopped_early"))

    past_deadline = deadline_dt is not None and datetime.now() >= deadline_dt
    post_llm = use_llm and not catchup and not past_deadline

    hb("cards")
    _optional_stage(results, "cards", "career_history.cards", "refresh_cards", use_llm=post_llm)
    hb("projects")
    monitor._stage(results, "projects", projects.discover_projects)
    monitor._stage(results, "versions", versions.link_versions)
    monitor._stage(results, "resolve_entities",
                   lambda: resolve.resolve_entities(apply=True, use_embeddings=False))
    hb("changes")
    monitor._stage(results, "changes", lambda: changes.detect_changes(use_llm=post_llm))
    monitor._stage(results, "conflicts", lambda: conflicts.detect_conflicts(use_llm=post_llm, max_pairs=50))
    monitor._stage(results, "stale", conflicts.detect_stale)
    monitor._stage(results, "similarity", similarity.refresh_similarity)
    hb("career")
    _optional_stage(results, "career", "career_history.career", "refresh_career", use_llm=post_llm)
    hb("state")
    monitor._stage(results, "state", lambda: project_state.refresh_states(use_llm=post_llm))
    if kind != "catchup":
        hb("eval")
        _optional_stage(results, "eval", "career_history.evalrun", "run_weekly_eval", run_id=run_id)
        ev = (results.get("eval") or {}).get("result") or {}
        if ev.get("scores"):
            counts["eval"] = {"scores": ev["scores"], "hard_gates_passed": ev.get("hard_gates_passed")}
    hb("digest")
    monitor._stage(results, "digest", lambda: _build_report(run_id, threshold))
    digest = (results["digest"].get("result") or {}) if results["digest"]["ok"] else {}

    errors = [f"{n}: {r['error']}" for n, r in results.items() if not r.get("ok")]
    if errors and all(not r.get("ok") for n, r in results.items() if n not in ("preflight", "migrate")):
        status = "failed"
    elif errors or stopped_early:
        status = "partial"
    else:
        status = "finished"
    counts["elapsed_minutes"] = round((datetime.now() - started).total_seconds() / 60, 1)
    intel_db.finish_pipeline_run(run_id, status, results, counts, errors, digest.get("digest_id"))
    if digest.get("markdown"):
        console.print(digest["markdown"])
    summary = {name: ("ok" if r.get("ok") else r.get("error")) for name, r in results.items()}
    console.log(f"[bold]{kind} run {run_id}: {status}[/bold] {counts}")
    return {"run_id": run_id, "status": status, "counts": counts, "stages": summary,
            "digest_id": digest.get("digest_id")}


def _build_report(run_id: str, threshold: int) -> dict[str, Any]:
    """Weekly report when the renderer exists (Phase 4), else the attention digest."""
    if hasattr(monitor, "build_weekly_report"):
        return monitor.build_weekly_report(run_id=run_id, threshold=threshold)
    return monitor.build_digest(threshold=threshold)
