from career_history.discover import _skip_subtree


def test_prefix_and_glob_patterns():
    pats = ["Z. AI_Notebook/Weekly", "*/_tmp"]
    assert _skip_subtree("Z. AI_Notebook/Weekly", pats)
    assert _skip_subtree("Z. AI_Notebook/Weekly/2026", pats)
    assert not _skip_subtree("Z. AI_Notebook/_eval", pats)      # the freshness probe IS ingested
    assert _skip_subtree("01 Project/_tmp", pats)
    assert not _skip_subtree("01 Project", pats)
    assert not _skip_subtree("01 Project", [])
