"""Who "me" is (brief §12): the vault owner as one canonical person entity so
facts, roles, achievements and skills can be attributed to them.

config.yaml::

    me:
      name: "Jane Tan"
      aliases: ["Jane", "JT", "jtan"]
      default_roles: [project_manager, solution_architect]   # prior for role inference
      role_prior_weight: 0.35
      ai_keywords: [ai, llm, genai, agent, rag, "machine learning"]

``seed_me`` upserts the entity (metadata.is_me = true) and folds any person
entity whose name is one of the aliases into it. Extraction resolves first-person
and alias owners to this entity; resolution never merges it away.
"""
from __future__ import annotations

import re
from typing import Any

from rich.console import Console
from sqlalchemy import text

from career_history import config, db

console = Console()

_FIRST_PERSON = {"i", "me", "my", "myself", "self", "mine"}
_ME_ID: int | None = None


def me_config() -> dict[str, Any]:
    try:
        return dict(config.me())
    except Exception:  # noqa: BLE001
        return {}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def alias_set(cfg: dict[str, Any] | None = None) -> set[str]:
    cfg = cfg if cfg is not None else me_config()
    names = [cfg.get("name") or ""] + list(cfg.get("aliases") or [])
    return {_norm(n) for n in names if _norm(n)}


def is_me(name: Any, cfg: dict[str, Any] | None = None) -> bool:
    """True for the configured name/aliases and for first-person references."""
    n = _norm(name)
    if not n:
        return False
    if n in _FIRST_PERSON:
        return True
    return n in alias_set(cfg)


def me_entity_id(refresh: bool = False) -> int | None:
    """The 'me' entity id (cached per process); None when `me.name` is unset."""
    global _ME_ID
    if _ME_ID is not None and not refresh:
        return _ME_ID
    with db.conn() as c:
        row = c.execute(text("""
            SELECT id FROM entities
             WHERE entity_type = 'person' AND metadata ->> 'is_me' = 'true'
             ORDER BY id LIMIT 1
        """)).fetchone()
    _ME_ID = row[0] if row else None
    return _ME_ID


def seed_me() -> dict[str, Any]:
    """Create/update the me entity and fold alias-named person entities into it."""
    global _ME_ID
    cfg = me_config()
    name = (cfg.get("name") or "").strip()
    if not name:
        return {"skipped": True, "reason": "me.name not configured"}
    aliases = [a for a in (cfg.get("aliases") or []) if str(a).strip()]
    entity_id = db.upsert_entity(canonical_name=name, entity_type="person", aliases=aliases,
                                 metadata={"is_me": True, "source": "identity"})
    _ME_ID = entity_id
    folded = fold_aliases(entity_id, cfg)
    console.log(f"[green]identity:[/green] me = entity {entity_id} ({name}), folded {folded} alias entit(ies)")
    return {"entity_id": entity_id, "folded": folded, "skipped": False}


def fold_aliases(entity_id: int | None = None, cfg: dict[str, Any] | None = None) -> int:
    """Merge person entities whose canonical name is one of my aliases into me."""
    from career_history import intel_db
    cfg = cfg if cfg is not None else me_config()
    entity_id = entity_id or me_entity_id()
    if entity_id is None:
        return 0
    names = sorted(alias_set(cfg))
    if not names:
        return 0
    with db.conn() as c:
        rows = c.execute(text("""
            SELECT id FROM entities
             WHERE entity_type = 'person' AND id <> :me
               AND lower(canonical_name) = ANY(CAST(:names AS text[]))
        """), {"me": entity_id, "names": names}).fetchall()
    for (src,) in rows:
        intel_db.merge_entity(src, entity_id, method="identity", score=1.0)
    return len(rows)


def resolve_owner(name: Any, fallback_id: int | None = None) -> int | None:
    """Entity id for a fact participant: the me entity when the name is me, else
    ``fallback_id`` (whatever same-extraction resolution found)."""
    if fallback_id is not None:
        return fallback_id
    if is_me(name):
        return me_entity_id()
    return None
