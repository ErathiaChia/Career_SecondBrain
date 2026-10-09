"""Project deliverables: brief, meeting prep, next actions, what's happening.

Each deliverable is assembled deterministically from project state, typed facts,
changes, conflicts and similarity (so it works with the LLM off), rendered as
markdown with every item tied to a source file and fact id. ``narrative=True``
adds a short LLM write-up that must label claims FACT / INFERENCE / UNKNOWN and
cite fact ids as [F<id>]; it never replaces the sourced sections.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from era_mcp import epistemic, llm, projects

_PRIORITY = {"high": 0, "medium": 1, "low": 2}
CLOSED = {"done", "cancelled", "rejected", "mitigated"}


def _today() -> str:
    return date.today().isoformat()


def _due(f: dict[str, Any]) -> str | None:
    value = (f.get("attributes") or {}).get("due_at") or (f.get("occurred_at") if f.get("kind") == "milestone" else None)
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return m.group(0) if m else None


def _src(f: dict[str, Any]) -> str:
    fid = f.get("fact_id") or f.get("id")
    name = f.get("file_name") or (f.get("source") or {}).get("file_name") or "?"
    flags = []
    if f.get("from_latest_version") is False:
        flags.append("older version")
    if f.get("stale_reasons"):
        flags.append("stale: " + ", ".join(f["stale_reasons"]))
    if f.get("conflict_ids"):
        flags.append("conflicting")
    tail = f" ({'; '.join(flags)})" if flags else ""
    return f"[F{fid}, {name}]{tail}"


def _line(f: dict[str, Any], with_owner: bool = True, with_due: bool = True) -> str:
    bits = []
    if with_owner and f.get("owner"):
        bits.append(f"owner: {f['owner']}")
    if with_due and _due(f):
        bits.append(f"due {_due(f)}")
    if f.get("status"):
        bits.append(str(f["status"]))
    if f.get("priority"):
        bits.append(str(f["priority"]))
    meta = f" — {', '.join(bits)}" if bits else ""
    return f"- {f['statement']}{meta} {_src(f)}"


def _section(title: str, items: list[str], empty: str = "None recorded.") -> str:
    return f"### {title}\n" + ("\n".join(items) if items else f"_{empty}_")


def _open(facts: list[dict[str, Any]], kinds: set[str]) -> list[dict[str, Any]]:
    return [f for f in facts if f["kind"] in kinds and (f.get("status") or "open") not in CLOSED]


def _by_due(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(facts, key=lambda f: (_due(f) is None, _due(f) or "", _PRIORITY.get(f.get("priority"), 3)))


def _state_value(state: dict[str, Any] | None, key: str) -> Any:
    return ((state or {}).get("state") or {}).get(key, {}).get("value")


# --- Next actions ---------------------------------------------------------------

def rank_next_actions(facts: list[dict[str, Any]], conflicts: list[dict[str, Any]],
                      today: str | None = None, limit: int = 15) -> list[dict[str, Any]]:
    """Score what to do next, with the reason for each suggestion."""
    today = today or _today()
    soon = (date.fromisoformat(today) + timedelta(days=7)).isoformat()
    out: list[dict[str, Any]] = []
    for f in _open(facts, {"action_item", "commitment"}):
        due = _due(f)
        score, reasons = 10, []
        if due and due < today:
            score += 50
            reasons.append(f"overdue since {due}")
        elif due and due <= soon:
            score += 30
            reasons.append(f"due {due}")
        if f.get("status") == "blocked":
            score += 25
            reasons.append("blocked")
        if f.get("priority") == "high":
            score += 20
            reasons.append("high priority")
        if not f.get("owner"):
            score += 5
            reasons.append("no owner")
        out.append({"action": f["statement"], "type": f["kind"], "score": score,
                    "reasons": reasons or ["open"], "owner": f.get("owner"), "due": due,
                    "source": _src(f), "fact_id": f.get("fact_id")})
    for f in _open(facts, {"open_question"}):
        out.append({"action": f"Get an answer: {f['statement']}", "type": "open_question",
                    "score": 15 + (10 if f.get("priority") == "high" else 0),
                    "reasons": ["unresolved question"], "owner": f.get("owner"), "due": None,
                    "source": _src(f), "fact_id": f.get("fact_id")})
    for f in _open(facts, {"risk"}):
        if f.get("priority") == "high":
            mitigation = (f.get("attributes") or {}).get("mitigation")
            out.append({"action": f"Mitigate risk: {f['statement']}", "type": "risk", "score": 35,
                        "reasons": ["high open risk"] + ([f"planned mitigation: {mitigation}"] if mitigation else
                                                         ["no mitigation recorded"]),
                        "owner": f.get("owner"), "due": None, "source": _src(f), "fact_id": f.get("fact_id")})
    for c in conflicts:
        if c.get("status") == "needs_confirmation":
            out.append({"action": f"Confirm which is correct: \"{c['fact_a']}\" vs \"{c['fact_b']}\"",
                        "type": "conflict", "score": 30, "reasons": [c.get("explanation") or c["conflict_type"]],
                        "owner": None, "due": None,
                        "source": f"[F{c['fact_a_id']}, {c['fact_a_file']}] vs [F{c['fact_b_id']}, {c['fact_b_file']}]",
                        "conflict_id": c["id"]})
    for f in facts:
        if "not_reverified" in (f.get("stale_reasons") or []) and (f.get("status") or "open") not in CLOSED:
            out.append({"action": f"Re-verify: {f['statement']}", "type": "stale", "score": 12,
                        "reasons": ["not re-asserted recently"], "owner": f.get("owner"), "due": None,
                        "source": _src(f), "fact_id": f.get("fact_id")})
    out.sort(key=lambda a: -a["score"])
    return out[:limit]


def render_next_actions(project_name: str, actions: list[dict[str, Any]]) -> str:
    lines = [f"- **{a['action']}** — {'; '.join(a['reasons'])}"
             f"{' — owner: ' + a['owner'] if a.get('owner') else ''} {a['source']}" for a in actions]
    return f"## Next actions: {project_name}\n" + ("\n".join(lines) or "_Nothing open._")


# --- Brief ----------------------------------------------------------------------

def render_brief(project: dict[str, Any], state: dict[str, Any] | None, facts: list[dict[str, Any]],
                 changes: list[dict[str, Any]], conflicts: list[dict[str, Any]],
                 similar: list[dict[str, Any]], today: str | None = None) -> str:
    today = today or _today()
    health = (state or {}).get("health") or {}
    phase = _state_value(state, "phase") or "UNKNOWN"
    summary = _state_value(state, "summary")
    objectives = _state_value(state, "objectives") or []
    decisions = [f for f in facts if f["kind"] == "decision"][:6]
    risks = sorted(_open(facts, {"risk", "dependency"}), key=lambda f: _PRIORITY.get(f.get("priority"), 3))[:6]
    actions = _by_due(_open(facts, {"action_item", "commitment"}))[:8]
    questions = _open(facts, {"open_question"})[:6]
    milestones = [f for f in _by_due([f for f in facts if f["kind"] == "milestone"])
                  if (_due(f) or "") >= today][:5]
    header = [
        f"## Project brief: {project['name']}",
        f"**Client:** {project.get('client') or 'UNKNOWN'} · **Type:** {project.get('project_type') or 'UNKNOWN'} · "
        f"**Status:** {project.get('status') or 'UNKNOWN'} · **Phase:** {phase} · "
        f"**Last activity:** {str(project.get('last_activity') or 'UNKNOWN')[:10]}",
    ]
    if health:
        header.append(f"**Health:** {health.get('level', '?').upper()} ({health.get('overall', '?')}/100) — "
                      f"{health.get('headline', '')}")
    if summary and summary != "UNKNOWN":
        header.append(f"\n{summary}")
    if not state:
        header.append("\n_No project state built yet; this brief is assembled directly from extracted facts._")
    parts = ["\n".join(header)]
    if objectives:
        parts.append(_section("Objectives", [f"- {o}" for o in objectives]))
    parts += [
        _section("Recent decisions", [_line(f, with_owner=False, with_due=False) for f in decisions]),
        _section("Upcoming milestones", [_line(f, with_owner=False) for f in milestones]),
        _section("Open risks and dependencies", [_line(f) for f in risks]),
        _section("Open actions", [_line(f) for f in actions]),
        _section("Open questions", [_line(f, with_due=False) for f in questions]),
    ]
    if conflicts:
        parts.append(_section("Needs confirmation (conflicting sources)", [
            f"- \"{c['fact_a']}\" [F{c['fact_a_id']}, {c['fact_a_file']}] vs \"{c['fact_b']}\" "
            f"[F{c['fact_b_id']}, {c['fact_b_file']}] — {c.get('explanation') or c['conflict_type']}"
            for c in conflicts[:5]]))
    if changes:
        parts.append(_section("What changed recently", [
            f"- {str(c['detected_at'])[:10]} [{c['severity']}] {c['summary']}" for c in changes[:8]]))
    if similar:
        parts.append(_section("Similar past projects", [
            f"- {s['name']} (score {float(s['score']):.2f}"
            f"{'; shared: ' + ', '.join(s['shared_entities'][:5]) if s.get('shared_entities') else ''})"
            for s in similar[:3]]))
    return "\n\n".join(parts)


# --- Meeting prep ---------------------------------------------------------------

def render_meeting_prep(project: dict[str, Any], facts: list[dict[str, Any]], changes: list[dict[str, Any]],
                        conflicts: list[dict[str, Any]], attendees: list[str], topic: str | None,
                        today: str | None = None) -> str:
    today = today or _today()
    topic_tokens = {t for t in re.split(r"[^a-z0-9]+", (topic or "").lower()) if len(t) > 2}

    def on_topic(f: dict[str, Any]) -> bool:
        if not topic_tokens:
            return True
        text = f"{f.get('statement', '')} {f.get('topic') or ''}".lower()
        return any(t in text for t in topic_tokens)

    relevant = [f for f in facts if on_topic(f)]
    actions = _by_due(_open(relevant, {"action_item", "commitment"}))
    questions = _open(relevant, {"open_question"})
    risks = [f for f in _open(relevant, {"risk"}) if f.get("priority") in {"high", None}][:5]
    decisions = [f for f in relevant if f["kind"] == "decision"][:5]
    overdue = [f for f in actions if (_due(f) or "9999") < today]
    agenda = []
    if changes:
        agenda.append("Updates since last time")
    if overdue:
        agenda.append(f"Overdue items ({len(overdue)})")
    if conflicts:
        agenda.append(f"Resolve conflicting information ({len(conflicts)})")
    if risks:
        agenda.append("Top risks and mitigations")
    if questions:
        agenda.append(f"Open questions ({len(questions)})")
    agenda.append("Agree next actions, owners and dates")
    parts = [f"## Meeting prep: {project['name']}" + (f" — {topic}" if topic else ""),
             _section("Suggested agenda", [f"{i}. {a}" for i, a in enumerate(agenda, 1)])]
    if changes:
        parts.append(_section("What changed recently", [f"- {c['summary']}" for c in changes[:6]]))
    for person in attendees:
        p = person.lower()
        mine = [f for f in actions if p in (f.get("owner") or "").lower()]
        theirs_q = [f for f in questions if p in (f.get("owner") or "").lower()]
        parts.append(_section(f"With {person}", [_line(f, with_owner=False) for f in mine + theirs_q],
                              empty="No open items recorded for this person."))
    parts += [
        _section("Open actions to review", [_line(f) for f in actions[:10]]),
        _section("Questions to ask", [_line(f, with_due=False) for f in questions[:8]]),
        _section("Risks to raise", [_line(f) for f in risks]),
        _section("Recent decisions to confirm", [_line(f, with_owner=False, with_due=False) for f in decisions]),
    ]
    if conflicts:
        parts.append(_section("Conflicts to settle", [
            f"- \"{c['fact_a']}\" vs \"{c['fact_b']}\" — {c.get('explanation') or c['conflict_type']}"
            for c in conflicts[:5]]))
    return "\n\n".join(parts)


# --- What's happening -----------------------------------------------------------

def render_whats_happening(changes: list[dict[str, Any]], projects_health: list[dict[str, Any]],
                           upcoming: list[dict[str, Any]], since_days: int) -> str:
    parts = [f"## What's happening (last {since_days} days)"]
    by_project: dict[str, list[dict[str, Any]]] = {}
    for c in changes:
        by_project.setdefault(c.get("project") or "Unassigned", []).append(c)
    lines = []
    for name, rows in sorted(by_project.items(), key=lambda kv: -len(kv[1])):
        impact = next((r["impact"] for r in rows if r.get("impact")), None) or {}
        lines.append(f"- **{name}** ({len(rows)} change(s)): {impact.get('summary') or rows[0]['summary']}")
        for b in (impact.get("impact") or [])[:2]:
            lines.append(f"  - {b}")
    parts.append(_section("Changes by project", lines, empty="No notable changes."))
    attention = [p for p in projects_health if p.get("level") in {"red", "amber"}]
    parts.append(_section("Projects needing attention", [
        f"- {p['name']}: {p['level'].upper()} — {p.get('headline', '')}" for p in attention[:8]],
        empty="No project is amber or red."))
    parts.append(_section("Coming up (next 14 days)", [
        f"- {u['due']} — {u['project']}: {u['statement']} [F{u['fact_id']}]" for u in upcoming[:10]]))
    return "\n\n".join(parts)


# --- Narrative (optional LLM) ---------------------------------------------------

_NARRATIVE_SYS = (
    "You write a short narrative for a project lead from the structured material "
    "given. Use only that material. Start each claim with FACT: (stated in the "
    "material, cite [F<id>]), INFERENCE: (your reasoning, cite the facts it rests on) "
    "or UNKNOWN: (important but not in the material). Max 8 sentences. Mention "
    "conflicting information explicitly instead of picking a side."
)


async def narrative(markdown: str, purpose: str) -> dict[str, Any]:
    try:
        text = await llm.chat([{"role": "system", "content": _NARRATIVE_SYS},
                               {"role": "user", "content": f"Purpose: {purpose}\n\n{markdown[:12000]}"}],
                              timeout=120)
    except llm.LLMUnavailable as e:
        return {"text": None, "error": f"narrative unavailable: {e}"}
    return {"text": text, "epistemic": epistemic.parse(text)}


# --- Data assembly (sync, run in threadpool) ------------------------------------

def gather(project: dict[str, Any], since_days: int = 14) -> dict[str, Any]:
    pid = project["id"]
    return {
        "state": projects.project_state(pid),
        "facts": projects.project_facts(pid, limit=400),
        "changes": projects.project_changes(pid, since_days=since_days, min_severity="notice", limit=30),
        "conflicts": projects.project_conflicts(pid, limit=20),
        "similar": projects.similar_projects(pid, limit=3),
    }


def portfolio(since_days: int = 7) -> dict[str, Any]:
    changes = projects.project_changes(None, since_days=since_days, min_severity="notice", limit=200)
    health: list[dict[str, Any]] = []
    if projects._present("project_state"):
        health = projects._query("""
            SELECT p.id, p.name, ps.health ->> 'level' AS level, ps.health ->> 'headline' AS headline,
                   CAST(ps.health ->> 'overall' AS integer) AS overall
              FROM project_state ps JOIN projects p ON p.id = ps.project_id
             WHERE ps.is_current AND p.status IS DISTINCT FROM 'REMOVED'
             ORDER BY CAST(ps.health ->> 'overall' AS integer) ASC NULLS LAST
        """)
    upcoming: list[dict[str, Any]] = []
    if projects._present("projects"):
        rows = projects._query("""
            SELECT pf.id AS fact_id, p.name AS project, pf.statement, pf.kind,
                   pf.occurred_at, pf.attributes
              FROM project_facts pf JOIN projects p ON p.id = pf.project_id
             WHERE pf.kind IN ('milestone', 'action_item', 'commitment')
               AND COALESCE(to_jsonb(pf) ->> 'status', 'open') NOT IN ('done', 'cancelled', 'rejected')
        """)
        today = _today()
        horizon = (date.today() + timedelta(days=14)).isoformat()
        for r in rows:
            due = _due(r)
            if due and today <= due <= horizon:
                upcoming.append({**r, "due": due})
        upcoming.sort(key=lambda u: u["due"])
    return {"changes": changes, "health": health, "upcoming": upcoming}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
