"""Project state: the current, sourced picture of a project.

Built in two layers:
  1. Deterministic, from typed facts: decisions, requirements, risks, blockers,
     open questions, next actions, milestones, commitments. Superseded facts and
     facts from older document versions are dropped or down-weighted.
  2. Optional LLM rollup (phase, objectives, priorities, summary). The model may
     only cite fact ids it was given; anything uncited is discarded, and a field
     with no valid citation is reported as UNKNOWN rather than guessed.

Every field is ``{value, confidence, sources, last_verified}``. Health is a set of
explainable dimensions (activity, delivery, risk, clarity, freshness), each with
a score, a level and the reasons/evidence behind it.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from rich.console import Console

from career_history import intel_db, llm

console = Console()

OPEN_STATUSES = {None, "open", "in_progress", "blocked", "proposed"}
DONE_STATUSES = {"done", "cancelled", "rejected", "mitigated"}
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, None: 3}
UNKNOWN = "UNKNOWN"


def _ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:19])
    except ValueError:
        return None


def _due(fact: dict[str, Any]) -> datetime | None:
    attrs = fact.get("attributes") or {}
    return _ts(attrs.get("due_at")) or (_ts(fact.get("occurred_at")) if fact.get("kind") == "milestone" else None)


def _item(fact: dict[str, Any], stale: dict[int, list[str]]) -> dict[str, Any]:
    confidence = float(fact.get("confidence") or 0.6)
    if not fact.get("from_latest_version", True):
        confidence *= 0.6
    if stale.get(fact["id"]):
        confidence *= 0.7
    due = _due(fact)
    return {
        "fact_id": fact["id"],
        "statement": fact["statement"],
        "kind": fact["kind"],
        "topic": fact.get("topic"),
        "status": fact.get("status"),
        "priority": fact.get("priority"),
        "owner": fact.get("owner") or (fact.get("attributes") or {}).get("owner"),
        "due": due.date().isoformat() if due else None,
        "source": {"file_id": fact["file_id"], "file_name": fact.get("file_name"),
                   "quote": fact.get("source_quote")},
        "last_verified": _iso(fact.get("last_verified_at") or fact.get("last_modified_at")),
        "confidence": round(confidence, 3),
        "stale_reasons": stale.get(fact["id"], []),
    }


def _iso(value: Any) -> str | None:
    ts = _ts(value)
    return ts.isoformat() if ts else None


def _field(value: Any, items: list[dict[str, Any]], confidence: float | None = None) -> dict[str, Any]:
    if confidence is None:
        confidence = (sum(i["confidence"] for i in items) / len(items)) if items else 0.0
    verified = [i["last_verified"] for i in items if i.get("last_verified")]
    return {
        "value": value,
        "confidence": round(confidence, 3),
        "sources": [{"fact_id": i["fact_id"], **i["source"]} for i in items[:8]],
        "last_verified": max(verified) if verified else None,
    }


def _list_field(items: list[dict[str, Any]]) -> dict[str, Any]:
    return _field(items, items)


def deterministic_state(project: dict[str, Any], facts: list[dict[str, Any]],
                        flags: dict[str, Any] | None = None,
                        now: datetime | None = None) -> dict[str, Any]:
    """State fields derivable from typed facts without an LLM."""
    now = now or datetime.now()
    flags = flags or {"stale": {}, "conflicts": []}
    stale = flags.get("stale", {})
    superseded = {f["supersedes_fact_id"] for f in facts if f.get("supersedes_fact_id")}
    live = [f for f in facts if f["id"] not in superseded]
    items = [_item(f, stale) for f in live]

    def of(kind: str, open_only: bool = False) -> list[dict[str, Any]]:
        out = [i for i in items if i["kind"] == kind]
        if open_only:
            out = [i for i in out if i["status"] not in DONE_STATUSES]
        return out

    def by_due(xs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(xs, key=lambda i: (i["due"] is None, i["due"] or "", _PRIORITY_RANK.get(i["priority"], 3)))

    risks = sorted(of("risk", open_only=True), key=lambda i: _PRIORITY_RANK.get(i["priority"], 3))
    dependencies = of("dependency", open_only=True)
    actions = by_due(of("action_item", open_only=True))
    blockers = [i for i in items if i["status"] == "blocked"] + \
               [i for i in risks if i["priority"] == "high"] + \
               [i for i in dependencies if i["status"] in {"open", "blocked"}]
    seen: set[int] = set()
    blockers = [b for b in blockers if not (b["fact_id"] in seen or seen.add(b["fact_id"]))]
    milestones = sorted(of("milestone"), key=lambda i: i["due"] or "9999")
    upcoming = [m for m in milestones if m["due"] and m["due"] >= now.date().isoformat()
                and m["status"] not in DONE_STATUSES]
    overdue = [i for i in actions + milestones
               if i["due"] and i["due"] < now.date().isoformat() and i["status"] not in DONE_STATUSES]

    return {
        "project": {"id": project["id"], "name": project["name"], "client": project.get("client"),
                    "status": project.get("status"), "type": project.get("project_type"),
                    "owner": project.get("owner")},
        "decisions": _list_field(of("decision")[:15]),
        "requirements": _list_field(of("requirement")[:30]),
        "risks": _list_field(risks[:20]),
        "dependencies": _list_field(dependencies[:20]),
        "blockers": _list_field(blockers[:10]),
        "open_questions": _list_field(of("open_question", open_only=True)[:15]),
        "next_actions": _list_field(actions[:15]),
        "milestones": _list_field(milestones[:20]),
        "upcoming_milestones": _list_field(upcoming[:5]),
        "overdue": _list_field(overdue[:10]),
        "commitments": _list_field(of("commitment", open_only=True)[:15]),
        "conflicts": {"value": flags.get("conflicts", []),
                      "confidence": 1.0, "sources": [], "last_verified": None},
        "fact_count": len(live),
        "superseded_count": len(superseded),
    }


def _level(score: int) -> str:
    return "green" if score >= 70 else "amber" if score >= 40 else "red"


def compute_health(project: dict[str, Any], state: dict[str, Any], counts: dict[str, Any] | None = None,
                   now: datetime | None = None) -> dict[str, Any]:
    """Explainable health: each dimension lists the reasons and evidence fact ids."""
    now = now or datetime.now()
    counts = counts or {}
    dims: dict[str, dict[str, Any]] = {}

    last = _ts(project.get("last_activity"))
    days = (now - last).days if last else None
    if days is None:
        dims["activity"] = {"score": 50, "reasons": ["No file activity recorded."], "evidence": []}
    else:
        score = 100 if days <= 14 else 75 if days <= 45 else 45 if days <= 120 else 20
        dims["activity"] = {"score": score, "reasons": [f"Last file activity {days} day(s) ago."], "evidence": []}

    overdue = state["overdue"]["value"]
    score = max(0, 100 - 20 * len(overdue))
    dims["delivery"] = {"score": score,
                        "reasons": [f"{len(overdue)} overdue action item(s)/milestone(s)."] if overdue
                        else ["Nothing overdue."],
                        "evidence": [i["fact_id"] for i in overdue]}

    risks = state["risks"]["value"]
    high = [r for r in risks if r["priority"] == "high"]
    score = max(0, 100 - 25 * len(high) - 5 * (len(risks) - len(high)))
    dims["risk"] = {"score": score,
                    "reasons": [f"{len(high)} high and {len(risks) - len(high)} other open risk(s)."],
                    "evidence": [r["fact_id"] for r in risks]}

    questions = state["open_questions"]["value"]
    conflicts = state["conflicts"]["value"]
    score = max(0, 100 - 8 * len(questions) - 15 * len(conflicts))
    dims["clarity"] = {"score": score,
                       "reasons": [f"{len(questions)} open question(s), {len(conflicts)} unresolved conflict(s)."],
                       "evidence": [q["fact_id"] for q in questions]}

    fact_count = state.get("fact_count") or 0
    stale = int(counts.get("stale_facts") or 0)
    ratio = (stale / fact_count) if fact_count else 0.0
    dims["freshness"] = {"score": int(round(100 * (1 - ratio))) if fact_count else 50,
                         "reasons": [f"{stale} of {fact_count} fact(s) flagged stale."] if fact_count
                         else ["No extracted facts yet; state is thin."],
                         "evidence": []}

    for d in dims.values():
        d["level"] = _level(d["score"])
    weights = {"activity": 0.15, "delivery": 0.3, "risk": 0.25, "clarity": 0.15, "freshness": 0.15}
    overall = int(round(sum(dims[k]["score"] * w for k, w in weights.items())))
    worst = min(dims.items(), key=lambda kv: kv[1]["score"])
    return {"overall": overall, "level": _level(overall), "dimensions": dims,
            "headline": f"{_level(overall).upper()}: weakest dimension is {worst[0]} ({worst[1]['reasons'][0]})"}


def _rollup_prompt(project: dict[str, Any], facts: list[dict[str, Any]]) -> str:
    lines = [f"[{f['id']}] ({f['kind']}{', ' + f['status'] if f.get('status') else ''}) {f['statement']}"
             for f in facts[:120]]
    return f"""
You maintain the state of a work project. Using ONLY the numbered facts below,
return JSON:
{{
  "phase": {{"value": "discovery|proposal|planning|design|build|testing|deployment|support|closed|unknown", "source_fact_ids": [], "confidence": 0.0}},
  "objectives": [{{"value": "short objective", "source_fact_ids": [], "confidence": 0.0}}],
  "priorities": [{{"value": "short priority", "source_fact_ids": [], "confidence": 0.0}}],
  "summary": {{"value": "2-3 sentence current status", "source_fact_ids": [], "confidence": 0.0}}
}}
Rules: every item must cite fact ids from the list. If the facts do not support a
field, return "unknown" / an empty list. Do not invent.

Project: {project['name']} (client: {project.get('client') or 'unknown'})
Facts:
{chr(10).join(lines)}
""".strip()


def validate_rollup(raw: dict[str, Any], facts_by_id: dict[int, dict[str, Any]],
                    stale: dict[int, list[str]] | None = None) -> dict[str, Any]:
    """Keep only rollup items that cite known fact ids; uncited fields become UNKNOWN."""
    stale = stale or {}

    def cited(entry: Any) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            return None
        value = entry.get("value")
        ids = []
        for x in entry.get("source_fact_ids") or []:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                continue
        ids = [i for i in ids if i in facts_by_id]
        if not value or str(value).strip().lower() == "unknown" or not ids:
            return None
        items = [_item(facts_by_id[i], stale) for i in ids]
        conf = entry.get("confidence")
        try:
            conf = min(float(conf), 1.0) if conf is not None else None
        except (TypeError, ValueError):
            conf = None
        base = sum(i["confidence"] for i in items) / len(items)
        return _field(str(value).strip(), items, min(base, conf) if conf is not None else base)

    out: dict[str, Any] = {}
    for key in ("phase", "summary"):
        f = cited(raw.get(key))
        out[key] = f or {"value": UNKNOWN, "confidence": 0.0, "sources": [], "last_verified": None}
    for key in ("objectives", "priorities"):
        entries = raw.get(key) if isinstance(raw.get(key), list) else []
        kept = [c for c in (cited(e) for e in entries) if c]
        out[key] = {"value": [k["value"] for k in kept],
                    "confidence": round(sum(k["confidence"] for k in kept) / len(kept), 3) if kept else 0.0,
                    "sources": [s for k in kept for s in k["sources"]][:12],
                    "last_verified": max((k["last_verified"] for k in kept if k["last_verified"]), default=None)}
    return out


def source_hash(project: dict[str, Any], facts: list[dict[str, Any]], counts: dict[str, Any],
                state: dict[str, Any], health: dict[str, Any]) -> str:
    """Hash of everything the state depends on. Date-dependent outputs (overdue
    set, activity level) are hashed instead of the date, so an idle project is
    not rebuilt every day."""
    key = {
        "p": [project.get(k) for k in ("name", "client", "status", "owner", "project_type")],
        "f": sorted((f["id"], f.get("status"), str(f.get("last_verified_at"))) for f in facts),
        "c": counts,
        "x": sorted(c["id"] for c in state["conflicts"]["value"]),
        "o": sorted(i["fact_id"] for i in state["overdue"]["value"]),
        "u": sorted(i["fact_id"] for i in state["upcoming_milestones"]["value"]),
        "a": health["dimensions"]["activity"]["level"],
    }
    return hashlib.sha256(json.dumps(key, default=str, sort_keys=True).encode()).hexdigest()


def build_state(project: dict[str, Any], use_llm: bool = True,
                skip_if_hash: str | None = None) -> tuple[dict, dict, str | None, str] | None:
    """Build state + health. Returns None when the inputs hash to ``skip_if_hash``
    (so the LLM rollup is not paid for an unchanged project)."""
    facts = intel_db.project_facts(project["id"])
    flags = intel_db.project_flags(project["id"])
    counts = intel_db.project_counts(project["id"])
    state = deterministic_state(project, facts, flags)
    state["counts"] = counts
    health = compute_health(project, state, counts)
    digest = source_hash(project, facts, counts, state, health)
    if skip_if_hash is not None and digest == skip_if_hash:
        return None
    model = None
    if use_llm and facts:
        try:
            raw = llm.generate_json(_rollup_prompt(project, facts))
            state.update(validate_rollup(raw, {f["id"]: f for f in facts}, flags.get("stale")))
            model = llm._model()
        except llm.LLMError as e:
            console.log(f"[yellow]State rollup skipped for {project['name']}:[/yellow] {e}")
    for key in ("phase", "summary"):
        state.setdefault(key, {"value": UNKNOWN, "confidence": 0.0, "sources": [], "last_verified": None})
    for key in ("objectives", "priorities"):
        state.setdefault(key, {"value": [], "confidence": 0.0, "sources": [], "last_verified": None})
    return state, health, model, digest


def refresh_states(project_ref: str | None = None, use_llm: bool = True,
                   force: bool = False) -> dict[str, Any]:
    projects = [intel_db.get_project(project_ref)] if project_ref else intel_db.list_projects()
    projects = [p for p in projects if p]
    built = skipped = 0
    for project in projects:
        current = None if force else intel_db.current_project_state(project["id"])
        result = build_state(project, use_llm=use_llm,
                             skip_if_hash=current["source_hash"] if current else None)
        if result is None:
            skipped += 1
            continue
        state, health, model, digest = result
        if force:
            digest = f"{digest}:{datetime.now().isoformat()}"
        if intel_db.save_project_state(project["id"], state, health, model, digest) is None:
            skipped += 1
        else:
            built += 1
    console.log(f"[green]project-state:[/green] {built} rebuilt, {skipped} unchanged")
    return {"projects": len(projects), "rebuilt": built, "unchanged": skipped}
