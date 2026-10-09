from era_mcp.retrieval import lexical_terms


def test_drops_stopwords_and_question_words():
    assert lexical_terms("What did we present at the SCDS event?") == ["present", "scds", "event"]


def test_keeps_acronyms_and_versions_deduplicated():
    assert lexical_terms("IBF ibf V4 effort-estimation") == ["ibf", "v4", "effort", "estimation"]


def test_only_safe_tsquery_tokens():
    assert lexical_terms("a & b | !c :* 'd'") == ["b", "c", "d"]
    assert lexical_terms("") == []
    assert lexical_terms(None) == []
