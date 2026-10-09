from career_history import identity

CFG = {"name": "Jane Tan", "aliases": ["Jane", "JT", "jtan"]}


def test_is_me_matches_name_aliases_and_first_person():
    for n in ("Jane Tan", "jane tan", "  JANE ", "JT", "jtan", "I", "me", "My", "myself"):
        assert identity.is_me(n, CFG), n
    for n in ("Someone Else", "Janet", "", None, "team"):
        assert not identity.is_me(n, CFG), n


def test_alias_set_normalises():
    assert identity.alias_set(CFG) == {"jane tan", "jane", "jt", "jtan"}
    assert identity.alias_set({"name": "", "aliases": []}) == set()


def test_resolve_owner_prefers_existing_resolution(monkeypatch):
    monkeypatch.setattr(identity, "me_config", lambda: CFG)
    monkeypatch.setattr(identity, "me_entity_id", lambda refresh=False: 42)
    assert identity.resolve_owner("Jane", fallback_id=7) == 7
    assert identity.resolve_owner("Jane", None) == 42
    assert identity.resolve_owner("I", None) == 42
    assert identity.resolve_owner("Bob", None) is None
