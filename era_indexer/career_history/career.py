"""The career ("me") layer, brief §12-13: which role I held on each project,
what was achieved (with evidence), and which skills/technologies I used.

Everything is derived deterministically from typed facts, entity mentions and
cards; the user is "usually the PM or SA", so those roles carry a prior that
decays as real evidence accumulates. Low-confidence roles are queued as a
``confirm_role`` proposed action for the user to settle (``confirm-role``).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import date
from typing import Any

from rich.console import Console

from career_history import career_db, identity, intel_db

console = Console()

ROLES = ("project_manager", "solution_architect", "presales", "delivery_lead", "product_manager",
         "engineer", "consultant", "stakeholder", "sponsor", "other")

# contribution.attributes.activity -> role weight
_ACTIVITY_ROLE = {
    "led": {"project_manager": 0.40, "delivery_lead": 0.15},
    "managed": {"project_manager": 0.40},
    "planned": {"project_manager": 0.25},
    "coordinated": {"project_manager": 0.25},
    "designed": {"solution_architect": 0.40},
    "architected": {"solution_architect": 0.45},
    "reviewed": {"solution_architect": 0.10, "consultant": 0.10},
    "presented": {"presales": 0.25},
    "sold": {"presales": 0.30},
    "negotiated": {"presales": 0.25},
    "demoed": {"presales": 0.20},
    "built": {"engineer": 0.30},
    "implemented": {"engineer": 0.25},
    "delivered": {"delivery_lead": 0.20, "project_manager": 0.10},
    "advised": {"consultant": 0.30},
}
_RELATION_ROLE = {"MANAGES": {"project_manager": 0.30}, "OWNS": {"project_manager": 0.20},
                  "DELIVERS": {"delivery_lead": 0.25}, "DECIDED": {"solution_architect": 0.10, "project_manager": 0.10}}
_DOC_TYPE_ROLE = {
    "architecture": {"solution_architect": 0.08}, "design": {"solution_architect": 0.08},
    "plan": {"project_manager": 0.06}, "tracker": {"project_manager": 0.06}, "status_report": {"project_manager": 0.06},
    "proposal": {"presales": 0.06}, "pricing": {"presales": 0.06}, "sow": {"presales": 0.04, "project_manager": 0.04},
}
_ROLE_LABELS = {
    "project_manager": ["project manager", "pm", "programme manager", "program manager", "delivery manager"],
    "solution_architect": ["solution architect", "solutions architect", "sa", "architect", "technical architect"],
    "presales": ["presales", "pre-sales", "sales engineer", "bid manager"],
    "delivery_lead": ["delivery lead", "engagement lead", "engagement manager"],
    "product_manager": ["product manager", "product owner"],
    "engineer": ["engineer", "developer", "data scientist", "ml engineer"],
    "consultant": ["consultant", "advisor"],
}

_METRIC_RES = [
    (re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%"), "percent"),
    (re.compile(r"(?P<cur>SGD|S\$|USD|US\$|\$|EUR|€|MYR|RM)\s?(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>k|m|mn|million|b|bn|billion)?", re.I), "currency"),
    (re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<scale>x)\b", re.I), "multiplier"),
    (re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>days?|weeks?|months?|hours?|minutes?)\b", re.I), "duration"),
    (re.compile(r"(?P<value>\d[\d,]*)\s*(?P<unit>users?|sites?|customers?|branches?|stores?|documents?|tickets?|agents?)\b", re.I), "count"),
]
_OUTCOME_KIND_WORDS = {
    "revenue": ["revenue", "sales", "booking", "contract value", "tcv", "arr"],
    "cost": ["cost", "saving", "savings", "opex", "capex", "budget"],
    "time": ["faster", "cycle time", "turnaround", "hours saved", "days saved", "reduced time", "time to"],
    "quality": ["accuracy", "error", "defect", "quality", "precision", "recall", "csat", "nps"],
    "adoption": ["adoption", "users", "usage", "rollout", "onboarded", "active"],
    "win": ["won", "awarded", "win", "selected", "shortlisted", "signed"],
    "delivery": ["go-live", "went live", "launched", "delivered", "deployed", "completed", "uat passed"],
    "award": ["award", "recognised", "recognized", "commendation"],
}


# --- roles ---------------------------------------------------------------------

def _add(scores: dict[str, float], signals: dict[str, float], role_weights: dict[str, float],
         signal: str, scale: float = 1.0) -> None:
    for role, w in role_weights.items():
        scores[role] = scores.get(role, 0.0) + w * scale
        signals[signal] = signals.get(signal, 0.0) + w * scale


def score_roles(project: dict[str, Any], facts: list[dict[str, Any]], files: list[dict[str, Any]],
                me_id: int | None, cfg: dict[str, Any] | None = None,
                relationships: list[dict[str, Any]] | None = None,
                mentions: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Pure: score each role for ME on one project. Returns
    {role: {score 0-1, signals, sources}}. Signals: the PM/SA prior (decaying
    with evidence), contribution facts I own (activity verbs), commitments owed
    by me, projects.owner == me, MANAGES/OWNS relationships, role labels in
    facts, and the doc_type mix of files that list me."""
    cfg = cfg or {}
    scores: dict[str, float] = {}
    signals: dict[str, float] = {}
    sources: list[dict[str, Any]] = []
    evidence_weight = 0.0

    mine = [f for f in facts if me_id is not None and f.get("owner_entity_id") == me_id]
    for f in mine:
        attrs = f.get("attributes") or {}
        kind = f.get("kind")
        if kind == "contribution":
            activity = str(attrs.get("activity") or "").lower().strip()
            weights = _ACTIVITY_ROLE.get(activity)
            if not weights:  # fall back to verbs in the statement
                stmt = str(f.get("statement") or "").lower()
                weights = next((w for verb, w in _ACTIVITY_ROLE.items() if re.search(rf"\b{verb}\b", stmt)), None)
            if weights:
                conf = float(f.get("confidence") or 0.6)
                _add(scores, signals, weights, "contribution_facts", conf)
                evidence_weight += conf
                sources.append({"fact_id": f["id"]})
            label = str(attrs.get("role_hint") or attrs.get("role") or "").lower()
            for role, labels in _ROLE_LABELS.items():
                if label and any(label == l or label.startswith(l) for l in labels):
                    _add(scores, signals, {role: 0.35}, "role_label")
                    evidence_weight += 0.5
                    sources.append({"fact_id": f["id"]})
        elif kind in ("action_item", "commitment"):
            if kind == "commitment" and attrs.get("direction") not in (None, "owed_by_me"):
                continue
            _add(scores, signals, {"project_manager": 0.05}, "owned_actions")
            evidence_weight += 0.1
        elif kind == "decision":
            _add(scores, signals, {"project_manager": 0.04, "solution_architect": 0.04}, "decided")
            evidence_weight += 0.1
    signals["owned_actions"] = min(signals.get("owned_actions", 0.0), 0.25)
    scores["project_manager"] = min(scores.get("project_manager", 0.0), 2.0)

    owner = str(project.get("owner") or "")
    if me_id is not None and owner and identity.is_me(owner, cfg):
        _add(scores, signals, {"project_manager": 0.40}, "project_owner")
        evidence_weight += 1.0

    for r in relationships or []:
        weights = _RELATION_ROLE.get(str(r.get("relationship_type") or "").upper())
        if weights:
            _add(scores, signals, weights, "relationships")
            evidence_weight += 0.3

    my_names = identity.alias_set(cfg)
    for fl in files:
        people = fl.get("people") or []
        if isinstance(people, str):
            try:
                people = json.loads(people)
            except ValueError:
                people = []
        names = {str((p.get("name") if isinstance(p, dict) else p) or "").lower() for p in people}
        if my_names & names:
            weights = _DOC_TYPE_ROLE.get(str(fl.get("doc_type") or "").lower())
            if weights:
                _add(scores, signals, weights, "doc_types")
                evidence_weight += 0.1
                sources.append({"file_id": fl["file_id"]})

    # Prior: "usually the PM or SA". Decays as evidence accumulates.
    prior_w = float(cfg.get("role_prior_weight", 0.35))
    decay = 1.0 / (1.0 + evidence_weight)
    for role in cfg.get("default_roles") or []:
        if role in ROLES:
            _add(scores, signals, {role: prior_w}, "prior", decay)

    out: dict[str, dict[str, Any]] = {}
    for role, raw in scores.items():
        score = 1.0 - math.exp(-raw)  # squash to (0, 1): 0.35 -> 0.30, 1.0 -> 0.63, 2.0 -> 0.86
        out[role] = {"score": round(score, 3), "signals": {k: round(v, 3) for k, v in signals.items()},
                     "sources": sources[:20]}
    return out


def infer_roles(project: dict[str, Any], use_llm: bool = False) -> dict[str, Any]:
    cfg = identity.me_config()
    me_id = identity.me_entity_id()
    facts = career_db.facts_for_project_with_owner(project["id"])
    files = career_db.project_file_cards(project["id"])
    rels = career_db.me_relationships_in_project(project["id"], me_id) if me_id else []
    scored = score_roles(project, facts, files, me_id, cfg, relationships=rels)
    written, proposed = 0, False
    if me_id is not None:
        ranked = sorted(scored.items(), key=lambda kv: -kv[1]["score"])
        for role, info in ranked:
            if info["score"] < 0.25:   # prior-only roles (~0.30) are still recorded as method=prior
                continue
            career_db.upsert_role_assignment({
                "project_id": project["id"], "person_entity_id": me_id, "is_me": True, "role": role,
                "role_label": None, "period_start": None, "period_end": None,
                "confidence": info["score"], "signals": info["signals"], "sources": info["sources"],
                "method": "inferred" if info["signals"].keys() - {"prior"} else "prior",
            })
            written += 1
        best = ranked[0][1]["score"] if ranked else 0.0
        confirmed = any(r.get("status") == "confirmed" for r in career_db.list_roles(project["id"], me_only=True))
        if ranked and best < 0.60 and not confirmed and not career_db.pending_action_exists(project["id"], "confirm_role"):
            candidates = [{"role": r, "confidence": i["score"]} for r, i in ranked[:3]]
            career_db.insert_proposed_action(
                project["id"], "confirm_role", f"Confirm your role on {project['name']}",
                "Evidence is thin; confirm with `career_history.cli confirm-role <project> --role <role>`.",
                {"candidates": candidates}, [s["fact_id"] for s in ranked[0][1]["sources"] if "fact_id" in s])
            proposed = True
    # Team members: anyone with 3+ owned facts gets a non-me role row.
    for person in career_db.project_person_mentions(project["id"]):
        if person.get("is_me"):
            continue
        theirs = [f for f in facts if f.get("owner_entity_id") == person["entity_id"]]
        if len(theirs) < 3:
            continue
        team_scores = score_roles(project, theirs, [], person["entity_id"], {"default_roles": []})
        for role, info in sorted(team_scores.items(), key=lambda kv: -kv[1]["score"])[:1]:
            if info["score"] >= 0.30:
                career_db.upsert_role_assignment({
                    "project_id": project["id"], "person_entity_id": person["entity_id"], "is_me": False,
                    "role": role, "role_label": None, "period_start": None, "period_end": None,
                    "confidence": info["score"], "signals": info["signals"], "sources": info["sources"],
                    "method": "inferred"})
    return {"roles_written": written, "proposed": proposed, "scores": {r: i["score"] for r, i in scored.items()}}


# --- achievements ----------------------------------------------------------------

def parse_metric(statement: str) -> dict[str, Any] | None:
    for rx, name in _METRIC_RES:
        m = rx.search(statement or "")
        if m:
            d = m.groupdict()
            value = d.get("value", "").replace(",", "")
            return {"name": name, "value": value, "unit": d.get("unit") or d.get("cur") or d.get("scale") or ("%" if name == "percent" else None),
                    "raw": m.group(0)}
    return None


def outcome_kind(statement: str, attrs: dict[str, Any] | None = None) -> str:
    attrs = attrs or {}
    if attrs.get("outcome_kind") in _OUTCOME_KIND_WORDS:
        return str(attrs["outcome_kind"])
    s = (statement or "").lower()
    for kind, words in _OUTCOME_KIND_WORDS.items():
        if any(w in s for w in words):
            return kind
    return "other"


def _tokens(s: str) -> frozenset[str]:
    return frozenset(t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) > 2)


def group_outcomes(facts: list[dict[str, Any]], me_id: int | None, my_role_conf: float) -> list[dict[str, Any]]:
    """Pure: candidate achievements from outcome / done-milestone / impactful
    decision / metric-bearing contribution facts, near-duplicates folded."""
    cands: list[dict[str, Any]] = []
    for f in facts:
        kind, attrs = f.get("kind"), (f.get("attributes") or {})
        stmt = str(f.get("statement") or "")
        metric = parse_metric(stmt) or (parse_metric(str(attrs.get("metric") or "")) if attrs.get("metric") else None)
        qualifies = (kind == "outcome"
                     or (kind == "milestone" and f.get("status") == "done")
                     or (kind == "decision" and attrs.get("impact"))
                     or (kind == "contribution" and metric is not None))
        if not qualifies:
            continue
        owned = me_id is not None and f.get("owner_entity_id") == me_id
        conf = float(f.get("confidence") or 0.6) * (1.0 if metric else 0.8)
        if not f.get("from_latest_version", True):
            conf *= 0.6
        is_me = owned or my_role_conf >= 0.5
        if not owned:
            conf *= 0.8
        cands.append({"statement": stmt, "metric": metric, "outcome_kind": outcome_kind(stmt, attrs),
                      "is_me": is_me, "evidence_fact_ids": [f["id"]], "evidence_file_ids": [f["file_id"]],
                      "confidence": round(min(conf, 1.0), 3),
                      "period": str(f.get("occurred_at") or "")[:10] or None})
    # fold near-duplicates (token Jaccard >= 0.85)
    out: list[dict[str, Any]] = []
    for c in sorted(cands, key=lambda x: -x["confidence"]):
        t = _tokens(c["statement"])
        for kept in out:
            kt = _tokens(kept["statement"])
            if t and kt and len(t & kt) / len(t | kt) >= 0.85:
                kept["evidence_fact_ids"] = sorted(set(kept["evidence_fact_ids"]) | set(c["evidence_fact_ids"]))
                kept["evidence_file_ids"] = sorted(set(kept["evidence_file_ids"]) | set(c["evidence_file_ids"]))
                kept["is_me"] = kept["is_me"] or c["is_me"]
                break
        else:
            out.append(c)
    for c in out:
        c["source_hash"] = hashlib.sha1(",".join(map(str, sorted(c["evidence_fact_ids"]))).encode()).hexdigest()
    return out


def derive_achievements(project: dict[str, Any], facts: list[dict[str, Any]], me_id: int | None,
                        my_role_conf: float, run_id: str | None) -> int:
    rows = group_outcomes(facts, me_id, my_role_conf)
    for r in rows:
        career_db.upsert_achievement({
            "project_id": project["id"], "statement": r["statement"], "metric": r["metric"],
            "outcome_kind": r["outcome_kind"], "is_me": r["is_me"], "evidence_fact_ids": r["evidence_fact_ids"],
            "evidence_file_ids": r["evidence_file_ids"], "confidence": r["confidence"],
            "period_start": r["period"], "period_end": r["period"], "source_hash": r["source_hash"]}, run_id)
    career_db.orphan_missing_achievements(project["id"], [r["source_hash"] for r in rows])
    return len(rows)


# --- skills ---------------------------------------------------------------------

def skill_strength(mention_count: int, role_conf: float, owned_fact_mentions: int) -> float:
    return round(math.log1p(max(0, mention_count)) * max(0.0, role_conf) * (1.0 + 0.5 * min(owned_fact_mentions, 4)), 3)


def derive_skill_evidence(project: dict[str, Any], facts: list[dict[str, Any]], me_id: int | None,
                          my_role: str | None, my_role_conf: float) -> int:
    if my_role_conf < 0.30:
        return 0
    mine_ids = {f.get("subject_entity_id") for f in facts if f.get("owner_entity_id") == me_id} | \
               {f.get("object_entity_id") for f in facts if f.get("owner_entity_id") == me_id}
    mine_facts: dict[int, list[int]] = {}
    for f in facts:
        if f.get("owner_entity_id") == me_id:
            for eid in (f.get("subject_entity_id"), f.get("object_entity_id")):
                if eid:
                    mine_facts.setdefault(eid, []).append(f["id"])
    n = 0
    for t in career_db.project_technology_mentions(project["id"]):
        owned = len(mine_facts.get(t["entity_id"], []))
        career_db.upsert_skill_evidence({
            "entity_id": t["entity_id"], "project_id": project["id"],
            "skill_kind": "technology" if t["entity_type"] == "technology" else
                          "product" if t["entity_type"] == "product" else "method",
            "role": my_role, "mention_count": int(t["mention_count"]),
            "evidence_fact_ids": mine_facts.get(t["entity_id"], [])[:20],
            "evidence_file_ids": list(t.get("file_ids") or [])[:20],
            "strength": skill_strength(int(t["mention_count"]), my_role_conf, owned),
            "first_seen": career_db._d(t.get("first_seen")), "last_seen": career_db._d(t.get("last_seen")),
        })
        n += 1
    return n


# --- orchestration -----------------------------------------------------------------

def _hash(project: dict[str, Any], facts: list[dict[str, Any]], me_id: int | None, cfg: dict[str, Any],
          roles: list[dict[str, Any]]) -> str:
    key = {"me": me_id, "roles_cfg": cfg.get("default_roles"), "owner": project.get("owner"),
           "facts": sorted((f["id"], f.get("status"), f.get("owner_entity_id")) for f in facts),
           "roles": sorted((r["role"], r["status"]) for r in roles)}
    return hashlib.sha256(json.dumps(key, default=str, sort_keys=True).encode()).hexdigest()


def refresh_career(project_ref: str | None = None, use_llm: bool = False, force: bool = False) -> dict[str, Any]:
    """Roles -> achievements -> skills for every project (hash-gated per project)."""
    if not career_db.table_exists("role_assignments"):
        console.log("[yellow]career: migration 0018 not applied; skipping[/yellow]")
        return {"skipped": True}
    cfg = identity.me_config()
    me_id = identity.me_entity_id()
    run_id = os.environ.get("ERA_RUN_ID")
    projects = [intel_db.get_project(project_ref)] if project_ref else intel_db.list_projects()
    built = skipped = 0
    for project in [p for p in projects if p]:
        facts = career_db.facts_for_project_with_owner(project["id"])
        roles_before = career_db.list_roles(project["id"], me_only=True)
        digest = _hash(project, facts, me_id, cfg, roles_before)
        if not force and career_db.career_hash(project["id"]) == digest:
            skipped += 1
            continue
        infer_roles(project, use_llm=use_llm)
        my_roles = career_db.list_roles(project["id"], me_only=True)
        confirmed = [r for r in my_roles if r.get("status") == "confirmed"]
        best = (confirmed or sorted(my_roles, key=lambda r: -float(r["confidence"]))[:1] or [None])[0]
        my_role = best["role"] if best else None
        my_conf = float(best["confidence"]) if best else 0.0
        derive_achievements(project, facts, me_id, my_conf, run_id)
        derive_skill_evidence(project, facts, me_id, my_role, my_conf)
        career_db.save_career_hash(project["id"], digest)
        built += 1
    console.log(f"[green]career:[/green] {built} project(s) rebuilt, {skipped} unchanged")
    return {"projects": built + skipped, "rebuilt": built, "unchanged": skipped}


def confirm_role(project_ref: str, role: str, reject: bool = False) -> dict[str, Any]:
    project = intel_db.get_project(project_ref)
    me_id = identity.me_entity_id()
    if project is None or me_id is None:
        raise ValueError("unknown project or me.name not configured")
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    career_db.set_role_status(project["id"], role, "rejected" if reject else "confirmed", me_id)
    return {"project": project["name"], "role": role, "status": "rejected" if reject else "confirmed"}


def role_history(me_only: bool = True) -> list[dict[str, Any]]:
    return career_db.list_roles(me_only=me_only)
