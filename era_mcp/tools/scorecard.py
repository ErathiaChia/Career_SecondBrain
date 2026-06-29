#!/usr/bin/env python3
"""Retrieval scorecard — measure whether the right document comes back, and where.

This is the measurement harness for the V3 retrieval work. You list real
questions and, for each, the path fragment(s) of the document that *should* be
retrieved. The script hits a running era_mcp server, finds the rank at which an
expected document first appears, and reports hit@k and MRR so you can compare a
change against a baseline ("IBF: rank 30 -> rank 1").

Run the server first (see era_mcp/README.md), then:

    python -m tools.scorecard                     # uses tools/scorecard_questions.json
    python -m tools.scorecard --endpoint search   # pure retrieval, no LLM needed
    python -m tools.scorecard --endpoint ask       # full /ask pipeline (needs the Mac LLM)
    python -m tools.scorecard --questions my.json --base-url http://192.168.50.50:8808

Dependencies: httpx only (already an era_mcp dependency). Questions are JSON so
no extra YAML dependency is needed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

_DEFAULT_QUESTIONS = Path(__file__).with_name("scorecard_questions.json")


def _result_paths(item: dict[str, Any]) -> str:
    """All path-ish text for one result row, lowercased, for substring matching."""
    return " ".join(
        str(item.get(k) or "")
        for k in ("file_path", "file_name", "folder")
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
    return resp.json().get("chunks", [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--questions", type=Path, default=_DEFAULT_QUESTIONS)
    ap.add_argument("--base-url", default=None, help="Overrides base_url in the questions file.")
    ap.add_argument("--endpoint", choices=["search", "ask"], default="ask")
    ap.add_argument("--top-k", type=int, default=20)
    args = ap.parse_args()

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
