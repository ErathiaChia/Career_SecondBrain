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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--questions", type=Path, default=None)
    ap.add_argument("--base-url", default=None, help="Overrides base_url in the questions file.")
    ap.add_argument("--suite", choices=["retrieval", "project"], default="retrieval")
    ap.add_argument("--endpoint", choices=["search", "ask"], default="ask")
    ap.add_argument("--top-k", type=int, default=20)
    args = ap.parse_args()

    if args.questions is None:
        args.questions = _DEFAULT_PROJECT if args.suite == "project" else _DEFAULT_QUESTIONS
    if args.suite == "project":
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
