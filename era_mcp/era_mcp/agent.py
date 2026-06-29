"""Agentic /ask: router + bounded ReAct Judge loop.

Turns /ask from a single pass into an intelligent agent:

  question
    -> route (rules + complexity)
       - STRUCTURAL ("how many / list all folders/projects") -> live inventory
       - SEMANTIC -> first retrieval pass -> confidence gate
            >= threshold -> answer (single pass)
            <  threshold -> bounded ReAct Judge loop (<= AGENT_MAX_ITERS):
                 the Judge carries a trajectory (memory), drives re-search /
                 re-write / re-route, and the controller enforces the limits.
    -> synthesize (with the investigation trajectory) -> structured JSON

The Judge runs on the Mac (`LLM_JUDGE_MODEL`, e.g. gemma4:31b-mlx). Everything
degrades gracefully: any LLM failure falls back to returning reranked chunks.
Scope: era_mcp only — never touches the auditor. See docs/agentic_mcp_design.md.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from era_mcp import config, llm, query_understanding, rerank, retrieval, structural

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str, fallback: str) -> str:
    try:
        return (_PROMPTS / name).read_text(encoding="utf-8").strip()
    except OSError:
        return fallback


_JUDGE_SYS = _load_prompt(
    "judge_agent.md",
    "You are a retrieval Judge. Given the question, folder overview, trajectory, "
    "and candidate summaries, return ONLY JSON: {thought, action "
    "(research|structural|answer), sufficient, missing, reformulations, query, "
    "confidence}.",
)
_SYNTH_SYS = _load_prompt(
    "synthesis.md",
    "Answer ONLY from the numbered SOURCES, citing claims inline as [n]. If "
    "incomplete or the search budget ran out, say plainly it is a best-effort "
    "partial answer and name what is missing. Never fabricate.",
)

# Cheap structural router: census / enumeration questions go to the inventory,
# not semantic search. The Judge can also re-route to structural mid-loop.
_STRUCTURAL_RE = re.compile(
    r"\b(how many|list (all|the)|all (the )?(projects?|folders?)|"
    r"what(?:'s| is) (in|under)|folder structure|which folders?|enumerate)\b",
    re.IGNORECASE,
)


def route(question: str, understanding: dict[str, Any]) -> str:
    """'structural' for census/enumeration questions, else 'semantic'."""
    if _STRUCTURAL_RE.search(question or ""):
        return "structural"
    return "semantic"


def _score(r: dict[str, Any]) -> float:
    rs = r.get("rerank_score")
    return rs if rs is not None else (r.get("rrf_score") or 0.0)


def _confidence(results: list[dict[str, Any]]) -> float:
    """Normalized (0-1) top relevance, used by the gate. Reranker scales differ:
    llm_score is 0-10, infinity ~0-1; normalize so the threshold is backend-agnostic."""
    if not results:
        return 0.0
    scores = [r["rerank_score"] for r in results if r.get("rerank_score") is not None]
    if not scores:
        sims = [r.get("similarity") or 0.0 for r in results]
        return max(sims) if sims else 0.0
    top = max(scores)
    if config.rerank_kind() == "llm_score":
        top = top / 10.0
    return max(0.0, min(1.0, top))


def _key(r: dict[str, Any]) -> tuple:
    return (r.get("file_path"), r.get("matched_chunk_index"), r.get("parent_chunk_id"))


def _merge(pool: dict[tuple, dict[str, Any]], results: list[dict[str, Any]]) -> int:
    """Merge results into the pool (best score wins). Returns count of NEW keys."""
    added = 0
    for r in results:
        k = _key(r)
        if k not in pool:
            pool[k] = r
            added += 1
        elif _score(r) > _score(pool[k]):
            pool[k] = r
    return added


def _ranked(pool: dict[tuple, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(pool.values(), key=_score, reverse=True)[:limit]


def _summarize(results: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """Compact candidate summaries for the Judge — never full chunks."""
    out = []
    for i, r in enumerate(results[:limit], start=1):
        snippet = (r.get("content") or "").replace("\n", " ").strip()[:200]
        out.append({
            "n": i,
            "file_name": r.get("file_name"),
            "folder": r.get("folder"),
            "rerank_score": r.get("rerank_score"),
            "snippet": snippet,
        })
    return out


async def _retrieve(query_texts: list[str], req: Any, top_k: int) -> list[dict[str, Any]]:
    """Embed each query (instruction applied in embed_query) and run multi-query
    fused retrieval + a single rerank against the user's original question."""
    seen: set[str] = set()
    texts = [q for q in query_texts if q and not (q in seen or seen.add(q))]
    if not texts:
        return []
    embeddings = await asyncio.gather(*[retrieval.embed_query(t) for t in texts])
    pairs = list(zip(texts, embeddings))
    return await retrieval.multi_search_async(
        queries=pairs,
        rerank_query=req.query,
        top_k=top_k,
        folder=req.folder,
        rerank_enabled=req.rerank,
    )


def _normalize_verdict(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    action = str(data.get("action", "")).strip().lower()
    if action not in ("research", "structural", "answer"):
        action = "answer"
    refs = data.get("reformulations") or []
    refs = ([str(x).strip() for x in refs if str(x).strip()][:3]
            if isinstance(refs, list) else [])
    conf = data.get("confidence", 0.0)
    return {
        "thought": str(data.get("thought", "")).strip(),
        "action": action,
        "sufficient": bool(data.get("sufficient", False)),
        "missing": str(data.get("missing", "")).strip(),
        "reformulations": refs,
        "query": str(data.get("query", "")).strip(),
        "confidence": float(conf) if isinstance(conf, (int, float)) else 0.0,
    }


def _judge_user_msg(question: str, folder_ov: str, trajectory: list[dict],
                    candidates: list[dict], remaining: int) -> str:
    parts = [f"QUESTION: {question}", "", f"SEARCHES REMAINING: {remaining}"]
    if remaining <= 1:
        parts.append("This is your LAST search — choose action=answer unless a "
                     "structural lookup is clearly needed.")
    parts += ["", "FOLDER OVERVIEW:", folder_ov or "(unavailable)", ""]
    if trajectory:
        parts.append("TRAJECTORY SO FAR:")
        parts += [json.dumps(s, ensure_ascii=False) for s in trajectory]
        parts.append("")
    parts += ["CANDIDATES:", json.dumps(candidates, ensure_ascii=False), "",
              "Respond with ONLY the JSON object."]
    return "\n".join(parts)


async def _judge(question: str, folder_ov: str, trajectory: list[dict],
                 results: list[dict], remaining: int) -> dict[str, Any]:
    data = await llm.chat_json(
        [{"role": "system", "content": _JUDGE_SYS},
         {"role": "user", "content": _judge_user_msg(
             question, folder_ov, trajectory, _summarize(results), remaining)}],
        timeout=config.llm_primary_timeout(),
        model=config.llm_judge_model(),
    )
    return _normalize_verdict(data)


async def _synthesize(question: str, chunks: list[dict], graph: dict | None,
                      investigation: str) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        content = (c.get("content") or "").strip()[:1500]
        blocks.append(f"[{i}] {c.get('file_name', '?')} (folder: {c.get('folder', '?')}):\n{content}")
    graph_note = ""
    if graph:
        parts: list[str] = []
        ents = ", ".join(e.get("canonical_name", "") for e in (graph.get("entities") or [])[:10]
                         if e.get("canonical_name"))
        if ents:
            parts.append(f"Related entities: {ents}")
        fact_lines = []
        for f in (graph.get("facts") or [])[:8]:
            attrs = f.get("attributes") or {}
            extra = [x for x in (attrs.get("due_at") and f"due {attrs['due_at']}",
                                 attrs.get("status"), attrs.get("counterparty")) if x]
            suffix = f" ({'; '.join(extra)})" if extra else ""
            fact_lines.append(f"- [{f.get('kind')}] {f.get('statement')}{suffix}")
        if fact_lines:
            parts.append("Known facts (decisions/commitments/events):\n" + "\n".join(fact_lines))
        if parts:
            graph_note = "\n\n" + "\n\n".join(parts)
    user = (f"QUESTION: {question}\n\nINVESTIGATION:\n{investigation}\n\n"
            f"SOURCES:\n{chr(10).join(blocks)}{graph_note}")
    return await llm.chat(
        [{"role": "system", "content": _SYNTH_SYS},
         {"role": "user", "content": user}],
        model=config.llm_judge_model(),
    )


def _citations(chunks: list[dict]) -> list[dict]:
    return [
        {
            "n": i,
            "file_name": c.get("file_name"),
            "file_path": c.get("file_path"),
            "folder": c.get("folder"),
            "matched_chunk_index": c.get("matched_chunk_index"),
            "similarity": c.get("similarity"),
            "rerank_score": c.get("rerank_score"),
        }
        for i, c in enumerate(chunks, start=1)
    ]


def _base_response(req: Any, understanding: dict, effective_top_k: int) -> dict:
    return {
        "query": req.query,
        "rewritten_query": (understanding["search_query"]
                            if understanding["search_query"] != req.query else None),
        "sub_queries": understanding.get("sub_queries", []),
        "complexity": understanding.get("complexity", "moderate"),
        "effective_top_k": effective_top_k,
        "provider": llm.provider_status(),
        "rerank_backend": rerank.status() if req.rerank else None,
    }


def _structural_answer(inv: dict) -> str:
    folders = inv.get("folders", [])
    lines = [f"Found {inv.get('count', 0)} folder(s) under {inv.get('scope', '?')}:"]
    for f in folders:
        lines.append(f"- {f['name']} ({f.get('file_count', 0)} files)")
    return "\n".join(lines)


async def run_agentic_ask(req: Any) -> dict:
    """Full agentic /ask. Returns the structured response for Open WebUI."""
    from fastapi.concurrency import run_in_threadpool

    t0 = time.monotonic()
    budget = config.agent_time_budget()
    max_iters = max(1, config.agent_max_iters())

    # 1) Query understanding (degrade-safe: identity on any failure).
    understanding = (
        await query_understanding.rewrite_query(req.query)
        if req.rewrite else query_understanding.identity(req.query)
    )
    search_query = understanding["search_query"]
    complexity = understanding.get("complexity", "moderate")
    effective_top_k = (config.topk_for_complexity(complexity)
                       if (req.adaptive_k and config.adaptive_topk_enabled())
                       else req.top_k)
    sub_queries = (understanding.get("sub_queries", [])
                   if config.multi_query_enabled() else [])
    base = _base_response(req, understanding, effective_top_k)

    # Live folder overview for the Judge (best-effort; never blocks the answer).
    try:
        folder_ov = await run_in_threadpool(structural.folder_overview)
    except Exception:
        folder_ov = ""

    # 2) Route.
    if route(req.query, understanding) == "structural":
        try:
            inv = await run_in_threadpool(structural.project_inventory, req.query, None)
            return {**base, "route": "structural", "answer": _structural_answer(inv),
                    "structural": inv, "citations": [], "chunks": [], "graph": None,
                    "sufficient": True, "confidence": 1.0, "gaps": "",
                    "iterations": 0, "queries_tried": [], "max_iters_reached": False,
                    "trajectory": [], "degraded": False, "degraded_reason": None,
                    "reranked": False}
        except Exception as e:  # noqa: BLE001 — fall through to semantic on any failure
            base["degraded_reason"] = f"structural_error: {e}"

    # 3) Semantic first pass.
    pool: dict[tuple, dict] = {}
    trajectory: list[dict] = []
    queries_tried: list[str] = []
    first_qs = [search_query] + list(sub_queries)
    try:
        _merge(pool, await _retrieve(first_qs, req, effective_top_k))
    except llm.LLMUnavailable:
        pass  # embedding is not LLM; but keep symmetric guard
    except Exception:
        pass
    queries_tried += first_qs

    confidence = _confidence(_ranked(pool, effective_top_k))
    threshold = config.strong_rerank_threshold()
    sufficient = confidence >= threshold
    max_iters_reached = False
    last_missing = ""

    # 4) Judge loop only when the first pass is not confident.
    if not sufficient:
        for i in range(max_iters):
            remaining = max_iters - i
            if time.monotonic() - t0 > budget:
                max_iters_reached = True
                break
            try:
                verdict = await _judge(req.query, folder_ov, trajectory,
                                       _ranked(pool, effective_top_k), remaining)
            except (llm.LLMUnavailable, ValueError):
                break  # judge unavailable → answer with what we have
            step = {"thought": verdict["thought"], "action": verdict["action"],
                    "queries": [], "observation": ""}
            last_missing = verdict["missing"] or last_missing

            if verdict["action"] == "answer":
                sufficient = verdict["sufficient"] or sufficient
                trajectory.append(step)
                break

            if verdict["action"] == "structural":
                trajectory.append(step)
                try:
                    inv = await run_in_threadpool(
                        structural.project_inventory, verdict["query"] or req.query, None)
                    return {**base, "route": "structural",
                            "answer": _structural_answer(inv), "structural": inv,
                            "citations": [], "chunks": [], "graph": None,
                            "sufficient": True, "confidence": 1.0, "gaps": "",
                            "iterations": i + 1, "queries_tried": queries_tried,
                            "max_iters_reached": False, "trajectory": trajectory,
                            "degraded": False, "degraded_reason": None, "reranked": False}
                except Exception:
                    break

            # action == "research": re-write + re-search.
            nxt = [q for q in verdict["reformulations"] if q not in queries_tried]
            step["queries"] = nxt
            if not nxt:
                trajectory.append(step)
                break
            try:
                added = _merge(pool, await _retrieve(nxt, req, effective_top_k))
            except Exception:
                added = 0
            queries_tried += nxt
            step["observation"] = (f"{added} new result(s); "
                                   f"top score {_confidence(_ranked(pool, effective_top_k)):.2f}")
            trajectory.append(step)
            confidence = _confidence(_ranked(pool, effective_top_k))
            if confidence >= threshold:
                sufficient = True
                break
            if added == 0:  # no-new-docs early exit
                break
            if i == max_iters - 1:
                max_iters_reached = True

    chunks = _ranked(pool, effective_top_k)

    # 5) Optional graph augmentation (best-effort).
    graph = None
    if req.use_graph:
        try:
            graph = await run_in_threadpool(retrieval.graph_only, search_query, effective_top_k)
        except Exception:
            graph = None

    # 6) Synthesis (degrade-safe).
    gaps = "" if sufficient else (last_missing or
           "Some aspects may be unanswered; a narrower follow-up or another pass may help.")
    degraded = False
    degraded_reason = base.get("degraded_reason")
    answer = None
    if req.synthesize and chunks:
        budget_note = ("The search budget (max iterations) was reached without a "
                       "fully confident answer. " if max_iters_reached else "")
        investigation = (f"{budget_note}Queries tried: {queries_tried}. "
                         f"Sufficient: {sufficient}. Missing: {gaps or 'nothing notable'}.")
        try:
            answer = await _synthesize(req.query, chunks, graph, investigation)
        except llm.LLMUnavailable as e:
            degraded = True
            degraded_reason = f"llm_unavailable: {e}"
    elif req.synthesize and not chunks:
        degraded = True
        degraded_reason = degraded_reason or "no_results"

    return {
        **base,
        "route": "semantic",
        "answer": answer,
        "citations": _citations(chunks),
        "chunks": chunks,
        "graph": graph,
        "sufficient": sufficient,
        "confidence": round(confidence, 4),
        "gaps": gaps,
        "iterations": len(trajectory),
        "queries_tried": queries_tried,
        "max_iters_reached": max_iters_reached,
        "trajectory": trajectory,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "reranked": bool(req.rerank and chunks and any("rerank_score" in c for c in chunks)),
    }
