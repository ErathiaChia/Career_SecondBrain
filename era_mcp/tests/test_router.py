from era_mcp import router


def _resolve_factory(known):
    def resolve(ref):
        return known.get(ref.lower())
    return resolve


def test_structural_and_digest_routes():
    assert router.decide("how many projects are under 2026?").route == "structural"
    assert router.decide("What changed this week?").route == "digest"
    assert router.decide("weekly update please").route == "digest"
    assert router.decide("tell me about pricing").route == "retrieval"


def test_project_resolution_from_acronym_and_capitalised_ngram():
    resolve = _resolve_factory({"cl89": {"id": 1, "name": "CL89 CPX"}, "orion portal": {"id": 2, "name": "Orion Portal"}})
    d = router.decide("what is the latest on CL89 pricing?", resolve=resolve)
    assert d.project and d.project["id"] == 1 and any("project resolved" in r for r in d.reasons)
    d2 = router.decide("timeline of the Orion Portal rollout", resolve=resolve)
    assert d2.project["id"] == 2 and "timeline" in d2.intents and "get_project_history" in d2.seed_tools
    assert router.decide("hello", resolve=resolve).project is None


def test_project_hint_wins():
    resolve = _resolve_factory({"acme credit": {"id": 7, "name": "Acme Credit"}})
    d = router.decide("open risks?", project_hint="Acme Credit", resolve=resolve)
    assert d.project["id"] == 7 and d.skip_rewrite is True


def test_intents_seed_tools():
    d = router.decide("compare v2 and v3 of the proposal")
    assert "compare" in d.intents and d.seed_tools[:2] == ["find_latest_version", "compare_documents"]
    d = router.decide("what evidence do I have of leading AI delivery?")
    assert "career" in d.intents and "find_career_evidence" in d.seed_tools
    d = router.decide("why did we choose Appian over Pega?")
    assert "decision" in d.intents and "trace_decision" in d.seed_tools
    d = router.decide("are the pricing figures still valid or stale?")
    assert "conflict" in d.intents


def test_mode_override_and_gate(monkeypatch):
    monkeypatch.setenv("STRONG_RERANK_THRESHOLD", "0.8")
    monkeypatch.setenv("WEAK_RERANK_THRESHOLD", "0.35")
    monkeypatch.setenv("CARD_STRONG_THRESHOLD", "0.62")
    plain = router.decide("what is the go-live date?")
    assert router.gate(plain, 0.9, None, False)[0] == "fast"
    assert router.gate(plain, 0.5, 0.7, True)[0] == "fast"          # card agreement
    assert router.gate(plain, 0.5, 0.7, False)[0] == "investigate"  # ambiguous
    assert router.gate(plain, 0.2, None, False)[0] == "investigate"
    hinted = router.decide("compare the two versions")
    assert router.gate(hinted, 0.95, 0.9, True)[0] == "investigate"
    assert router.gate(router.decide("x", mode="fast"), 0.0, None, False)[0] == "fast"
    assert router.gate(router.decide("x", mode="investigate"), 0.99, None, False)[0] == "investigate"


def test_multi_part_and_complexity():
    assert "multi_part" in router.decide("what did we promise and also when is UAT?").intents
    assert "multi_part" in router.decide("x", understanding={"complexity": "complex"}).intents
