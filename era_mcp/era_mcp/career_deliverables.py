"""Career deliverables (brief §12 / Phase 5): STAR interview examples, project
comparisons, capability evidence and a career timeline — rendered
deterministically from the career layer with [F<id>, file] citations on every
line. No LLM here; the agent may narrate on top, never replace."""
from __future__ import annotations

import re
from typing import Any

from era_mcp.deliverables import _section, _src

_CAPABILITY_ACTIVITIES = {
    "leadership": {"led", "managed", "coordinated", "planned", "delivered", "owned"},
    "architecture": {"designed", "architected", "reviewed", "specified"},
    "presales": {"presented", "sold", "negotiated", "demoed", "proposed", "pitched"},
    "delivery": {"delivered", "built", "implemented", "deployed", "migrated", "tested"},
    "product": {"prioritised", "prioritized", "roadmapped", "defined", "scoped", "launched"},
    "advisory": {"advised", "recommended", "assessed", "audited"},
}


def _val(state: dict[str, Any] | None, key: str) -> Any:
    v = ((state or {}).get("state") or {}).get(key)
    if isinstance(v, dict):
        return v.get("value")
    return v


def _fact_line(f: dict[str, Any]) -> str:
    return f"- {f.get('statement')} {_src(f)}"


def _ach_line(a: dict[str, Any]) -> str:
    metric = (a.get("metric") or {}).get("raw")
    cites = ", ".join(f"F{i}" for i in (a.get("evidence_fact_ids") or [])[:3]) or "no fact ids"
    file = (a.get("file") or {}).get("file_name") or "?"
    return f"- {a.get('statement')}" + (f" — **{metric}**" if metric else "") + f" [{cites}, {file}]"


def activity_of(fact: dict[str, Any]) -> str:
    attrs = fact.get("attributes") or {}
    a = str(attrs.get("activity") or "").lower().strip()
    if a:
        return a
    stmt = str(fact.get("statement") or "").lower()
    for verbs in _CAPABILITY_ACTIVITIES.values():
        for v in verbs:
            if re.search(rf"\b{v}\b", stmt):
                return v
    return ""


def capability_bucket(activity: str) -> str:
    for cap, verbs in _CAPABILITY_ACTIVITIES.items():
        if activity in verbs:
            return cap
    return "other"


# --- STAR -----------------------------------------------------------------------------

def render_star(project: dict[str, Any], state: dict[str, Any] | None, role: dict[str, Any] | None,
                facts: list[dict[str, Any]], achievements: list[dict[str, Any]], me_only: bool = True) -> str:
    """One STAR example for one project. Every bullet cites its fact / file."""
    contributions = [f for f in facts if f.get("kind") == "contribution" and (not me_only or f.get("owner_is_me", True))]
    requirements = [f for f in facts if f.get("kind") in ("requirement", "open_question")][:4]
    decisions = [f for f in facts if f.get("kind") == "decision"][:3]
    outcomes = [f for f in facts if f.get("kind") == "outcome"][:4]
    milestones_done = [f for f in facts if f.get("kind") == "milestone" and f.get("status") == "done"][:3]
    lessons = [f for f in facts if f.get("kind") == "lesson"][:3]
    business_problem = _val(state, "business_problem")
    stage = _val(state, "stage")
    role_txt = (f"{role['role'].replace('_', ' ')} ({role.get('status')}, confidence {float(role.get('confidence') or 0):.2f})"
                if role else "UNKNOWN (no role inferred yet — run career-refresh / confirm-role)")
    header = [f"## STAR — {project.get('name')}",
              f"**Client:** {project.get('client') or 'UNKNOWN'} · **Type:** {project.get('project_type') or 'UNKNOWN'} · "
              f"**Stage:** {stage or 'UNKNOWN'} · **My role:** {role_txt}"]
    situation = []
    if business_problem and business_problem != "UNKNOWN":
        situation.append(f"- {business_problem} (project state)")
    situation += [_fact_line(f) for f in requirements[:2]]
    if not situation:
        situation.append("- _Business problem not stated in the documents (UNKNOWN)._")
    task = [f"- Role: {role_txt}"] + [_fact_line(f) for f in requirements[2:4]] + [_fact_line(f) for f in decisions[:2]]
    action = [_fact_line(f) for f in contributions[:6]]
    if not action:
        action.append("- _No contribution facts attributed to me yet (UNKNOWN). Extraction v3 records them for new/"
                      "modified files; re-extract this project with `extract-documents --upgrade --folder …`._")
    result = [_ach_line(a) for a in achievements[:4]] + [_fact_line(f) for f in outcomes[:3]] + \
             [_fact_line(f) for f in milestones_done[:2]]
    if not result:
        result.append("- _No outcome recorded (UNKNOWN)._")
    parts = ["\n".join(header),
             _section("Situation", situation),
             _section("Task", task),
             _section("Action (what I did)", action),
             _section("Result", result)]
    if lessons:
        parts.append(_section("Lessons", [_fact_line(f) for f in lessons]))
    return "\n\n".join(parts)


def pick_star_projects(capability: str | None, skills: list[dict[str, Any]], facts: list[dict[str, Any]],
                       roles: list[dict[str, Any]], limit: int = 3) -> list[int]:
    """Pure: rank project ids for STAR examples by evidence strength for the
    capability (skill strength + contribution facts), falling back to role
    confidence when no capability is given."""
    score: dict[int, float] = {}
    for s in skills:
        score[s["project_id"]] = score.get(s["project_id"], 0.0) + float(s.get("strength") or 0)
    for f in facts:
        pid = f.get("project_id")
        if pid is not None:
            score[pid] = score.get(pid, 0.0) + float(f.get("confidence") or 0.5)
    if not score:
        for r in roles:
            score[r["project_id"]] = max(score.get(r["project_id"], 0.0), float(r.get("confidence") or 0))
    return [pid for pid, _ in sorted(score.items(), key=lambda kv: -kv[1])[:limit]]


# --- Compare -----------------------------------------------------------------------------

def render_compare(a: dict[str, Any], b: dict[str, Any]) -> str:
    """Side-by-side of two project records. Each dict: {project, state, role,
    achievements, facts}."""
    def cell(d: dict[str, Any], key: str) -> str:
        p, st = d["project"], d.get("state")
        if key == "role":
            r = d.get("role")
            return f"{r['role']} ({float(r.get('confidence') or 0):.2f})" if r else "UNKNOWN"
        if key == "technologies":
            techs = _val(st, "technologies") or []
            return ", ".join(t.get("name") for t in techs[:6] if isinstance(t, dict)) or "—"
        if key == "outcomes":
            achs = d.get("achievements") or []
            return "; ".join(f"{x['statement'][:60]} [{','.join(f'F{i}' for i in (x.get('evidence_fact_ids') or [])[:2])}]"
                             for x in achs[:3]) or "—"
        if key == "timeline":
            tl = _val(st, "timeline") or []
            dates = [t.get("date") for t in tl if isinstance(t, dict) and t.get("date")]
            return f"{min(dates)} → {max(dates)}" if dates else "—"
        if key == "health":
            h = (st or {}).get("health") or {}
            return f"{h.get('level', '?')} ({h.get('overall', '?')})"
        if key in ("stage", "business_problem", "phase"):
            return str(_val(st, key) or "UNKNOWN")[:120]
        return str(p.get(key) or "UNKNOWN")
    rows = [("Client", "client"), ("Type", "project_type"), ("Status", "status"), ("Stage", "stage"),
            ("Business problem", "business_problem"), ("My role", "role"), ("Technologies", "technologies"),
            ("Outcomes", "outcomes"), ("Timeline", "timeline"), ("Health", "health")]
    lines = [f"## Compare: {a['project'].get('name')} vs {b['project'].get('name')}", "",
             f"| | {a['project'].get('name')} | {b['project'].get('name')} |", "|---|---|---|"]
    for label, key in rows:
        lines.append(f"| {label} | {cell(a, key)} | {cell(b, key)} |")
    fa = {f.get("id") for f in a.get("facts") or []}
    fb = {f.get("id") for f in b.get("facts") or []}
    lines += ["", f"_Facts considered: {len(fa)} vs {len(fb)}; outcomes cite fact ids [F<id>]._"]
    return "\n".join(lines)


# --- Capability evidence ------------------------------------------------------------------

def render_capability_evidence(capability: str, skills: list[dict[str, Any]], facts: list[dict[str, Any]],
                               achievements: list[dict[str, Any]]) -> str:
    buckets: dict[str, list[str]] = {}
    for f in facts:
        bucket = capability_bucket(activity_of(f)) if f.get("kind") == "contribution" else "outcomes"
        buckets.setdefault(bucket, []).append(f"- {f.get('project') or '-'}: {f.get('statement')} {_src(f)}")
    parts = [f"## Evidence: {capability}"]
    if skills:
        parts.append(_section("Technologies / skills with evidence", [
            f"- {s['skill']} on {s['project']} as {s.get('role') or '?'} — strength {float(s['strength']):.2f}, "
            f"{s['mention_count']} mention(s) [{', '.join(f'F{i}' for i in (s.get('evidence_fact_ids') or [])[:3]) or 'mentions only'}]"
            for s in skills[:10]]))
    for name in ("leadership", "architecture", "presales", "delivery", "product", "advisory", "other", "outcomes"):
        if buckets.get(name):
            parts.append(_section(name.capitalize(), buckets[name][:8]))
    if achievements:
        parts.append(_section("Achievements", [_ach_line(a) for a in achievements[:8]]))
    if len(parts) == 1:
        parts.append("_No evidence recorded for this capability yet (UNKNOWN)._")
    return "\n\n".join(parts)


# --- Timeline -------------------------------------------------------------------------------

def render_career_timeline(roles: list[dict[str, Any]], achievements: list[dict[str, Any]]) -> str:
    items: list[tuple[str, str]] = []
    for r in roles:
        start = str(r.get("period_start") or r.get("first_activity") or "")[:10]
        end = str(r.get("period_end") or r.get("last_activity") or "")[:10]
        if start:
            items.append((start, f"- {start} → {end or 'now'}: **{r['role'].replace('_', ' ')}** on {r['project']} "
                                 f"({r.get('client') or '-'}) [{r.get('status')}, {float(r.get('confidence') or 0):.2f}]"))
    for a in achievements:
        d = str(a.get("period_end") or a.get("period_start") or "")[:10]
        if d:
            items.append((d, f"- {d}: {a['statement']} — {a.get('project') or '-'} "
                             f"[{', '.join(f'F{i}' for i in (a.get('evidence_fact_ids') or [])[:2])}]"))
    items.sort(key=lambda x: x[0])
    body = [t for _, t in items] or ["_No dated roles or achievements yet._"]
    return "## Career timeline\n\n" + "\n".join(body)
