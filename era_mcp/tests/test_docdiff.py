from era_mcp import docdiff


OLD = """# Scope
Build portal.

# Timeline
Go-live 1 Nov.

# Budget
SGD 200k.
"""

NEW = """# Scope
Build portal.

# Timeline
Go-live 15 Dec.

# Risks
Vendor API delay.
"""


def test_diff_texts_reports_sections_and_lines():
    d = docdiff.diff_texts(OLD, NEW)
    assert d["sections_changed"] == ["Timeline"]
    assert d["sections_added"] == ["Risks"]
    assert d["sections_removed"] == ["Budget"]
    assert d["lines_added"] >= 2 and d["lines_removed"] >= 2
    assert any(l.startswith("+Go-live 15 Dec.") for l in d["diff"])
    assert 0 < d["similarity"] < 1
    assert d["truncated"] is False


def test_diff_texts_truncates():
    old = "\n".join(f"line {i}" for i in range(500))
    new = "\n".join(f"LINE {i}" for i in range(500))
    d = docdiff.diff_texts(old, new, max_lines=20)
    assert len(d["diff"]) == 20 and d["truncated"] is True
