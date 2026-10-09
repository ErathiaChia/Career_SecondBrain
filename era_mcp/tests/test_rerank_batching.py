"""llm_score reranking must batch (never one giant prompt), never invent scores
for unscored candidates, and report why it fell back."""
from __future__ import annotations

import asyncio

import pytest

from era_mcp import config, rerank


def _run(coro):
    """Run the coroutine and capture rerank.last_error() from INSIDE the task
    (asyncio.run copies the context, so the ContextVar is not visible outside)."""
    async def go():
        out = await coro
        return out, rerank.last_error()
    return asyncio.run(go())


def _cands(n):
    return [{"id": i, "content": f"doc {i} " + "x" * 2000, "similarity": 0.5} for i in range(n)]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("RERANK_ENABLED", "1")
    monkeypatch.setenv("RERANK_KIND", "llm_score")
    monkeypatch.setenv("LLM_RERANK_BATCH", "5")
    monkeypatch.setenv("RERANK_MAX_CANDIDATES", "12")
    monkeypatch.setenv("LLM_RERANK_DOC_CHARS", "100")


def test_batches_and_caps(monkeypatch):
    calls = []

    async def fake_chat_json(messages, **kw):
        user = messages[1]["content"]
        calls.append(user)
        n = user.count("\n[")  # one "[j] ..." line per doc
        return {"scores": [{"index": j, "score": 10 - j} for j in range(n)]}

    monkeypatch.setattr(rerank.llm, "chat_json", fake_chat_json)
    out, err = _run(rerank.rerank("q", _cands(30), top_k=20))
    # 12 candidates scored in batches of 5 -> 3 calls; tail (18) kept in RRF order unscored
    assert len(calls) == 3
    assert all(len(c) < 5 * 100 + 400 for c in calls)  # per-doc truncation applied
    assert len(out) == 20
    scored = [o for o in out if "rerank_score" in o]
    assert len(scored) == 12 and out[0]["id"] == 0
    assert all("rerank_score" not in o for o in out[12:])
    assert err is None


def test_unscored_have_no_key(monkeypatch):
    async def fake_chat_json(messages, **kw):
        return {"scores": [{"index": 0, "score": 7}]}  # scores only the first of each batch

    monkeypatch.setattr(rerank.llm, "chat_json", fake_chat_json)
    out, _ = _run(rerank.rerank("q", _cands(6), top_k=6))
    with_score = [o for o in out if "rerank_score" in o]
    assert [o["id"] for o in with_score] == [0, 5]          # index 0 of batch 1 and batch 2
    assert all(o.get("rerank_score", 0) >= 0 for o in out)  # never -1 sentinels


def test_failure_keeps_rrf_order_and_reports(monkeypatch):
    async def boom(messages, **kw):
        raise ValueError("garbage json")

    monkeypatch.setattr(rerank.llm, "chat_json", boom)
    cands = _cands(4)
    out, err = _run(rerank.rerank("q", cands, top_k=3))
    assert [o["id"] for o in out] == [0, 1, 2]
    assert "ValueError" in (err or "")
    assert all("rerank_score" not in o for o in out)


def test_disabled_passthrough(monkeypatch):
    monkeypatch.setenv("RERANK_ENABLED", "0")
    out, _ = _run(rerank.rerank("q", _cands(3), top_k=2))
    assert [o["id"] for o in out] == [0, 1]
    assert config.rerank_max_candidates() == 12
