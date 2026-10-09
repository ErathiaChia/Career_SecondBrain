"""The Career Intelligence agent behind /ask (brief §2, §3, §18, §19).

    question
      -> router (mechanical): structural census | weekly digest | retrieval
      -> first pass: cards + hybrid retrieval + rerank -> ContextBuilder
      -> gate (mechanical): fast  -> one synthesis call
                            investigate -> Judge loop:
                                 <= 3 iterations x <= 3 tool calls from the registry
                                 <= 10 documents, <= 20k context tokens, wall-clock budget
                                 stop on answer / no new evidence / budget
      -> synthesis (budgeted) -> structured JSON with citations + trajectory

No cloud fallback: an unreachable local LLM is a 503. The only LLM calls are
the optional query rewrite, one Judge call per iteration, and one synthesis.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from era_mcp import cards as cards_mod
from era_mcp import config, epistemic, judge, llm, projects, query_understanding, rerank, retrieval, router, structural
from era_mcp.agent_tools import registry
from era_mcp.agent_tools.career import _state_text
from era_mcp.agent_tools.sources import from_card, from_chunk, from_fact, from_project
from era_mcp.budget import Budget
from era_mcp.context import ContextBuilder

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_PROMPTS_FROM_FILES: dict[str, bool] = {}
log = logging.getLogger(__name__)


def _load_prompt(name: str, fallback: str) -> str:
    """Prompt text from era_mcp/prompts/<name>, else the short inline fallback.
    Records which one was used so /status can say whether the deployed container
    actually carries the prompt files (the Dockerfile must COPY them)."""
    try:
        text = (_PROMPTS / name).read_text(encoding="utf-8").strip()
        _PROMPTS_FROM_FILES[name] = True
        return text
    except OSError:
        _PROMPTS_FROM_FILES[name] = False
        log.warning("prompt file %s not found under %s; using inline fallback", name, _PROMPTS)
        return fallback


def prompts_loaded_from_files() -> bool:
    status = {**_PROMPTS_FROM_FILES, **judge.prompts_loaded()}
    return bool(status) and all(status.values())


def assert_prompts_loaded() -> None:
    """Build-time check (Dockerfile) that the prompt files are in the image."""
    missing = [n for n in ("judge_agent.md", "synthesis.md", "ai_secondbrain_agent.md") if not (_PROMPTS / n).exists()]
    if missing:
        raise RuntimeError(f"prompt files missing from image: {missing} (expected in {_PROMPTS})")


_SYNTH_SYS = _load_prompt("synthesis.md", (
    "Answer ONLY from the SOURCES. Cite each claim as [n] or [F<id>]. Start claims with FACT: (cited), "
    "INFERENCE: (reasoned from cited facts) or UNKNOWN: (not in the sources). If the INVESTIGATION says "
    "the budget ran out or evidence is missing, say this is a best-effort partial answer and name the gaps. "
    "Prefer the latest document version; show disagreements with both citations. Never fabricate."))


# --- helpers --------------------------------------------------------------------

def _confidence(results: list[dict[str, Any]]) -> float:
    """Normalized (0-1) top relevance of the first pass. Reranker scales differ:
    llm_score is 0-10, infinity ~0-1. Unscored chunks fall back to cosine."""
    if not results:
        return 0.0
    scores = [r["rerank_score"] for r in results if r.get("rerank_score") is not None]
    if not scores:
        sims = [r.get("similarity") or 0.0 for r in results]
        return max(sims) if sims else 0.0
    top = max(scores)
    if config.rerank_kind() == "llm_score":
        top = top / 10.0
    return max(0.0, min(1.0, float(top)))


def _structural_answer(inv: dict) -> str:
    folders = inv.get("folders", [])
    lines = [f"Found {inv.get('count', 0)} folder(s) under {inv.get('scope', '?')}:"]
    for f in folders:
        lines.append(f"- {f['name']} ({f.get('file_count', 0)} files)")
    return "\n".join(lines)


def _legacy_citations(chunks: list[dict]) -> list[dict]:
    return [{"n": i, "file_name": c.get("file_name"), "file_path": c.get("file_path"), "folder": c.get("folder"),
             "matched_chunk_index": c.get("matched_chunk_index"), "similarity": c.get("similarity"),
             "rerank_score": c.get("rerank_score")} for i, c in enumerate(chunks, start=1)]


def _base(req: Any, understanding: dict[str, Any], effective_top_k: int, decision: router.RouteDecision) -> dict[str, Any]:
    return {
        "query": req.query,
        "mode": getattr(req, "mode", "auto"),
        "rewritten_query": (understanding["search_query"] if understanding["search_query"] != req.query else None),
        "sub_queries": understanding.get("sub_queries", []),
        "complexity": understanding.get("complexity", "moderate"),
        "effective_top_k": effective_top_k,
        "route_reasons": decision.reasons,
        "project": ({"id": decision.project.get("id"), "name": decision.project.get("name"),
                     "project_key": decision.project.get("project_key")} if decision.project else None),
        "provider": llm.provider_status(),
        "rerank_backend": rerank.status() if req.rerank else None,
    }


def _empty(base: dict[str, Any], **over: Any) -> dict[str, Any]:
    out = {**base, "route": "retrieval", "answer": None, "epistemic": None, "citations": [], "chunks": [],
           "graph": None, "sufficient": True, "confidence": {"retrieval": 1.0, "cards": None, "judge": None, "final": 1.0},
           "gaps": "", "budget": {"iterations_used": 0, "tool_calls_used": 0, "documents_used": 0, "context_tokens": 0,
                                  "elapsed_s": 0.0, "stop_reason": None},
           "llm_calls": 0, "tool_calls": 0, "tools_used": [], "iterations": 0, "queries_tried": [],
           "max_iters_reached": False, "trajectory": [], "degraded": False, "degraded_reason": None,
           "reranked": False, "rerank_error": None}
    out.update(over)
    return out


# --- the agent ------------------------------------------------------------------

async def run_ask(req: Any) -> dict[str, Any]:
    budget = Budget.from_config()
    llm_calls = 0
    tools_used: list[str] = []
    trajectory: list[dict[str, Any]] = []
    degraded_reason: str | None = None

    # 1) Mechanical routing: project resolution, intents, structural / digest.
    decision = await run_in_threadpool(router.decide, req.query, getattr(req, "mode", "auto"), None,
                                       getattr(req, "project", None), projects.resolve_project)
    understanding = query_understanding.identity(req.query)
    base = _base(req, understanding, req.top_k, decision)

    if decision.route == "structural":
        try:
            inv = await run_in_threadpool(structural.project_inventory, req.query, None)
            return _empty(base, route="structural", answer=_structural_answer(inv), structural=inv)
        except Exception as e:  # noqa: BLE001 — fall through to retrieval
            degraded_reason = f"structural_error: {e}"
    if decision.route == "digest":
        try:
            d = await run_in_threadpool(cards_mod.latest_weekly_digest)
        except Exception:  # noqa: BLE001
            d = None
        if d and d.get("markdown"):
            return _empty(base, route="digest", answer=d["markdown"],
                          epistemic=epistemic.parse(d["markdown"]),
                          digest={"id": d.get("id"), "kind": d.get("kind"), "run_id": d.get("run_id"),
                                  "created_at": str(d.get("created_at"))})
        degraded_reason = "no_weekly_digest_yet"

    # 2) Query understanding (one LLM call, skipped for short project lookups).
    if req.rewrite and not decision.skip_rewrite:
        understanding = await query_understanding.rewrite_query(req.query)
        llm_calls += 1
    if understanding.get("complexity") == "complex" and "multi_part" not in decision.intents:
        decision.intents.append("multi_part")
        decision.reasons.append("rewriter: complex")
    complexity = understanding.get("complexity", "moderate")
    effective_top_k = (config.topk_for_complexity(complexity)
                       if (req.adaptive_k and config.adaptive_topk_enabled()) else req.top_k)
    sub_queries = understanding.get("sub_queries", []) if config.multi_query_enabled() else []
    base = _base(req, understanding, effective_top_k, decision)

    # 3) First pass: cards + hybrid retrieval into the context builder.
    ctx = ContextBuilder.from_config(budget.max_context_tokens)
    plan = retrieval.plan_queries(understanding, sub_queries)
    queries_tried = [t for t, _ in plan]
    pid = decision.project["id"] if decision.project else None
    chunks: list[dict[str, Any]] = []
    card_hits: list[dict[str, Any]] = []
    try:
        embeddings = await asyncio.gather(*[retrieval.embed_query(e) for _, e in plan])
        file_ids = await run_in_threadpool(cards_mod.project_file_ids, pid) if pid else None
        try:
            card_hits = await run_in_threadpool(cards_mod.search_cards, req.query, embeddings[0], 10, req.folder, pid)
        except Exception as e:  # noqa: BLE001 — cards are optional
            log.debug("card search failed: %s", e)
            card_hits = []
        card_ranks = {c["file_id"]: c["card_rank"] for c in card_hits}
        chunks = await retrieval.multi_search_async(
            queries=[(t, emb) for (t, _), emb in zip(plan, embeddings)], rerank_query=req.query,
            top_k=effective_top_k, folder=req.folder, rerank_enabled=req.rerank,
            file_ids=file_ids or None, card_ranks=card_ranks or None)
    except Exception as e:  # noqa: BLE001 — retrieval failure is reported, not hidden
        degraded_reason = degraded_reason or f"retrieval_error: {type(e).__name__}: {e}"
        log.warning("first-pass retrieval failed: %s", e)

    if decision.project:
        try:
            st = await run_in_threadpool(projects.project_state, pid)
            ctx.add([from_project(decision.project, _state_text(decision.project, st))])
        except Exception:  # noqa: BLE001
            pass
    ctx.add([from_card(c) for c in card_hits[:5]])
    ctx.add([from_chunk(h) for h in chunks])

    rerank_conf = _confidence(chunks)
    card_conf = max((float(c["card_score"]) for c in card_hits if c.get("card_score") is not None), default=None)
    top_files = {h.get("file_id") for h in chunks[:3]}
    agreement = bool(card_hits) and card_hits[0]["file_id"] in top_files
    path, gate_reason = router.gate(decision, rerank_conf, card_conf, agreement)
    trajectory.append({"iteration": 0, "phase": "first_pass", "action": "retrieve", "queries": queries_tried,
                       "observation": f"{len(card_hits)} card(s), {len(chunks)} passage(s); rerank {rerank_conf:.2f}; "
                                      f"card {card_conf if card_conf is not None else '-'}; "
                                      f"{ctx.stats()['documents_used']} doc(s) in context",
                       "gate": path, "gate_reason": gate_reason})

    # 4) Bounded investigation.
    sufficient = path == "fast"
    last_missing = ""
    judge_conf: float | None = None
    if path == "investigate":
        catalog = registry.catalog()
        seen_calls: set[tuple[str, str]] = set()
        for it in range(1, budget.max_iterations + 1):
            if not budget.can_iterate():
                break
            phase = judge.PHASES[min(it - 1, len(judge.PHASES) - 1)]
            snap = {**budget.snapshot(), **ctx.stats()}
            try:
                verdict = await judge.decide(req.query, phase, it, budget.max_iterations, catalog, trajectory,
                                             ctx.digest(), snap, decision.project,
                                             decision.seed_tools if it == 1 else None,
                                             timeout=min(config.llm_primary_timeout(), max(10.0, budget.remaining_time())))
            except (llm.LLMUnavailable, ValueError) as e:
                trajectory.append({"iteration": it, "phase": phase, "action": "judge_error", "error": str(e)[:200]})
                budget.stop_reason = "judge_unavailable"
                break
            llm_calls += 1
            budget.iterations_used += 1
            judge_conf = verdict["confidence"]
            last_missing = verdict["missing"] or last_missing
            step: dict[str, Any] = {"iteration": it, "phase": phase, "thought": verdict["thought"],
                                    "action": verdict["action"], "sufficient": verdict["sufficient"], "tool_calls": []}
            if verdict["action"] == "answer":
                sufficient = verdict["sufficient"]
                budget.stop_reason = "judge_answer"
                trajectory.append(step)
                break
            calls: list[dict[str, Any]] = []
            for c in verdict["tool_calls"]:
                if len(calls) >= budget.max_tool_calls_per_iteration:
                    step["tool_calls"].append({"tool": c["tool"], "args": c["args"], "ok": False, "error": "per_round_cap"})
                    continue
                spec = registry.get(c["tool"])
                key = (c["tool"], json.dumps(c["args"], sort_keys=True, default=str))
                if spec is None:
                    step["tool_calls"].append({"tool": c["tool"], "args": c["args"], "ok": False, "error": "unknown_tool"})
                elif spec.cost == "llm":
                    step["tool_calls"].append({"tool": c["tool"], "args": c["args"], "ok": False, "error": "llm_tool_not_allowed_in_loop"})
                elif key in seen_calls:
                    step["tool_calls"].append({"tool": c["tool"], "args": c["args"], "ok": False, "error": "duplicate_call"})
                else:
                    seen_calls.add(key)
                    calls.append(c)
            if not calls:
                budget.stop_reason = "no_valid_calls"
                step["observation"] = "no valid new tool calls"
                trajectory.append(step)
                break
            results = await asyncio.gather(*[registry.call(c["tool"], c["args"]) for c in calls])
            added_total = 0
            for c, r in zip(calls, results):
                budget.tool_calls_used += 1
                tools_used.append(c["tool"])
                added = ctx.add(r.sources) if r.ok else 0
                added_total += added
                step["tool_calls"].append({"tool": c["tool"], "args": c["args"], "ok": r.ok, "summary": r.summary,
                                           "new_sources": added, "elapsed_ms": r.elapsed_ms, "error": r.error})
            st = ctx.stats()
            step["observation"] = (f"{added_total} new source(s); {st['documents_used']}/{budget.max_documents} documents; "
                                   f"{st['context_tokens']}/{budget.max_context_tokens} tokens"
                                   + ("; document budget reached" if st["rejected_documents"] else ""))
            trajectory.append(step)
            if added_total == 0:
                budget.stop_reason = "no_new_evidence"
                break
            if it == budget.max_iterations:
                budget.stop_reason = "max_iterations"
        if budget.stop_reason is None and budget.iterations_used >= budget.max_iterations:
            budget.stop_reason = "max_iterations"
    max_iters_reached = budget.stop_reason in ("max_iterations", "time_budget")

    # Graph augmentation (compat): entities/facts matched by name, added as fact sources.
    graph = None
    if req.use_graph:
        try:
            graph = await run_in_threadpool(retrieval.graph_only, understanding["search_query"], effective_top_k)
            ctx.add([from_fact(f, 0.6) for f in (graph.get("facts") or [])[:8]])
        except Exception:  # noqa: BLE001
            graph = None

    # 5) Synthesis.
    sources_block, citations = ctx.render()
    gaps = "" if sufficient else (last_missing or
           "Some aspects may be unanswered; a narrower follow-up or mode=investigate may help.")
    degraded = False
    answer = None
    if req.synthesize and ctx.sources:
        budget_note = ("The investigation budget was exhausted before a fully confident answer was reached. "
                       if max_iters_reached else "")
        investigation = (f"{budget_note}Route: {path} ({gate_reason}). Queries tried: {queries_tried}. "
                         f"Tools used: {tools_used or 'none'}. Sufficient: {sufficient}. "
                         f"Missing: {gaps or 'nothing notable'}.")
        user = f"QUESTION: {req.query}\n\nINVESTIGATION:\n{investigation}\n\nSOURCES:\n{sources_block}"
        try:
            answer = await llm.chat([{"role": "system", "content": _SYNTH_SYS}, {"role": "user", "content": user}],
                                    model=config.llm_judge_model(), timeout=budget.synthesis_timeout())
            llm_calls += 1
        except llm.LLMUnavailable as e:
            # Local-first: no cloud fallback, so an unreachable Mac is an error,
            # not a silently degraded answer. synthesize=false still returns sources.
            raise HTTPException(status_code=503, detail=llm.unavailable_detail(e))
    elif req.synthesize and not ctx.sources:
        degraded = True
        degraded_reason = degraded_reason or "no_results"

    final_conf = judge_conf if judge_conf is not None else max(rerank_conf, card_conf or 0.0)
    return {
        **base,
        "route": path,
        "answer": answer,
        "epistemic": epistemic.parse(answer) if answer else None,
        "citations": citations,
        "sources": [s.citation(i) | {"text": s.text} for i, s in enumerate(ctx.ordered(), start=1)] if not req.synthesize else None,
        "chunks": chunks,
        "chunk_citations": _legacy_citations(chunks),
        "graph": graph,
        "sufficient": sufficient,
        "confidence": {"retrieval": round(rerank_conf, 4), "cards": card_conf, "judge": judge_conf,
                       "final": round(float(final_conf), 4)},
        "gaps": gaps,
        "budget": {**budget.snapshot(), **ctx.stats()},
        "llm_calls": llm_calls,
        "tool_calls": budget.tool_calls_used,
        "tools_used": tools_used,
        "iterations": budget.iterations_used,
        "queries_tried": queries_tried,
        "max_iters_reached": max_iters_reached,
        "trajectory": trajectory,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "reranked": bool(req.rerank and chunks and any("rerank_score" in c for c in chunks)),
        "rerank_error": rerank.last_error(),
    }


run_agentic_ask = run_ask
