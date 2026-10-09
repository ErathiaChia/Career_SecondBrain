from era_mcp import retrieval


def test_plan_queries_uses_hyde_for_main_and_dedupes():
    u = {"search_query": "ibf pricing", "hyde_doc": "A pricing proposal for ..."}
    plan = retrieval.plan_queries(u, ["token pricing", "ibf pricing", "", "token pricing"])
    assert plan == [("ibf pricing", "A pricing proposal for ..."), ("token pricing", "token pricing")]


def test_plan_queries_without_hyde():
    assert retrieval.plan_queries({"search_query": "q"}) == [("q", "q")]
