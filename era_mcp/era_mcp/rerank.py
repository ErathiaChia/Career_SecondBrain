"""Cross-encoder reranking of the fused candidate pool.

Ollama has no rerank endpoint, so two backends are offered:
  - ``infinity``  : an Infinity / TEI server (``/rerank``) on the Mac hosting
                    bge-reranker-v2-m3. Best quality.
  - ``llm_score`` : one batched LLM call scoring each candidate 0-10. No extra
                    server — reuses the synthesis LLM. Default.

Reranking is always best-effort: on any failure (or ``RERANK_ENABLED=0``) the
candidates are returned in their original RRF order, truncated to ``top_k``.
"""
from __future__ import annotations

import contextvars
import json
from typing import Any

import httpx

from era_mcp import config, llm

# Why the last rerank in this request context fell back to RRF order (or None).
# Surfaced as ``rerank_error`` in /ask responses so a silent fallback is visible.
_LAST_ERROR: contextvars.ContextVar[str | None] = contextvars.ContextVar("rerank_error", default=None)


def last_error() -> str | None:
    return _LAST_ERROR.get()


def status() -> dict[str, Any]:
    """Reranker configuration, for surfacing in /ask responses and debugging.

    Note: this reports how the reranker is *configured*, not whether a given
    request succeeded. To confirm reranking actually fired on a response, check
    whether the returned chunks carry a ``rerank_score`` (the /ask response also
    exposes a top-level ``reranked`` boolean derived that way)."""
    kind = config.rerank_kind()
    return {
        "enabled": config.rerank_enabled(),
        "kind": kind,
        "model": config.rerank_model() if kind == "infinity" else None,
        "base_url": config.rerank_base_url() if kind == "infinity" else None,
    }


async def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int,
    *,
    text_key: str = "content",
) -> list[dict[str, Any]]:
    """Return ``candidates`` reordered by relevance to ``query``, truncated to
    ``top_k``. Each surviving dict gains a ``rerank_score`` (when scored)."""
    _LAST_ERROR.set(None)
    if not candidates or not config.rerank_enabled():
        return candidates[:top_k]
    kind = config.rerank_kind()
    # Only the top of the RRF order is worth a cross-encoder pass (brief §9:
    # 20-50 candidates -> 5-10 sources). If top_k exceeds the cap, the tail
    # fills in RRF order without a rerank_score.
    head = candidates[:config.rerank_max_candidates()]
    tail = candidates[len(head):]
    try:
        if kind == "infinity":
            scored = await _rerank_infinity(query, head, text_key)
        elif kind == "llm_score":
            scored = await _rerank_llm(query, head, text_key)
        else:
            return candidates[:top_k]
    except Exception as e:
        # Any transport/parse error → keep deterministic RRF order, but say so.
        _LAST_ERROR.set(f"{kind}: {type(e).__name__}: {e}"[:200])
        return candidates[:top_k]
    return (scored + tail)[:top_k]


async def _rerank_infinity(
    query: str, candidates: list[dict[str, Any]], text_key: str
) -> list[dict[str, Any]]:
    documents = [(c.get(text_key) or "") for c in candidates]
    payload = {
        "model": config.rerank_model(),
        "query": query,
        "documents": documents,
        "return_documents": False,  # we only need indices+scores; keeps the response small
    }
    async with httpx.AsyncClient(timeout=config.rerank_timeout()) as client:
        resp = await client.post(f"{config.rerank_base_url()}/rerank", json=payload)
        resp.raise_for_status()
        data = resp.json()
    # Infinity/TEI: {"results": [{"index": i, "relevance_score": s}, ...]}
    results = data.get("results", data if isinstance(data, list) else [])
    ranked: list[dict[str, Any]] = []
    for item in results:
        idx = item.get("index")
        if idx is None or not (0 <= idx < len(candidates)):
            continue
        hit = dict(candidates[idx])
        hit["rerank_score"] = float(item.get("relevance_score", item.get("score", 0.0)))
        ranked.append(hit)
    if not ranked:
        raise ValueError("empty rerank result")
    ranked.sort(key=lambda h: h["rerank_score"], reverse=True)
    return ranked


_LLM_RERANK_SYSTEM = (
    "You are a search reranker. Score how well each numbered document answers the "
    "user's query, from 0 (irrelevant) to 10 (directly answers it). Respond with "
    'ONLY a JSON object: {"scores": [{"index": <int>, "score": <number>}, ...]} '
    "covering every document index."
)


def _parse_scores(data: Any) -> dict[int, float]:
    raw_scores = data.get("scores", data) if isinstance(data, dict) else data
    by_index: dict[int, float] = {}
    for item in raw_scores or []:
        try:
            by_index[int(item["index"])] = float(item["score"])
        except (KeyError, ValueError, TypeError):
            continue
    return by_index


async def _rerank_llm(
    query: str, candidates: list[dict[str, Any]], text_key: str
) -> list[dict[str, Any]]:
    """Score in small batches: one prompt with ~200 candidates x 600 chars used
    to blow past num_ctx/max_tokens and fail silently, which made the /ask
    confidence gate fall back to cosine and escalate every question."""
    batch = max(1, config.llm_rerank_batch())
    per_doc = config.llm_rerank_doc_chars()
    by_index: dict[int, float] = {}
    for start in range(0, len(candidates), batch):
        chunk = candidates[start:start + batch]
        docs = []
        for j, c in enumerate(chunk):
            body = (c.get(text_key) or "").replace("\n", " ")[:per_doc]
            docs.append(f"[{j}] {body}")
        user = f"Query: {query}\n\nDocuments:\n" + "\n".join(docs)
        data = await llm.chat_json(
            [{"role": "system", "content": _LLM_RERANK_SYSTEM},
             {"role": "user", "content": user}],
            timeout=config.rerank_timeout(),
        )
        for j, score in _parse_scores(data).items():
            if 0 <= j < len(chunk):
                by_index[start + j] = score
    if not by_index:
        raise ValueError("no usable LLM scores")
    scored, unscored = [], []
    for i, c in enumerate(candidates):
        hit = dict(c)
        if i in by_index:
            hit["rerank_score"] = by_index[i]
            scored.append(hit)
        else:
            # No score -> no rerank_score key, so confidence maths ignores it
            # instead of treating a -1 as a real (terrible) score.
            unscored.append(hit)
    scored.sort(key=lambda h: h["rerank_score"], reverse=True)
    return scored + unscored
