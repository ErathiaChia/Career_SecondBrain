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
                        now: datetime | None = None,
                        extras: dict[str, Any] | None = None) -> dict[str, Any]:
    """State fields derivable from typed facts without an LLM. ``extras`` (from
    ``project_record_inputs``) adds the brief §13 project record: my role, the
    technologies, a timeline, evidence documents, outcomes, related projects."""
    now = now or datetime.now()
    flags = flags or {"stale": {}, "conflicts": []}
    extras = extras or {}
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
        **project_record(project, items, extras),
    }


def project_record(project: dict[str, Any], items: list[dict[str, Any]], extras: dict[str, Any]) -> dict[str, Any]:
    """Brief §13: role, technologies, timeline, evidence, outcomes, related."""
    roles = extras.get("roles") or []
    confirmed = [r for r in roles if r.get("status") == "confirmed"]
    best = (confirmed or sorted(roles, key=lambda r: -float(r.get("confidence") or 0))[:1] or [None])[0]
    role = {"value": best["role"] if best else UNKNOWN,
            "confidence": round(float(best["confidence"]), 3) if best else 0.0,
            "status": best.get("status") if best else None,
            "sources": list(best.get("sources") or [])[:8] if best else [],
            "last_verified": _iso(best.get("updated_at")) if best else None}
    techs = [{"entity_id": t["entity_id"], "name": t["name"], "type": t.get("entity_type"),
              "mentions": int(t.get("mention_count") or 0)} for t in (extras.get("technologies") or [])[:15]]
    timeline: list[dict[str, Any]] = []
    for i in items:
        when = i.get("due") if i["kind"] in ("milestone", "action_item", "commitment") else None
        occurred = None
        src = extras.get("facts_by_id", {}).get(i["fact_id"]) if extras.get("facts_by_id") else None
        if src is not None:
            occurred = _iso(src.get("occurred_at"))
        when = (occurred or "")[:10] or when
        if when and i["kind"] in ("event", "milestone", "decision", "outcome", "contribution", "commitment"):
            timeline.append({"date": when, "kind": i["kind"], "statement": i["statement"], "fact_id": i["fact_id"],
                             "status": i.get("status")})
    for e in extras.get("events") or []:
        ts = _iso(e.get("detected_at"))
        if ts:
            timeline.append({"date": ts[:10], "kind": f"file_{e['kind']}", "statement": e.get("file_name"),
                             "file_id": e.get("file_id")})
    timeline.sort(key=lambda t: t["date"])
    evidence = [{"file_id": c["file_id"], "file_name": c.get("file_name"), "title": c.get("title"),
                 "doc_type": c.get("doc_type"), "summary": (c.get("summary") or "")[:300],
                 "fact_count": int(c.get("fact_count") or 0)} for c in (extras.get("cards") or [])[:12]]
    outcomes = [{"achievement_id": a["id"], "statement": a["statement"], "metric": a.get("metric"),
                 "outcome_kind": a.get("outcome_kind"), "is_me": a.get("is_me"), "confidence": float(a.get("confidence") or 0),
                 "evidence_fact_ids": a.get("evidence_fact_ids") or []}
                for a in (extras.get("achievements") or [])[:15]]
    related = [{"project_id": r["project_id"], "name": r.get("name"), "score": float(r.get("score") or 0),
                "shared_entities": r.get("shared_entities")} for r in (extras.get("related_projects") or [])[:5]]
    ai_words = [str(w).lower() for w in (extras.get("ai_keywords") or [])]
    haystack = " ".join([t["name"].lower() for t in techs] + [str(project.get("name") or "").lower()] +
                        [str(t).lower() for c in (extras.get("cards") or []) for t in (c.get("topics") or [])])
    is_ai = any(w in haystack for w in ai_words) if ai_words else False
    return {
        "role": role,
        "technologies": {"value": techs, "confidence": 1.0 if techs else 0.0, "sources": [], "last_verified": None},
        "timeline": {"value": timeline[-80:], "confidence": 1.0 if timeline else 0.0, "sources": [], "last_verified": None},
        "evidence_documents": {"value": evidence, "confidence": 1.0 if evidence else 0.0, "sources": [], "last_verified": None},
        "outcomes": {"value": outcomes, "confidence": round(sum(o["confidence"] for o in outcomes) / len(outcomes), 3) if outcomes else 0.0,
                     "sources": [{"fact_id": fid} for o in outcomes for fid in o["evidence_fact_ids"][:2]][:8], "last_verified": None},
        "related_projects": {"value": related, "confidence": 1.0 if related else 0.0, "sources": [], "last_verified": None},
        "is_ai_initiative": is_ai,
    }


def project_record_inputs(project_id: int) -> dict[str, Any]:
    """Load the §13 extras (all optional tables; empty when not built yet)."""
    from career_history import career_db, cards_db, config
    try:
        ai_keywords = (config.me() or {}).get("ai_keywords") or []
    except Exception:  # noqa: BLE001
        ai_keywords = []
    return {
        "roles": career_db.list_roles(project_id, me_only=True),
        "technologies": career_db.project_technology_mentions(project_id)
        if career_db.table_exists("project_files") else [],
        "events": cards_db.project_events(project_id),
        "cards": cards_db.project_cards(project_id),
        "achievements": career_db.list_achievements(project_id),
        "related_projects": cards_db.related_projects(project_id),
        "ai_keywords": ai_keywords,
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
  "stage": {{"value": "opportunity|poc|architecture|delivery|support|closed|unknown", "source_fact_ids": [], "confidence": 0.0}},
  "business_problem": {{"value": "one sentence: the customer problem this project addresses", "source_fact_ids": [], "confidence": 0.0}},
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
    for key in ("phase", "summary", "stage", "business_problem"):
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
        "r": [state.get("role", {}).get("value"), state.get("role", {}).get("status")],
        "t": [t["entity_id"] for t in state.get("technologies", {}).get("value", [])],
        "ach": sorted(o["achievement_id"] for o in state.get("outcomes", {}).get("value", [])),
        "rel": sorted(r["project_id"] for r in state.get("related_projects", {}).get("value", [])),
        "ev": sorted(e["file_id"] for e in state.get("evidence_documents", {}).get("value", [])),
    }
    return hashlib.sha256(json.dumps(key, default=str, sort_keys=True).encode()).hexdigest()


def build_state(project: dict[str, Any], use_llm: bool = True,
                skip_if_hash: str | None = None) -> tuple[dict, dict, str | None, str] | None:
    """Build state + health. Returns None when the inputs hash to ``skip_if_hash``
    (so the LLM rollup is not paid for an unchanged project)."""
    facts = intel_db.project_facts(project["id"])
    flags = intel_db.project_flags(project["id"])
    counts = intel_db.project_counts(project["id"])
    try:
        extras = project_record_inputs(project["id"])
    except Exception as e:  # noqa: BLE001 — the record is additive
        console.log(f"[yellow]project record inputs skipped for {project['name']}:[/yellow] {e}")
        extras = {}
    extras["facts_by_id"] = {f["id"]: f for f in facts}
    state = deterministic_state(project, facts, flags, extras=extras)
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
    for key in ("phase", "summary", "stage", "business_problem"):
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
