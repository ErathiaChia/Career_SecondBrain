from career_history import runner


def test_stamp_versions_records_parser_embedding_and_time(monkeypatch):
    seen = {}
    monkeypatch.setattr(runner.db, "set_file_versions", lambda fid, **kw: seen.update(fid=fid, **kw))
    monkeypatch.setattr(runner.config, "get", lambda: {"models": {"embedding_model": "qwen3-embedding:0.6b"}})
    chunks = [{"content": "a"}, {"content": "b", "embedding_content_version": "markdown-headings-ctx-qwen3-v1"}]
    runner._stamp_versions(7, chunks, "docling-v2+noimg+ocr:0+markdown-headings-v1")
    assert seen["fid"] == 7
    assert seen["parser_version"].startswith("docling-v2")
    assert seen["embedding_model"] == "qwen3-embedding:0.6b"
    assert seen["embedding_version"] == "markdown-headings-ctx-qwen3-v1"
    assert seen["indexed_at"] is not None


def test_stamp_versions_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(runner.db, "set_file_versions", boom)
    monkeypatch.setattr(runner.config, "get", lambda: {"models": {}})
    runner._stamp_versions(1, [], "x")  # logs and returns
