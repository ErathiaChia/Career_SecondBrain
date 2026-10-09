"""Monitoring: the scheduled project-intelligence pipeline and its digest.

``run`` executes every stage in order, isolating failures so one broken stage
never stops the rest:

    sync -> extract -> projects/versions -> changes -> conflicts/stale ->
    state -> similarity -> digest

``build_digest`` scores candidate items (changes, health, overdue and upcoming
work, conflicts, pending approvals) for attention and keeps only those at or
above ``threshold``. An item already reported in the previous digest loses
REPEAT_PENALTY points, so standing issues fade unless they are severe.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

from rich.console import Console

from career_history import intel_db

console = Console()

SEVERITY_SCORE = {"info": 10, "notice": 30, "warning": 60, "critical": 90}
REPEAT_PENALTY = 20


def score_items(inputs: dict[str, Any], today: date | None = None) -> list[dict[str, Any]]:
    """Turn digest inputs into scored, keyed attention items."""
    today = today or date.today()
    soon = (today + timedelta(days=7)).isoformat()
    items: list[dict[str, Any]] = []
    batches: dict[str, dict[str, Any]] = {}
    for c in inputs.get("changes", []):
        key = c.get("batch_id") or f"{c['project_id']}:{c['summary']}"
        b = batches.setdefault(key, {"project": c["project"], "severity": "info", "impact": c.get("impact") or {},
                                     "count": 0})
        b["count"] += 1
        if SEVERITY_SCORE.get(c["severity"], 0) > SEVERITY_SCORE.get(b["severity"], 0):
            b["severity"] = c["severity"]
    for key, b in batches.items():
        impact = b["impact"]
        items.append({"key": f"change:{key}", "type": "change", "project": b["project"],
                      "score": SEVERITY_SCORE.get(b["severity"], 10) + min(10, b["count"]),
                      "title": impact.get("summary") or f"{b['count']} change(s)",
                      "detail": "; ".join(impact.get("impact") or [])[:400],
                      "rationale_found": impact.get("rationale_found")})
    for s in inputs.get("states", []):
        health = s.get("health") or {}
        level = health.get("level")
        if level in {"red", "amber"}:
            items.append({"key": f"health:{s['project_id']}:{level}", "type": "health", "project": s["project"],
                          "score": 70 if level == "red" else 45,
                          "title": f"Health {level.upper()} ({health.get('overall')}/100)",
                          "detail": health.get("headline", "")})
        overdue = s.get("overdue") or []
        if overdue:
            ids = sorted(o["fact_id"] for o in overdue)
            items.append({"key": f"overdue:{s['project_id']}:{','.join(map(str, ids))}", "type": "overdue",
                          "project": s["project"], "score": 50 + 5 * min(6, len(overdue) - 1),
                          "title": f"{len(overdue)} overdue item(s)",
                          "detail": "; ".join(f"{o['statement']} (due {o.get('due')})" for o in overdue[:4])})
        for m in s.get("upcoming") or []:
            if m.get("due") and m["due"] <= soon:
                items.append({"key": f"upcoming:{m['fact_id']}", "type": "upcoming", "project": s["project"],
                              "score": 40, "title": f"Due {m['due']}: {m['statement']}", "detail": ""})
    by_project: dict[Any, list[dict[str, Any]]] = {}
    for c in inputs.get("conflicts", []):
        by_project.setdefault(c["project_id"], []).append(c)
    for project_id, rows in by_project.items():
        ids = sorted(c["id"] for c in rows)
        types = sorted({c["conflict_type"] for c in rows})
        items.append({"key": f"conflict:{project_id}:{','.join(map(str, ids))}", "type": "conflict",
                      "project": rows[0]["project"], "score": 45 + min(10, len(rows) - 1),
                      "title": f"{len(rows)} conflicting fact pair(s) to confirm ({', '.join(types)})",
                      "detail": "; ".join(c.get("explanation") or "" for c in rows[:3])[:400]})
    pending = inputs.get("proposed", [])
    if pending:
        items.append({"key": f"proposed:{','.join(str(p['id']) for p in pending)}", "type": "approval",
                      "project": None, "score": 35, "title": f"{len(pending)} proposed action(s) awaiting approval",
                      "detail": "; ".join(p["title"] for p in pending[:5])})
    previous = inputs.get("previous_keys") or set()
    for item in items:
        if item["key"] in previous:
            item["score"] -= REPEAT_PENALTY
            item["repeat"] = True
    items.sort(key=lambda i: -i["score"])
    return items


def render_digest(items: list[dict[str, Any]], threshold: int, generated: datetime | None = None) -> str:
    generated = generated or datetime.now()
    kept = [i for i in items if i["score"] >= threshold]
    lines = [f"# Project digest — {generated.strftime('%Y-%m-%d %H:%M')}",
             f"_{len(kept)} item(s) at or above attention score {threshold} "
             f"({len(items) - len(kept)} below threshold)._", ""]
    if not kept:
        lines.append("Nothing needs your attention right now.")
        return "\n".join(lines)
    by_project: dict[str, list[dict[str, Any]]] = {}
    for i in kept:
        by_project.setdefault(i["project"] or "Across projects", []).append(i)
    for project, rows in by_project.items():
        lines.append(f"## {project}")
        for r in rows:
            tail = " _(still open from last digest)_" if r.get("repeat") else ""
            lines.append(f"- **[{r['score']}] {r['title']}**{tail}")
            if r.get("detail"):
                lines.append(f"  - {r['detail']}")
            if r["type"] == "change" and r.get("rationale_found") is False:
                lines.append("  - Rationale not found in the documents.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_digest(threshold: int = 40, since_days: int = 7, save: bool = True) -> dict[str, Any]:
    items = score_items(intel_db.digest_inputs(since_days))
    markdown = render_digest(items, threshold)
    kept = [i for i in items if i["score"] >= threshold]
    stats = {"candidates": len(items), "kept": len(kept), "threshold": threshold, "since_days": since_days}
    digest_id = intel_db.save_digest(kept, markdown, stats) if save else None
    return {"digest_id": digest_id, "markdown": markdown, **stats}


def _stage(results: dict[str, Any], name: str, fn: Callable[[], Any]) -> None:
    t0 = time.monotonic()
    try:
        out = fn()
        results[name] = {"ok": True, "seconds": round(time.monotonic() - t0, 1),
                         "result": out if isinstance(out, dict) else None}
    except Exception as e:  # noqa: BLE001 — one stage never stops the pipeline
        results[name] = {"ok": False, "seconds": round(time.monotonic() - t0, 1),
                         "error": f"{type(e).__name__}: {e}"}
        console.log(f"[red]monitor stage {name} failed:[/red] {e}")


def run(folder: str | None = None, skip_sync: bool = False, skip_extract: bool = False,
        use_llm: bool = True, threshold: int = 40) -> dict[str, Any]:
    from career_history import changes, conflicts, project_state, projects, similarity, versions

    results: dict[str, Any] = {}
    if not skip_sync:
        def sync() -> None:
            from career_history import config, discover, runner
            settings = config.run_everything()
            discover.discover(folder=folder, run_settings=settings)
            runner.run(folder=folder, limit=None, run_settings=settings)
        _stage(results, "sync", sync)
    if not skip_extract and use_llm:
        def extract() -> dict[str, Any]:
            from career_history import graph
            return graph.refresh_documents(folder=folder)
        _stage(results, "extract", extract)
    _stage(results, "projects", projects.discover_projects)
    _stage(results, "versions", versions.link_versions)
    _stage(results, "changes", lambda: changes.detect_changes(use_llm=use_llm))
    _stage(results, "conflicts", lambda: conflicts.detect_conflicts(use_llm=use_llm, max_pairs=50))
    _stage(results, "stale", conflicts.detect_stale)
    _stage(results, "state", lambda: project_state.refresh_states(use_llm=use_llm))
    _stage(results, "similarity", similarity.refresh_similarity)
    _stage(results, "digest", lambda: build_digest(threshold=threshold))
    digest = (results["digest"].get("result") or {}) if results["digest"]["ok"] else {}
    if digest.get("markdown"):
        console.print(digest["markdown"])
    summary = {name: ("ok" if r["ok"] else r["error"]) for name, r in results.items()}
    summary["digest_items"] = digest.get("kept", 0)
    return summary
