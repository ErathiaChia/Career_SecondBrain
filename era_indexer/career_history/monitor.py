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


# --- Weekly change-intelligence report (brief §16) ----------------------------------

SECTION_RULE = "──────────────"


def _bullet(text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return "• " + (text if len(text) <= limit else text[: limit - 1] + "…")


def render_weekly_report(inputs: dict[str, Any], generated: datetime | None = None,
                         attention: str | None = None, max_items: int = 12) -> str:
    """The fixed-heading report the brief asks for. ``inputs`` comes from
    ``intel_db.weekly_inputs``; ``attention`` is the scored digest appended as an
    extended section."""
    generated = generated or datetime.now()
    run = inputs.get("run") or {}
    window = inputs.get("window") or {}
    lines = ["CAREER INTELLIGENCE WEEKLY UPDATE",
             f"Week {str(window.get('since') or '')[:10]} – {generated:%Y-%m-%d} · run {run.get('run_id') or '-'} · "
             f"{run.get('status') or '-'} · generated {generated:%Y-%m-%d %H:%M}", ""]

    def section(title: str, body: list[str]) -> None:
        lines.extend([title, SECTION_RULE])
        lines.extend(body if body else ["(none)"])
        lines.append("")

    counts = inputs.get("event_counts") or {}
    section("NEW FILES", [str(counts.get("added", 0))])
    section("MODIFIED", [str(counts.get("modified", 0) + counts.get("version_added", 0) + counts.get("restored", 0))])
    section("NEW PROJECT INFORMATION",
            [_bullet(f"{r['project']} — {r.get('new_docs', 0)} new doc(s), {r.get('new_facts', 0)} new fact(s), "
                     f"{r.get('new_decisions', 0)} decision(s)") for r in (inputs.get("project_info") or [])[:max_items]])
    section("NEW DECISIONS",
            [_bullet(f"[F{d['id']}] {d['statement']} — {d.get('project') or '-'} · {d.get('file_name') or ''} · "
                     f"{str(d.get('occurred_at') or d.get('created_at') or '')[:10]}")
             for d in (inputs.get("new_decisions") or [])[:max_items]])
    section("NEW ACHIEVEMENTS",
            [_bullet(f"[A{a['id']}] {a['statement']}" + (f" [{(a.get('metric') or {}).get('raw')}]" if (a.get('metric') or {}).get('raw') else "")
                     + f" — {a.get('project') or '-'}" + (" (mine)" if a.get("is_me") else ""))
             for a in (inputs.get("new_achievements") or [])[:max_items]])
    section("CHANGED INFORMATION",
            [_bullet(f"{c.get('project') or '-'}: {c.get('summary')}" +
                     (f" — {c['impact'].get('summary')}" if isinstance(c.get("impact"), dict) and c["impact"].get("summary") else ""))
             for c in (inputs.get("changed_information") or [])[:max_items]])
    section("CONFLICTS",
            [_bullet(f"{c.get('project') or '-'}: '{c.get('statement_a')}' vs '{c.get('statement_b')}' — {c.get('conflict_type')}"
                     + (f", likely latest [F{c['likely_latest_fact_id']}]" if c.get("likely_latest_fact_id") else "") + f" (#{c['id']})")
             for c in (inputs.get("conflicts") or [])[:max_items]]
            + ([f"({inputs.get('open_conflicts_total')} open in total)"] if inputs.get("open_conflicts_total") else []))
    section("STALE INFORMATION",
            [_bullet(f"{s_.get('project') or '-'}: {s_.get('statement')} — {s_.get('reason')}"
                     + (f" (newer: [F{s_['newer_evidence_id']}])" if s_.get("newer_evidence_id") else ""))
             for s_ in (inputs.get("stale") or [])[:max_items]])

    lines.append(SECTION_RULE + " (extended)")
    section("DELETED FILES", [str(counts.get("deleted", 0))] +
            [_bullet(d.get("file_name") or d.get("file_path")) for d in (inputs.get("deleted") or [])[:6]])
    pc = (run.get("counts") or {})
    section("PIPELINE", [_bullet(f"{run.get('kind') or '-'} run {run.get('run_id') or '-'}: {run.get('status') or '-'}; "
                                 f"extracted {pc.get('docs_extracted', 0)}, failed {pc.get('docs_failed', 0)}, "
                                 f"backlog {pc.get('docs_remaining', '-')}, deadline hit: {pc.get('deadline_hit', False)}")])
    ev = inputs.get("eval") or {}
    if ev:
        section("EVAL TREND", [_bullet(f"{k}: {v}") for k, v in ev.items()])
    if attention:
        lines.extend(["ATTENTION ITEMS", SECTION_RULE])
        lines.extend(attention.strip().splitlines()[2:] or ["(none)"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_weekly_report(run_id: str | None = None, threshold: int = 40, save: bool = True,
                        since_days_fallback: int = 7) -> dict[str, Any]:
    """Weekly report (§16) + the scored attention digest, saved as digests.kind='weekly'
    and, when configured, as a markdown file (reports.weekly_dir / vault)."""
    inputs = intel_db.weekly_inputs(run_id, since_days_fallback)
    try:
        inputs["eval"] = _eval_trend()
    except Exception:  # noqa: BLE001
        inputs["eval"] = {}
    items = score_items(intel_db.digest_inputs(since_days_fallback))
    attention = render_digest(items, threshold)
    markdown = render_weekly_report(inputs, attention=attention)
    kept = [i for i in items if i["score"] >= threshold]
    stats = {"candidates": len(items), "kept": len(kept), "threshold": threshold,
             "new_files": (inputs.get("event_counts") or {}).get("added", 0),
             "modified": (inputs.get("event_counts") or {}).get("modified", 0),
             "new_decisions": len(inputs.get("new_decisions") or []),
             "new_achievements": len(inputs.get("new_achievements") or []),
             "conflicts": len(inputs.get("conflicts") or []), "stale": len(inputs.get("stale") or [])}
    digest_id = intel_db.save_digest(kept, markdown, stats, kind="weekly", run_id=run_id) if save else None
    path = _publish_report(markdown) if save else None
    return {"digest_id": digest_id, "markdown": markdown, "path": path, **stats}


def _eval_trend() -> dict[str, Any]:
    """Latest two scorecard runs from local/eval/runs, as 'now (prev)' strings."""
    import json
    from pathlib import Path
    from career_history import config
    runs_dir = Path((config.get().get("eval") or {}).get("runs_dir") or
                    Path(__file__).resolve().parents[2] / "local" / "eval" / "runs")
    files = sorted(runs_dir.glob("*.json"))[-2:] if runs_dir.exists() else []
    if not files:
        return {}
    cur = json.loads(files[-1].read_text())
    prev = json.loads(files[-2].read_text()) if len(files) > 1 else {}
    out: dict[str, Any] = {}
    for suite, res in (cur.get("suites") or {}).items():
        now_s = res.get("score")
        prev_s = ((prev.get("suites") or {}).get(suite) or {}).get("score")
        gate = "" if res.get("hard_gate_passed", True) else " HARD GATE FAILED"
        out[suite] = f"{now_s} (prev {prev_s})" + gate if now_s is not None else "n/a"
    return out


def _publish_report(markdown: str) -> str | None:
    import os
    from pathlib import Path
    from career_history import config
    cfg = config.get().get("reports") or {}
    out_dir = os.environ.get("ERA_REPORT_DIR") or cfg.get("weekly_dir") or "~/Library/Application Support/era/reports"
    path = Path(os.path.expanduser(out_dir)) / f"CAREER_WEEKLY_{datetime.now():%Y-%m-%d}.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
    except OSError as e:
        console.log(f"[yellow]weekly report not written to {path}:[/yellow] {e}")
        return None
    if cfg.get("publish_to_vault"):
        roots = [r for r in config.get_source_directories() if os.path.isdir(r)]
        if roots:
            vault_path = Path(roots[0]) / (cfg.get("vault_subdir") or "Z. AI_Notebook/Weekly") / path.name
            try:
                vault_path.parent.mkdir(parents=True, exist_ok=True)
                vault_path.write_text(markdown, encoding="utf-8")
            except OSError as e:
                console.log(f"[yellow]weekly report not published to vault:[/yellow] {e}")
    return str(path)

