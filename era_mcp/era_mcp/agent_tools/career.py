"""Career tools (brief §11-13): project history/facts/brief, achievements,
KPIs, role history, timelines, capability evidence, similar projects."""
from __future__ import annotations

from typing import Any

from fastapi.concurrency import run_in_threadpool

from era_mcp import career as career_mod
from era_mcp import cards as cards_mod
from era_mcp import deliverables, projects, retrieval
from era_mcp.agent_tools import _common
from era_mcp.agent_tools.registry import ToolResult, tool
from era_mcp.agent_tools.sources import Source, from_card, from_fact, from_project


def _state_text(p: dict[str, Any], st: dict[str, Any] | None) -> str:
    state = (st or {}).get("state") or {}
    health = (st or {}).get("health") or {}

    def val(key: str) -> Any:
        v = state.get(key)
        return v.get("value") if isinstance(v, dict) else v
    bits = [f"Project {p['name']} (client {p.get('client')}, status {p.get('status')}, type {p.get('project_type')})"]
    for key in ("role", "stage", "phase", "business_problem", "summary"):
        v = val(key)
        if v and v != "UNKNOWN":
            bits.append(f"{key}: {v}")
    techs = val("technologies") or []
    if techs:
        bits.append("technologies: " + ", ".join(t.get("name") for t in techs[:10] if isinstance(t, dict)))
    outs = val("outcomes") or []
    if outs:
        bits.append("outcomes: " + " | ".join(o.get("statement") for o in outs[:5] if isinstance(o, dict)))
    if health:
        bits.append(f"health: {health.get('level')} ({health.get('overall')}) — {health.get('headline')}")
    return "\n".join(bits)


@tool("get_project_history", "career",
      "The project record (role, stage, business problem, technologies, outcomes, health) plus its dated timeline and recent changes.",
      {"type": "object", "properties": {"project": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["project"]})
async def get_project_history(project: str, limit: int = 40) -> ToolResult:
    p = await _common.resolve(project)
    if p is None:
        return _common.not_found(project)
    st = await run_in_threadpool(projects.project_state, p["id"])
    timeline = await run_in_threadpool(projects.project_timeline, p["id"], limit)
    changes = await run_in_threadpool(projects.project_changes, p["id"], 90, "info", 10)
    sources = [from_project(p, _state_text(p, st))]
    for t in timeline:
        if t.get("fact_id"):
            sources.append(from_fact({"id": t["fact_id"], "kind": t.get("type"), "statement": t.get("summary"),
                                      "occurred_at": t.get("at"), "file_name": t.get("file_name")}, 0.8))
    tl = "; ".join(f"{str(t.get('at'))[:10]} {t.get('type')}: {str(t.get('summary'))[:60]}" for t in timeline[-8:])
    summary = f"{p['name']}: {len(timeline)} timeline item(s), {len(changes)} recent change(s). Latest: {tl}"
    return ToolResult(ok=True, summary=summary, sources=sources,
                      data={"state": (st or {}).get("state"), "changes": changes[:5]})


@tool("get_project_facts", "career",
      "Typed facts of a project (decision, commitment, requirement, risk, action_item, open_question, milestone, contribution, outcome, lesson), newest first.",
      {"type": "object", "properties": {"project": {"type": "string"}, "kinds": {"type": "array"},
                                        "open_only": {"type": "boolean"}, "limit": {"type": "integer"}}, "required": ["project"]})
async def get_project_facts(project: str, kinds: list[str] | None = None, open_only: bool = False, limit: int = 30) -> ToolResult:
    p = await _common.resolve(project)
    if p is None:
        return _common.not_found(project)
    facts = await run_in_threadpool(projects.project_facts, p["id"], kinds, open_only, limit)
    sources = [from_fact(f, 0.9) for f in facts]
    by_kind: dict[str, int] = {}
    for f in facts:
        by_kind[f.get("kind")] = by_kind.get(f.get("kind"), 0) + 1
    return ToolResult(ok=True, summary=f"{p['name']}: {len(facts)} fact(s) {dict(sorted(by_kind.items()))}; "
                                       + _common.head([f"[F{f['id']}] {f.get('statement')}" for f in facts], 4),
                      sources=sources)


@tool("get_project_brief", "career", "One-page project brief (markdown) with [F<id>, file] citations.",
      {"type": "object", "properties": {"project": {"type": "string"}}, "required": ["project"]}, judge_visible=False,
      max_result_tokens=2000)
async def get_project_brief(project: str) -> ToolResult:
    p = await _common.resolve(project)
    if p is None:
        return _common.not_found(project)
    data = await run_in_threadpool(deliverables.gather, p)
    md = deliverables.render_brief(p, data["state"], data["facts"], data["changes"], data["conflicts"], data["similar"])
    return ToolResult(ok=True, summary=md[:1200], sources=[from_project(p, md[:4000])], data={"markdown": md})


def _ach_source(a: dict[str, Any]) -> Source:
    f = a.get("file") or {}
    metric = a.get("metric") or {}
    text = (f"{a['statement']}" + (f" [{metric.get('raw')}]" if metric.get("raw") else "")
            + f" — {a.get('project')}" + (f" ({a.get('client')})" if a.get("client") else "")
            + f"; kind {a.get('outcome_kind')}; mine={bool(a.get('is_me'))}; evidence facts "
            + ",".join(f"F{i}" for i in (a.get("evidence_fact_ids") or [])[:4]))
    return Source(kind="achievement", text=text, file_id=f.get("id"), file_name=f.get("file_name"),
                  file_path=f.get("file_path"), folder=f.get("folder"), date=str(a.get("period_end") or "")[:10] or None,
                  relevance=float(a.get("confidence") or 0.5),
                  extra={"achievement_id": a["id"], "project_id": a.get("project_id"), "evidence_fact_ids": a.get("evidence_fact_ids")})


@tool("get_achievement", "career",
      "Derived achievements (outcomes with evidence), mine by default — by project or keyword.",
      {"type": "object", "properties": {"project": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer"},
                                        "me_only": {"type": "boolean"}}})
async def get_achievement(project: str | None = None, query: str | None = None, limit: int = 10, me_only: bool = True) -> ToolResult:
    p = await _common.resolve(project)
    if project and p is None:
        return _common.not_found(project)
    rows = await run_in_threadpool(career_mod.achievements, p["id"] if p else None, query, False, me_only, limit)
    if not rows:
        return ToolResult(ok=True, summary="no derived achievements yet" + (f" for {p['name']}" if p else "") +
                          " — try get_project_facts with kinds=[outcome, milestone] or find_evidence.", data={"count": 0})
    return ToolResult(ok=True, summary=f"{len(rows)} achievement(s): " + _common.head([a["statement"] for a in rows], 5),
                      sources=[_ach_source(a) for a in rows])


@tool("get_kpi", "career", "Achievements that carry a metric (%, money, time, counts) — the KPI evidence.",
      {"type": "object", "properties": {"project": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer"}}})
async def get_kpi(project: str | None = None, query: str | None = None, limit: int = 10) -> ToolResult:
    p = await _common.resolve(project)
    if project and p is None:
        return _common.not_found(project)
    rows = await run_in_threadpool(career_mod.achievements, p["id"] if p else None, query, True, True, limit)
    return ToolResult(ok=True, summary=(f"{len(rows)} KPI item(s): " + _common.head([f"{a['statement']} [{(a.get('metric') or {}).get('raw')}]" for a in rows], 5))
                      if rows else "no metric-bearing achievements recorded", sources=[_ach_source(a) for a in rows])


@tool("get_role_history", "career", "My role on every project (confirmed or inferred), with confidence and period.",
      {"type": "object", "properties": {}})
async def get_role_history() -> ToolResult:
    rows = await run_in_threadpool(career_mod.role_history, True)
    if not rows:
        return ToolResult(ok=True, summary="no role assignments yet (run career-refresh on the Mac)", data={"count": 0})
    sources = [Source(kind="role", text=f"{r['project']} ({r.get('client') or '-'}): {r['role']} "
                                        f"[{r['status']}, confidence {float(r['confidence']):.2f}] "
                                        f"{str(r.get('period_start') or r.get('first_activity') or '')[:10]}–{str(r.get('period_end') or r.get('last_activity') or '')[:10]}",
                      relevance=float(r["confidence"]), date=str(r.get("period_start") or r.get("first_activity") or "")[:10] or None,
                      extra={"project_id": r["project_id"], "role": r["role"], "status": r["status"]}) for r in rows]
    return ToolResult(ok=True, summary=f"{len(rows)} role(s): " + _common.head([f"{r['project']}: {r['role']}" for r in rows], 8),
                      sources=sources)


@tool("build_timeline", "career",
      "A dated timeline: of my career (projects, roles, achievements) or of one project.",
      {"type": "object", "properties": {"project": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
                                        "limit": {"type": "integer"}}})
async def build_timeline(project: str | None = None, start: str | None = None, end: str | None = None, limit: int = 60) -> ToolResult:
    if project:
        return await get_project_history(project, limit)
    roles = await run_in_threadpool(career_mod.role_history, True)
    achs = await run_in_threadpool(career_mod.achievements, None, None, False, True, 40)
    items: list[tuple[str, str, Source]] = []
    for r in roles:
        d = str(r.get("period_start") or r.get("first_activity") or "")[:10]
        if d and (not start or d >= start) and (not end or d <= end):
            items.append((d, "role", Source(kind="role", text=f"{d}: {r['role']} on {r['project']} ({r.get('client') or '-'})",
                                             relevance=float(r["confidence"]), date=d, extra={"project_id": r["project_id"]})))
    for a in achs:
        d = str(a.get("period_end") or a.get("period_start") or "")[:10]
        if d and (not start or d >= start) and (not end or d <= end):
            items.append((d, "achievement", _ach_source(a)))
    items.sort(key=lambda x: x[0])
    sources = [s for _, _, s in items[:limit]]
    return ToolResult(ok=True, summary=f"{len(sources)} dated item(s) ({len(roles)} roles, {len(achs)} achievements): " +
                      "; ".join(f"{d} {k}" for d, k, _ in items[:8]), sources=sources)


@tool("find_career_evidence", "career",
      "Evidence that I have a capability (e.g. 'leading AI delivery', 'product management', 'Appian'): skill evidence, my contribution/outcome facts, matching documents.",
      {"type": "object", "properties": {"capability": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["capability"]},
      cost="embed")
async def find_career_evidence(capability: str, limit: int = 10) -> ToolResult:
    skills = await run_in_threadpool(career_mod.skill_evidence, capability, limit)
    facts = await run_in_threadpool(career_mod.contribution_facts, capability, limit)
    emb = await retrieval.embed_query(capability)
    cards = await run_in_threadpool(cards_mod.search_cards, f"my role {capability}", emb, 6, None, None)
    sources: list[Source] = []
    for s in skills:
        sources.append(Source(kind="achievement", text=f"skill {s['skill']} ({s['skill_kind']}) on {s['project']} as {s.get('role') or '?'}: "
                                                      f"{s['mention_count']} mention(s), strength {float(s['strength']):.2f}, evidence facts "
                                                      + ",".join(f"F{i}" for i in (s.get('evidence_fact_ids') or [])[:3]),
                              relevance=min(1.0, float(s["strength"]) / 3.0), extra={"skill_id": s["id"], "project_id": s["project_id"]}))
    sources += [from_fact(f, 0.95) for f in facts]
    sources += [from_card(c) for c in cards[:4]]
    summary = (f"{len(skills)} skill item(s), {len(facts)} contribution/outcome fact(s), {len(cards)} card(s) for {capability!r}: "
               + _common.head([f"{s['skill']}@{s['project']}" for s in skills] + [f.get("statement") for f in facts], 5))
    return ToolResult(ok=True, summary=summary, sources=sources,
                      data={"skills": len(skills), "facts": len(facts), "cards": len(cards)})


@tool("find_similar_projects", "career", "Projects similar to a project (shared entities, embedding) or to a free-text description.",
      {"type": "object", "properties": {"project": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer"}}},
      cost="embed")
async def find_similar_projects(project: str | None = None, query: str | None = None, limit: int = 5) -> ToolResult:
    if project:
        p = await _common.resolve(project)
        if p is None:
            return _common.not_found(project)
        rows = await run_in_threadpool(projects.similar_projects, p["id"], limit)
    elif query:
        emb = await retrieval.embed_query(query)
        rows = await run_in_threadpool(projects.projects_similar_to_vector, emb, limit)
    else:
        return ToolResult(ok=False, summary="give a project or a query", error="invalid_args")
    sources = [from_project(r, f"{r.get('name')} (client {r.get('client')}): similarity {float(r.get('score') or r.get('cosine') or 0):.2f}; "
                               f"shared {r.get('shared_entities') or r.get('shared') or ''}", relevance=float(r.get("score") or r.get("cosine") or 0.5))
               for r in rows]
    return ToolResult(ok=True, summary=f"{len(rows)} similar project(s): " + _common.head([r.get("name") for r in rows], 5), sources=sources)
