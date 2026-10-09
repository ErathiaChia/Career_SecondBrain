#!/usr/bin/env python3
"""Retrieval scorecard — measure whether the right document comes back, and where.

This is the measurement harness for the V3 retrieval work. You list real
questions and, for each, the path fragment(s) of the document that *should* be
retrieved. The script hits a running era_mcp server, finds the rank at which an
expected document first appears, and reports hit@k and MRR so you can compare a
change against a baseline ("CL89: rank 30 -> rank 1").

Run the server first (see era_mcp/README.md), then:

    python -m tools.scorecard                     # uses tools/scorecard_questions.json
    python -m tools.scorecard --endpoint search   # pure retrieval, no LLM needed
    python -m tools.scorecard --endpoint ask       # full /ask pipeline (needs the Mac LLM)
    python -m tools.scorecard --questions my.json --base-url http://${NAS_HOST}:8808

Dependencies: httpx only (already an era_mcp dependency). Questions are JSON so
no extra YAML dependency is needed.

Project-intelligence benchmark (``--suite project``): a gold file of checks per
project (see scorecard_project.example.json) scored against the /projects/*
endpoints:

    python -m tools.scorecard --suite project --questions tools/scorecard_project.json

Check types: ``project_fields`` (client/type/status accuracy), ``entities``
(recall of expected people/clients/tech), ``facts`` (recall of expected typed
facts), ``conflicts`` (known contradictions found), ``latest_version`` (the
right file is marked latest), ``stale`` (known-outdated facts flagged),
``state`` (a state field's value) and ``attribution`` (share of brief lines that
cite a source). Each check scores 0..1; the report averages per type.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import httpx

_DEFAULT_QUESTIONS = Path(__file__).with_name("scorecard_questions.json")
_DEFAULT_PROJECT = Path(__file__).with_name("scorecard_project.json")


def _result_paths(item: dict[str, Any]) -> str:
    """All path-ish text for one result row, lowercased, for substring matching.
    Covers both chunk rows (file_path/file_name/folder) and structural folder rows
    (name/path)."""
    return " ".join(
        str(item.get(k) or "")
        for k in ("file_path", "file_name", "folder", "name", "path")
    ).lower()


def _rank_of_expected(results: list[dict[str, Any]], expects: list[str]) -> int | None:
    """1-based rank of the first result matching ANY expected fragment, else None."""
    needles = [e.lower() for e in expects if e.strip()]
    if not needles:
        return None
    for i, item in enumerate(results, start=1):
        hay = _result_paths(item)
        if any(n in hay for n in needles):
            return i
    return None


def _fetch(client: httpx.Client, base_url: str, endpoint: str, query: str,
           top_k: int) -> list[dict[str, Any]]:
    if endpoint == "search":
        resp = client.post(f"{base_url}/search", json={"query": query, "top_k": top_k})
        resp.raise_for_status()
        return resp.json().get("results", [])
    # /ask: skip synthesis (we only score retrieval), keep rerank + multi-query.
    resp = client.post(
        f"{base_url}/ask",
        json={"query": query, "synthesize": False, "adaptive_k": False, "top_k": top_k},
    )
    resp.raise_for_status()
    data = resp.json()
    # Semantic answers carry `chunks`; structural (census) answers carry the
    # folder list under `structural.folders` — score whichever is present.
    return data.get("chunks") or (data.get("structural") or {}).get("folders") or []


# --- Project-intelligence suite -------------------------------------------------

Fetch = Callable[[str, dict[str, Any]], Any]


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def _contains_all(hay: str, needles: list[str]) -> bool:
    return all(_norm(n) in hay for n in needles if str(n).strip())


def _recall(found_texts: list[str], expected: list[Any]) -> tuple[float, list[str]]:
    """Share of expected items present. An item is a string, or a list of strings
    that must all appear in the same found text."""
    hays = [_norm(t) for t in found_texts]
    missing = []
    for item in expected:
        needles = item if isinstance(item, list) else [item]
        if not any(_contains_all(h, needles) for h in hays):
            missing.append(" + ".join(map(str, needles)))
    return ((len(expected) - len(missing)) / len(expected) if expected else 1.0), missing


def score_check(check: dict[str, Any], fetch: Fetch) -> dict[str, Any]:
    """Score one gold check against the API. Returns {type, score, detail}."""
    kind = check["type"]
    project = quote(str(check.get("project", "")), safe="")
    base = f"/projects/{project}"

    if kind == "project_fields":
        p = fetch(base, {})
        expected = check["expect"]
        wrong = [f"{k}: got {p.get(k)!r}" for k, v in expected.items() if _norm(v) not in _norm(p.get(k))]
        return {"score": (len(expected) - len(wrong)) / len(expected), "detail": wrong}
    if kind == "entities":
        rows = fetch(f"{base}/entities", {"limit": 200})["entities"]
        texts = [f"{e['canonical_name']} {' '.join(e.get('aliases') or [])}" for e in rows]
        score, missing = _recall(texts, check["expect"])
        return {"score": score, "detail": missing}
    if kind == "facts":
        params: dict[str, Any] = {"limit": 300}
        if check.get("kind"):
            params["kind"] = check["kind"]
        rows = fetch(f"{base}/facts", params)["facts"]
        score, missing = _recall([f"{r['statement']} {r.get('source_quote') or ''}" for r in rows],
                                 check["expect"])
        return {"score": score, "detail": missing}
    if kind == "conflicts":
        rows = fetch(f"{base}/conflicts", {"include_resolved": True, "limit": 300})["conflicts"]
        score, missing = _recall([f"{r['fact_a']} {r['fact_b']} {r.get('explanation') or ''}" for r in rows],
                                 check["expect"])
        return {"score": score, "detail": missing + [f"{len(rows)} conflict(s) flagged in total"]}
    if kind == "latest_version":
        families = fetch(f"{base}/documents", {"group": "version"})["families"]
        fam = next((f for f in families if _norm(check["family_contains"]) in
                    _norm(f"{f['family_key']} {' '.join(v['file_name'] for v in f['versions'])}")), None)
        if fam is None:
            return {"score": 0.0, "detail": [f"no family matching {check['family_contains']!r}"]}
        ok = _norm(check["expect_latest_contains"]) in _norm(fam["latest"])
        return {"score": 1.0 if ok else 0.0, "detail": [] if ok else [f"latest is {fam['latest']!r}"]}
    if kind == "stale":
        rows = fetch(f"{base}/stale", {"limit": 500})["stale"]
        score, missing = _recall([r["statement"] for r in rows], check["expect"])
        return {"score": score, "detail": missing}
    if kind == "state":
        data = fetch(f"{base}/state", {})
        field = ((data.get("state") or {}).get(check["field"]) or {})
        value = field.get("value")
        text = " ".join(map(str, value)) if isinstance(value, list) else str(value)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            text = " ".join(v.get("statement", "") for v in value)
        ok = _norm(check["expect_contains"]) in _norm(text)
        return {"score": 1.0 if ok else 0.0,
                "detail": [] if ok else [f"{check['field']} = {text[:120]!r}"]}
    if kind == "attribution":
        md = fetch(f"{base}/brief", {})["markdown"]
        bullets = [l for l in md.splitlines() if l.lstrip().startswith("- ")]
        cited = [l for l in bullets if "[F" in l]
        score = len(cited) / len(bullets) if bullets else 0.0
        return {"score": score, "detail": [f"{len(cited)}/{len(bullets)} brief lines cite a source"]}
    return {"score": 0.0, "detail": [f"unknown check type {kind!r}"]}


def summarize_project_suite(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, list[float]] = {}
    for r in results:
        by_type.setdefault(r["type"], []).append(r["score"])
    per_type = {t: round(sum(s) / len(s), 3) for t, s in by_type.items()}
    overall = round(sum(per_type.values()) / len(per_type), 3) if per_type else 0.0
    return {"per_type": per_type, "overall": overall, "checks": len(results)}


def run_project_suite(spec: dict[str, Any], base_url: str) -> int:
    checks = spec.get("checks", [])
    if not checks:
        print("No checks in file.", file=sys.stderr)
        return 2
    print(f"Project-intelligence scorecard: {len(checks)} checks -> {base_url}\n")
    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=180.0) as client:
        def fetch(path: str, params: dict[str, Any]) -> Any:
            resp = client.get(f"{base_url}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

        for check in checks:
            try:
                r = score_check(check, fetch)
            except Exception as e:  # noqa: BLE001 - report, don't crash the run
                r = {"score": 0.0, "detail": [f"ERROR: {e}"]}
            r.update({"type": check["type"], "id": check.get("id") or check["type"]})
            results.append(r)
            flag = "ok " if r["score"] >= 0.999 else ".. " if r["score"] > 0 else "!! "
            detail = "; ".join(r["detail"])[:110]
            print(f"  {flag}{r['id'][:40]:<40} {r['score']:.2f}  {detail}")
    summary = summarize_project_suite(results)
    print("\nSummary (mean score per check type)")
    for t, s in sorted(summary["per_type"].items()):
        print(f"  {t:<16} {s:.3f}")
    print(f"  {'overall':<16} {summary['overall']:.3f}")
    return 0


# --- Career / agent / freshness suites (brief §12, §23) ------------------------------

import re as _re
import statistics as _stats
import time as _time

_CITE_RE = _re.compile(r"\[(F\d+|\d+)(?:\s*,[^\]]*)?\]")
_FACT_LINE_RE = _re.compile(r"(?:^|\n|[-*•]\s*|\.\s+)\**\s*FACT\s*\**\s*:\s*\**\s*(.+?)(?=\n|$)")


def _ask(client: httpx.Client, base_url: str, query: str, mode: str = "auto", project: str | None = None) -> tuple[dict[str, Any], float]:
    t0 = _time.monotonic()
    body: dict[str, Any] = {"query": query, "mode": mode}
    if project:
        body["project"] = project
    resp = client.post(f"{base_url}/ask", json=body)
    elapsed = _time.monotonic() - t0
    if resp.status_code == 503:
        return {"error": "llm_unavailable", "detail": resp.json().get("detail")}, elapsed
    resp.raise_for_status()
    return resp.json(), elapsed


def traceability(resp: dict[str, Any]) -> tuple[float, list[str]]:
    """1.0 when every FACT line carries a citation AND every cited label resolves
    to a citation row with a file. Pure."""
    answer = resp.get("answer") or ""
    problems: list[str] = []
    facts = _FACT_LINE_RE.findall(answer)
    uncited = [f for f in facts if not _CITE_RE.search(f)]
    problems += [f"uncited FACT: {f[:60]}" for f in uncited]
    labels = {f"[{m}]" for m in _CITE_RE.findall(answer)}
    known = {c.get("label") for c in (resp.get("citations") or [])}
    known |= {f"[{c.get('n')}]" for c in (resp.get("citations") or []) if c.get("n") is not None}
    known |= {f"[F{c.get('fact_id')}]" for c in (resp.get("citations") or []) if c.get("fact_id")}
    dangling = [l for l in labels if l not in known]
    problems += [f"dangling citation {l}" for l in dangling]
    no_file = [c.get("label") for c in (resp.get("citations") or []) if not (c.get("file_id") or c.get("file_name")) and c.get("kind") not in ("project", "role")]
    problems += [f"citation without file: {l}" for l in no_file]
    if not facts and not labels:
        return (1.0 if not answer else 0.0), problems + (["no FACT lines / citations in answer"] if answer else [])
    return (1.0 if not problems else 0.0), problems


def boundedness(resp: dict[str, Any], max_iterations: int = 3, max_tool_calls: int = 9,
                max_elapsed_s: float | None = None) -> tuple[float, list[str]]:
    problems = []
    if (resp.get("iterations") or 0) > max_iterations:
        problems.append(f"iterations {resp.get('iterations')} > {max_iterations}")
    if (resp.get("tool_calls") or 0) > max_tool_calls:
        problems.append(f"tool_calls {resp.get('tool_calls')} > {max_tool_calls}")
    b = resp.get("budget") or {}
    if (b.get("documents_used") or 0) > (b.get("max_documents") or 10):
        problems.append("documents over cap")
    if max_elapsed_s and (b.get("elapsed_s") or 0) > max_elapsed_s:
        problems.append(f"elapsed {b.get('elapsed_s')} > {max_elapsed_s}")
    if b.get("stop_reason") == "time_budget" and not resp.get("answer"):
        problems.append("time budget exhausted without an answer")
    return (1.0 if not problems else 0.0), problems


def local_first(resp: dict[str, Any]) -> tuple[float, list[str]]:
    fb = str(((resp.get("provider") or {}).get("fallback")) or "")
    ok = fb.startswith("disabled")
    return (1.0 if ok else 0.0), ([] if ok else [f"provider.fallback = {fb!r}"])


def score_career_question(q: dict[str, Any], resp: dict[str, Any], elapsed_s: float) -> dict[str, Any]:
    """Pure: metrics for one career question (0..1 each)."""
    if resp.get("error"):
        return {"id": q.get("id"), "error": resp["error"], "project_hit": 0.0, "fact_recall": 0.0, "evidence": 0.0,
                "traceability": 0.0, "boundedness": 0.0, "elapsed_s": round(elapsed_s, 1)}
    cits = resp.get("citations") or []
    hay_cits = " ".join(_norm(f"{c.get('file_name')} {c.get('file_path')} {c.get('folder')}") for c in cits)
    tools = set(resp.get("tools_used") or [])
    proj = resp.get("project") or {}
    hay_proj = _norm(f"{proj.get('name')} {proj.get('project_key')} {resp.get('answer')} {hay_cits}")
    expect_projects = q.get("expect_projects") or []
    project_hit = (sum(1 for p in expect_projects if _norm(p) in hay_proj) / len(expect_projects)) if expect_projects else 1.0
    exp_paths = q.get("expect_path_contains") or []
    path_hit = 1.0 if not exp_paths else (1.0 if any(_norm(f) in hay_cits for f in exp_paths) else 0.0)
    texts = [str(resp.get("answer") or "")] + [str(c.get("text") or "") for c in (resp.get("sources") or [])]
    fact_recall, missing = _recall(texts, q.get("expect_fact_contains") or [])
    min_c = int(q.get("min_citations") or 1)
    evidence = min(1.0, len(cits) / min_c) if min_c else 1.0
    tools_ok = 1.0 if not q.get("expect_tools_any") else (1.0 if tools & set(q["expect_tools_any"]) else 0.0)
    trace, trace_problems = traceability(resp)
    bound, bound_problems = boundedness(resp, int(q.get("max_iterations") or 3), int(q.get("max_tool_calls") or 9),
                                        q.get("max_elapsed_s"))
    return {"id": q.get("id"), "project_hit": round(project_hit, 3), "path_hit": path_hit,
            "fact_recall": round(fact_recall, 3), "evidence": round(evidence, 3), "tools_ok": tools_ok,
            "traceability": trace, "boundedness": bound, "sufficient": bool(resp.get("sufficient")),
            "route": resp.get("route"), "elapsed_s": round(elapsed_s, 1), "llm_calls": resp.get("llm_calls"),
            "detail": (missing + trace_problems + bound_problems)[:6]}


def summarize_career(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"score": None, "metrics": {}, "questions": 0}
    keys = ("project_hit", "path_hit", "fact_recall", "evidence", "tools_ok", "traceability", "boundedness")
    metrics = {k: round(sum(float(r.get(k) or 0) for r in rows) / len(rows), 3) for k in keys}
    metrics["sufficient_share"] = round(sum(1 for r in rows if r.get("sufficient")) / len(rows), 3)
    metrics["elapsed_p50_s"] = round(_stats.median([r.get("elapsed_s") or 0 for r in rows]), 1)
    score = round(sum(metrics[k] for k in ("project_hit", "fact_recall", "evidence", "tools_ok")) / 4, 3)
    return {"score": score, "metrics": metrics, "questions": len(rows)}


def score_agent_question(q: dict[str, Any], resp: dict[str, Any], elapsed_s: float) -> dict[str, Any]:
    kind = q.get("kind") or "fast"
    out: dict[str, Any] = {"id": q.get("id"), "kind": kind, "elapsed_s": round(elapsed_s, 1),
                           "route": resp.get("route"), "llm_calls": resp.get("llm_calls"),
                           "iterations": resp.get("iterations"), "tool_calls": resp.get("tool_calls")}
    if resp.get("error"):
        out.update(error=resp["error"], ok=0.0, boundedness=0.0, local_first=0.0)
        return out
    bound, bp = boundedness(resp, 3, 9, q.get("max_elapsed_s"))
    lf, lp = local_first(resp)
    problems = bp + lp
    if kind == "fast":
        ok = resp.get("route") == (q.get("expect_route") or "fast") and (resp.get("llm_calls") or 0) <= 2 and bool(resp.get("answer"))
        if not ok:
            problems.append(f"route {resp.get('route')} / llm_calls {resp.get('llm_calls')} / answer {bool(resp.get('answer'))}")
    elif kind == "investigate":
        tools = set(resp.get("tools_used") or [])
        ok = resp.get("route") == "investigate" and (not q.get("expect_tools_any") or bool(tools & set(q["expect_tools_any"])))
        if not ok:
            problems.append(f"route {resp.get('route')} tools {sorted(tools)}")
    elif kind == "digest":
        ok = resp.get("route") == "digest" and (resp.get("llm_calls") or 0) == 0
        if not ok:
            problems.append(f"route {resp.get('route')} llm_calls {resp.get('llm_calls')}")
    else:  # insufficient
        ok = resp.get("sufficient") is False and bool(resp.get("gaps"))
        if not ok:
            problems.append(f"sufficient {resp.get('sufficient')} gaps {bool(resp.get('gaps'))}")
    out.update(ok=1.0 if ok else 0.0, boundedness=bound, local_first=lf, detail=problems[:5])
    return out


def summarize_agent(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"score": None, "metrics": {}, "questions": 0}
    fast = [r for r in rows if r.get("kind") == "fast"]
    metrics = {
        "ok": round(sum(r.get("ok") or 0 for r in rows) / len(rows), 3),
        "boundedness": round(sum(r.get("boundedness") or 0 for r in rows) / len(rows), 3),
        "local_first": round(sum(r.get("local_first") or 0 for r in rows) / len(rows), 3),
        "fast_p50_s": round(_stats.median([r.get("elapsed_s") or 0 for r in fast]), 1) if fast else None,
        "fast_llm_calls_max": max((r.get("llm_calls") or 0 for r in fast), default=None),
    }
    return {"score": metrics["ok"], "metrics": metrics, "questions": len(rows)}


def score_freshness(results: list[dict[str, Any]], run_id: str | None, probe_fragment: str) -> dict[str, Any]:
    rank = _rank_of_expected(results, [probe_fragment]) if run_id else None
    return {"score": 1.0 if rank else 0.0, "metrics": {"pass": 1.0 if rank else 0.0, "rank": rank},
            "questions": 1, "detail": [] if rank else [f"probe {probe_fragment!r} not in top results for run {run_id!r}"]}


def apply_thresholds(suite: str, summary: dict[str, Any], thresholds: dict[str, Any] | None) -> dict[str, Any]:
    """Attach pass/fail per threshold and the hard-gate verdict (pure)."""
    th = (thresholds or {}).get(suite) or {}
    hard = set(th.get("hard") or [])
    metrics = dict(summary.get("metrics") or {})
    if "overall" in th and summary.get("score") is not None:
        metrics.setdefault("overall", summary["score"])
    checks: dict[str, bool] = {}
    for key, limit in th.items():
        if key == "hard" or key not in metrics or metrics[key] is None:
            continue
        val = float(metrics[key])
        checks[key] = (val <= limit) if key.endswith(("_s", "_max")) else (val >= limit)
    summary["thresholds"] = checks
    summary["hard_gate_passed"] = all(checks.get(k, True) for k in hard)
    return summary


def run_suites(suites: list[str], sets_dir: Path, base_url: str, thresholds: dict[str, Any] | None,
               run_id: str | None, top_k: int = 20) -> dict[str, Any]:
    out: dict[str, Any] = {"generated": _time.strftime("%Y-%m-%dT%H:%M:%S"), "base_url": base_url, "run_id": run_id,
                           "suites": {}}
    with httpx.Client(timeout=240.0) as client:
        for suite in suites:
            spec_path = sets_dir / f"{suite}.json"
            if not spec_path.exists():
                out["suites"][suite] = {"score": None, "skipped": f"{spec_path} missing"}
                continue
            spec = json.loads(spec_path.read_text())
            rows: list[dict[str, Any]] = []
            if suite == "retrieval":
                ranks = []
                for q in spec.get("questions", []):
                    try:
                        res = _fetch(client, base_url, "ask", q["query"], top_k)
                        rank = _rank_of_expected(res, q.get("expect_path_contains", []))
                    except Exception as e:  # noqa: BLE001
                        rank = None
                        rows.append({"id": q.get("id"), "error": str(e)[:120]})
                    ranks.append(rank)
                    rows.append({"id": q.get("id"), "rank": rank})
                n = len(ranks) or 1
                found = [r for r in ranks if r]
                summary = {"score": round(sum(1 for r in found if r <= 5) / n, 3),
                           "metrics": {"hit_at_5": round(sum(1 for r in found if r <= 5) / n, 3),
                                       "hit_at_10": round(sum(1 for r in found if r <= 10) / n, 3),
                                       "mrr": round(sum(1.0 / r for r in found) / n, 3)}, "questions": len(ranks)}
            elif suite == "project":
                def fetch(path: str, params: dict[str, Any]) -> Any:
                    resp = client.get(f"{base_url}{path}", params=params)
                    resp.raise_for_status()
                    return resp.json()
                for check in spec.get("checks", []):
                    try:
                        r = score_check(check, fetch)
                    except Exception as e:  # noqa: BLE001
                        r = {"score": 0.0, "detail": [f"ERROR: {e}"]}
                    rows.append({**r, "type": check["type"], "id": check.get("id") or check["type"]})
                ps = summarize_project_suite(rows)
                summary = {"score": ps["overall"], "metrics": {**ps["per_type"], "overall": ps["overall"]}, "questions": ps["checks"]}
            elif suite == "career":
                for q in spec.get("questions", []):
                    try:
                        resp, el = _ask(client, base_url, q["query"], q.get("mode", "auto"), q.get("project"))
                    except Exception as e:  # noqa: BLE001
                        resp, el = {"error": str(e)[:120]}, 0.0
                    rows.append(score_career_question(q, resp, el))
                summary = summarize_career(rows)
            elif suite == "agent":
                for q in spec.get("questions", []):
                    try:
                        resp, el = _ask(client, base_url, q["query"], q.get("mode", "auto"), q.get("project"))
                    except Exception as e:  # noqa: BLE001
                        resp, el = {"error": str(e)[:120]}, 0.0
                    rows.append(score_agent_question(q, resp, el))
                summary = summarize_agent(rows)
            elif suite == "freshness":
                frag = spec.get("probe_path_contains") or "freshness_probe"
                try:
                    res = _fetch(client, base_url, "search", run_id or "freshness probe", 10) if run_id else []
                except Exception as e:  # noqa: BLE001
                    res = []
                    rows.append({"error": str(e)[:120]})
                summary = score_freshness(res, run_id, frag)
            else:
                summary = {"score": None, "skipped": f"unknown suite {suite}"}
            summary["rows"] = rows
            out["suites"][suite] = apply_thresholds(suite, summary, thresholds)
    out["hard_gates_passed"] = all(s.get("hard_gate_passed", True) for s in out["suites"].values())
    return out


def _print_suites(out: dict[str, Any], baseline: dict[str, Any] | None) -> None:
    print(f"Scorecard run {out['generated']} -> {out['base_url']}")
    for suite, s in out["suites"].items():
        if s.get("skipped"):
            print(f"  {suite:<10} skipped: {s['skipped']}")
            continue
        prev = ((baseline or {}).get("suites") or {}).get(suite) or {}
        delta = ""
        if prev.get("score") is not None and s.get("score") is not None:
            delta = f" (baseline {prev['score']}, Δ {round(s['score'] - prev['score'], 3):+})"
        gate = "" if s.get("hard_gate_passed", True) else "  <-- HARD GATE FAILED"
        print(f"  {suite:<10} score {s.get('score')}{delta}{gate}")
        for k, v in (s.get("metrics") or {}).items():
            mark = "" if k not in (s.get("thresholds") or {}) else (" ok" if s["thresholds"][k] else " BELOW THRESHOLD")
            print(f"      {k:<18} {v}{mark}")
        for r in s.get("rows", [])[:40]:
            if r.get("detail") or r.get("error"):
                print(f"      - {r.get('id')}: {r.get('error') or '; '.join(r.get('detail') or [])[:100]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--questions", type=Path, default=None, help="(legacy) single question/check file")
    ap.add_argument("--base-url", default=None, help="Overrides base_url in the questions file.")
    ap.add_argument("--suite", default="retrieval",
                    help="retrieval | project | career | agent | freshness | all, or a comma list")
    ap.add_argument("--sets-dir", type=Path, default=None, help="Directory with <suite>.json files (e.g. local/eval)")
    ap.add_argument("--out", type=Path, default=None, help="Write the JSON result here")
    ap.add_argument("--baseline", type=Path, default=None, help="Previous JSON result to show deltas against")
    ap.add_argument("--thresholds", type=Path, default=None, help="eval/thresholds.json")
    ap.add_argument("--run-id", default=None, help="Pipeline run id (freshness probe token)")
    ap.add_argument("--endpoint", choices=["search", "ask"], default="ask")
    ap.add_argument("--top-k", type=int, default=20)
    args = ap.parse_args()

    suites = [s.strip() for s in args.suite.split(",") if s.strip()]
    if suites == ["all"]:
        suites = ["retrieval", "project", "career", "agent", "freshness"]
    multi = args.sets_dir is not None or len(suites) > 1 or suites[0] in ("career", "agent", "freshness")
    if multi:
        sets_dir = args.sets_dir or Path(__file__).parent
        thresholds = json.loads(args.thresholds.read_text()) if args.thresholds and args.thresholds.exists() else None
        base_url = (args.base_url or "http://localhost:8808").rstrip("/")
        out = run_suites(suites, sets_dir, base_url, thresholds, args.run_id, args.top_k)
        baseline = json.loads(args.baseline.read_text()) if args.baseline and args.baseline.exists() else None
        _print_suites(out, baseline)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(out, indent=1, default=str))
            latest = args.out.with_name("latest.json")
            try:
                if latest.exists() or latest.is_symlink():
                    latest.unlink()
                latest.symlink_to(args.out.name)
            except OSError:
                pass
        return 0 if out["hard_gates_passed"] else 1

    # ---- legacy single-suite behaviour (retrieval / project) ----
    if args.questions is None:
        args.questions = _DEFAULT_PROJECT if suites[0] == "project" else _DEFAULT_QUESTIONS
    if suites[0] == "project":
        if not args.questions.exists():
            print(f"Checks file not found: {args.questions}", file=sys.stderr)
            print("Copy scorecard_project.example.json and fill in your own.", file=sys.stderr)
            return 2
        spec = json.loads(args.questions.read_text())
        base_url = (args.base_url or spec.get("base_url") or "http://localhost:8808").rstrip("/")
        return run_project_suite(spec, base_url)

    if not args.questions.exists():
        print(f"Questions file not found: {args.questions}", file=sys.stderr)
        print("Copy scorecard_questions.example.json and fill in your own.", file=sys.stderr)
        return 2

    spec = json.loads(args.questions.read_text())
    base_url = (args.base_url or spec.get("base_url") or "http://localhost:8808").rstrip("/")
    questions = spec.get("questions", [])
    if not questions:
        print("No questions in file.", file=sys.stderr)
        return 2

    print(f"Scorecard: {len(questions)} questions -> {base_url}/{args.endpoint} (top_k={args.top_k})\n")
    ranks: list[int | None] = []
    rows: list[tuple[str, str]] = []
    with httpx.Client(timeout=120.0) as client:
        for q in questions:
            query = q["query"]
            expects = q.get("expect_path_contains", [])
            try:
                results = _fetch(client, base_url, args.endpoint, query, args.top_k)
                rank = _rank_of_expected(results, expects)
            except Exception as e:  # noqa: BLE001 - report, don't crash the run
                rank = None
                rows.append((query, f"ERROR: {e}"))
                ranks.append(None)
                continue
            ranks.append(rank)
            verdict = f"rank {rank}" if rank else f"MISS (in top {len(results)})"
            rows.append((query, verdict))

    width = min(70, max((len(q) for q, _ in rows), default=10))
    for query, verdict in rows:
        flag = "ok " if verdict.startswith("rank") else "!! "
        print(f"  {flag}{query[:width]:<{width}}  {verdict}")

    found = [r for r in ranks if r is not None]
    n = len(ranks)
    hit5 = sum(1 for r in found if r <= 5)
    hit10 = sum(1 for r in found if r <= 10)
    mrr = sum(1.0 / r for r in found) / n if n else 0.0
    print("\nSummary")
    print(f"  hit@5:  {hit5}/{n}")
    print(f"  hit@10: {hit10}/{n}")
    print(f"  MRR:    {mrr:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
