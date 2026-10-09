"""Entity resolution: collapse duplicate entities ("Nova Engg", "Nova Engineering",
"Nova Engineering Pte Ltd") into one canonical entity.

Matching is deterministic first, within a type group (company / organization /
client / vendor are one group):
  - same normalized key (case, punctuation, corporate suffixes ignored),
  - token-wise match where each token is equal, a prefix (>= 3 chars), or an
    abbreviation ("engg" ~ "engineering"),
  - acronym of a multi-word organisation name ("NBS" ~ "Nova Bank of
    Stars"), organisations only.
Optionally, name-embedding cosine >= threshold also merges, but only when the
names already share a matching token.

The canonical entity is the one tied to a project / path seed, else the most
mentioned, else the longest name. Dry-run by default; ``apply=True`` folds the
duplicates and logs every fold in ``entity_merges``.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Callable, Iterable

from rich.console import Console

from career_history import intel_db

console = Console()

_ORG_TYPES = {"company", "organization", "client", "vendor"}
_ORG_SUFFIXES = {"pte", "ltd", "limited", "inc", "corp", "corporation", "co", "sdn", "bhd",
                 "plc", "llc", "group", "holdings", "the", "berhad"}
_STOP = {"of", "and", "for", "the", "&"}
_SPLIT = re.compile(r"[^a-z0-9]+")


def type_group(entity_type: str) -> str:
    return "org" if entity_type in _ORG_TYPES else entity_type


def name_tokens(name: str, entity_type: str) -> list[str]:
    tokens = [t for t in _SPLIT.split((name or "").lower().replace("&", " and ")) if t]
    if type_group(entity_type) == "org":
        stripped = [t for t in tokens if t not in _ORG_SUFFIXES]
        tokens = stripped or tokens
    return tokens


def _is_abbreviation(short: str, long: str) -> bool:
    if len(short) < 3 or len(short) >= len(long) or short[0] != long[0]:
        return False
    it = iter(long)
    return all(ch in it for ch in short)


def token_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if a.isdigit() or b.isdigit():
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 3 and long.startswith(short):
        return True
    return _is_abbreviation(short, long)


def names_match(ta: list[str], tb: list[str]) -> bool:
    if not ta or not tb:
        return False
    if "".join(ta) == "".join(tb):
        return True
    if len(ta) != len(tb):
        return False
    return all(token_match(x, y) for x, y in zip(ta, tb))


def acronym_match(name_a: str, tb: list[str]) -> bool:
    """``name_a`` is an upper-case acronym of the multi-word name ``tb``."""
    raw = (name_a or "").strip()
    if not (2 <= len(raw) <= 6 and raw.isalpha() and raw.isupper()):
        return False
    words = [t for t in tb if t not in _STOP]
    return len(words) >= 2 and "".join(w[0] for w in words) == raw.lower()


def _shares_token(ta: list[str], tb: list[str]) -> bool:
    return any(token_match(x, y) for x in ta for y in tb)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _canonical_rank(e: dict[str, Any]) -> tuple:
    meta = e.get("metadata") or {}
    anchored = meta.get("source") in {"path-seed", "manifest"} or bool(meta.get("project_key"))
    return (anchored, int(e.get("mention_count") or 0), len(e.get("canonical_name") or ""))


def plan_merges(
    entities: list[dict[str, Any]],
    embed: Callable[[list[str]], list[list[float]]] | None = None,
    threshold: float = 0.93,
) -> list[dict[str, Any]]:
    """Return merges ``[{source_id, target_id, source_name, target_name, method, score}]``."""
    parent: dict[int, int] = {e["id"]: e["id"] for e in entities}
    method: dict[tuple[int, int], tuple[str, float]] = {}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int, how: str, score: float) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
            method[(a, b)] = (how, score)

    blocks: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    tokens: dict[int, list[str]] = {}
    for e in entities:
        toks = name_tokens(e["canonical_name"], e["entity_type"])
        tokens[e["id"]] = toks
        if toks:
            blocks[(type_group(e["entity_type"]), toks[0][0])].append(e)

    vectors: dict[int, list[float]] = {}
    if embed is not None:
        for block in blocks.values():
            if len(block) > 1:
                names = [e["canonical_name"] for e in block]
                for e, v in zip(block, embed(names)):
                    vectors[e["id"]] = v

    for (group, _), block in blocks.items():
        for i, a in enumerate(block):
            ta = tokens[a["id"]]
            for b in block[i + 1:]:
                tb = tokens[b["id"]]
                if names_match(ta, tb):
                    union(a["id"], b["id"], "token", 1.0)
                elif group == "org" and (acronym_match(a["canonical_name"], tb)
                                         or acronym_match(b["canonical_name"], ta)):
                    union(a["id"], b["id"], "acronym", 0.9)
                elif a["id"] in vectors and b["id"] in vectors and _shares_token(ta, tb):
                    score = _cosine(vectors[a["id"]], vectors[b["id"]])
                    if score >= threshold:
                        union(a["id"], b["id"], "embedding", round(score, 4))

    clusters: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in entities:
        clusters[find(e["id"])].append(e)
    pair_method = {frozenset(k): v for k, v in method.items()}
    merges: list[dict[str, Any]] = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        target = max(members, key=_canonical_rank)
        for m in members:
            if m["id"] == target["id"]:
                continue
            how, score = pair_method.get(frozenset((m["id"], target["id"])), ("cluster", None))
            merges.append({
                "source_id": m["id"], "target_id": target["id"],
                "source_name": m["canonical_name"], "target_name": target["canonical_name"],
                "entity_type": target["entity_type"], "method": how, "score": score,
            })
    return merges


def _ollama_embedder() -> Callable[[list[str]], list[list[float]]]:
    from career_history import embed as embed_mod

    def embed(names: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(names), 64):
            out.extend(embed_mod.embed(names[i:i + 64]))
        return out

    return embed


def resolve_entities(apply: bool = False, entity_types: Iterable[str] | None = None,
                     use_embeddings: bool = False, threshold: float = 0.93) -> dict[str, Any]:
    entities = intel_db.entities_for_resolution(entity_types)
    embedder = _ollama_embedder() if use_embeddings else None
    merges = plan_merges(entities, embed=embedder, threshold=threshold)
    if apply:
        for m in merges:
            intel_db.merge_entity(m["source_id"], m["target_id"], m["method"], m["score"])
        try:  # alias-named person entities fold into the configured "me"
            from career_history import identity
            identity.fold_aliases()
        except Exception as e:  # noqa: BLE001
            console.log(f"[yellow]identity fold skipped:[/yellow] {e}")
    by_method: dict[str, int] = defaultdict(int)
    for m in merges:
        by_method[m["method"]] += 1
    summary = {"entities": len(entities), "merges": len(merges), "applied": apply,
               "by_method": dict(by_method), "sample": merges[:25]}
    console.log(f"[green]resolve-entities {'applied' if apply else 'dry-run'}.[/green] "
                f"{len(merges)} merge(s) across {len(entities)} entities")
    return summary
