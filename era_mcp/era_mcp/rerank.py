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

import json
from typing import Any

import httpx

from era_mcp import config, llm


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
    if not candidates or not config.rerank_enabled():
        return candidates[:top_k]
    kind = config.rerank_kind()
    try:
        if kind == "infinity":
            scored = await _rerank_infinity(query, candidates, text_key)
        elif kind == "llm_score":
            scored = await _rerank_llm(query, candidates, text_key)
        else:
            return candidates[:top_k]
    except Exception:
        # Any transport/parse error → keep deterministic RRF order.
        return candidates[:top_k]
    return scored[:top_k]


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


async def _rerank_llm(
    query: str, candidates: list[dict[str, Any]], text_key: str
) -> list[dict[str, Any]]:
    # Truncate each doc so the batch fits comfortably in context.
    docs = []
    for i, c in enumerate(candidates):
        body = (c.get(text_key) or "").replace("\n", " ")[:600]
        docs.append(f"[{i}] {body}")
    user = f"Query: {query}\n\nDocuments:\n" + "\n".join(docs)
    data = await llm.chat_json(
        [{"role": "system", "content": _LLM_RERANK_SYSTEM},
         {"role": "user", "content": user}],
        timeout=config.rerank_timeout(),
    )
    raw_scores = data.get("scores", data) if isinstance(data, dict) else data
    by_index: dict[int, float] = {}
    for item in raw_scores or []:
        try:
            by_index[int(item["index"])] = float(item["score"])
        except (KeyError, ValueError, TypeError):
            continue
    if not by_index:
        raise ValueError("no usable LLM scores")
    ranked = []
    for i, c in enumerate(candidates):
        hit = dict(c)
        # Unscored candidates sink to the bottom but are retained.
        hit["rerank_score"] = by_index.get(i, -1.0)
        ranked.append(hit)
    ranked.sort(key=lambda h: h["rerank_score"], reverse=True)
    return ranked
