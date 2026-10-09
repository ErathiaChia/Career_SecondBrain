from era_mcp.agent_tools.sources import Source, from_chunk, from_fact
from era_mcp.budget import Budget, estimate_tokens
from era_mcp.context import ContextBuilder


def _p(fid, rel, text="passage text " * 20, idx=0):
    return Source(kind="passage", text=text, file_id=fid, file_name=f"f{fid}.md", relevance=rel,
                  extra={"matched_chunk_index": idx})


def test_estimate_tokens():
    assert estimate_tokens("") == 0 and estimate_tokens("a" * 360) == 101


def test_document_cap_rejects_eleventh_document():
    ctx = ContextBuilder(max_documents=10, max_tokens=20000)
    added = ctx.add([_p(i, 0.5) for i in range(1, 13)])
    assert added == 10 and len(ctx.documents()) == 10 and ctx.rejected_documents == 2
    # a fact from an already-admitted document is fine; from a new one is not
    assert ctx.add([from_fact({"id": 9, "kind": "decision", "statement": "x", "file_id": 1, "file_name": "f1.md"})]) == 1
    assert ctx.add([from_fact({"id": 10, "kind": "decision", "statement": "y", "file_id": 99, "file_name": "f99.md"})]) == 0


def test_passages_per_document_and_dedupe():
    ctx = ContextBuilder(max_documents=10, max_tokens=20000)
    srcs = [_p(1, 0.9, idx=i, text=f"chunk {i} " * 10) for i in range(5)]
    assert ctx.add(srcs) == 3
    assert ctx.add(srcs) == 0  # duplicates never count as new evidence


def test_token_cap_drops_lowest_relevance_passages_first():
    ctx = ContextBuilder(max_documents=10, max_tokens=700)
    low = _p(1, 0.1, text="low " * 400)      # ~ 450 tokens -> trimmed to 330
    high = _p(2, 0.9, text="high " * 400)
    ctx.add([low])
    ctx.add([high])
    kinds = [(s.file_id, s.relevance) for s in ctx.sources]
    assert (2, 0.9) in kinds
    assert ctx.tokens() <= 700


def test_tier_order_and_render_labels():
    ctx = ContextBuilder(max_documents=10, max_tokens=20000)
    ctx.add([_p(1, 0.8)])
    ctx.add([Source(kind="card", text="Card summary", file_id=1, file_name="f1.md", relevance=0.7, date="2026-01-02")])
    ctx.add([from_fact({"id": 42, "kind": "decision", "statement": "Use tokens", "file_id": 1, "file_name": "f1.md"})])
    ctx.add([Source(kind="project", text="Project P", relevance=1.0)])
    block, cits = ctx.render()
    order = [s.kind for s in ctx.ordered()]
    assert order == ["project", "card", "passage", "fact"]
    assert "[F42]" in block and any(c["label"] == "[F42]" for c in cits)
    assert all({"file_name", "section", "date", "relevance", "kind"} <= set(c) for c in cits)
    assert "CARD | f1.md | 2026-01-02" in block


def test_digest_is_compact():
    ctx = ContextBuilder(max_documents=10, max_tokens=20000)
    ctx.add([_p(i, 0.5) for i in range(1, 8)])
    d = ctx.digest(max_lines=3)
    assert d.count("\n") == 3 and "more source(s)" in d


def test_budget_can_iterate_and_snapshot():
    b = Budget(max_iterations=2, time_budget_s=100, synth_reserve_s=30, est_judge_s=10)
    assert b.can_iterate()
    b.iterations_used = 2
    assert not b.can_iterate() and b.stop_reason == "max_iterations"
    b2 = Budget(max_iterations=3, time_budget_s=30, synth_reserve_s=30, est_judge_s=10)
    assert not b2.can_iterate() and b2.stop_reason == "time_budget"
    assert b2.synthesis_timeout() >= 15
    assert set(b2.snapshot()) >= {"iterations_used", "max_tool_calls", "elapsed_s", "stop_reason"}


def test_from_chunk_carries_citation_metadata(monkeypatch):
    monkeypatch.setenv("RERANK_KIND", "infinity")
    s = from_chunk({"content": "x", "file_id": 3, "file_name": "a.pdf", "file_path": "/v/a.pdf", "folder": "P",
                    "heading_path": "2 > 2.1", "page_number": 4, "last_modified_at": "2026-03-01T10:00:00",
                    "rerank_score": 0.83, "version_label": "V2", "is_latest": False})
    assert s.section == "2 > 2.1" and s.page == 4 and s.date == "2026-03-01" and s.relevance == 0.83
    assert s.version_label == "V2" and s.is_latest is False
