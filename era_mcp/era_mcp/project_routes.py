"""Project-intelligence endpoints (registered as Open WebUI tools via their
``operation_id``). Reads come from ``projects.py``; generated deliverables from
``deliverables.py``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from era_mcp import deliverables, docdiff, projects, retrieval

router = APIRouter()


def _project_or_404(ref: str) -> dict:
    project = projects.resolve_project(ref)
    if project is None:
        raise HTTPException(status_code=404, detail={
            "error": f"No project matches {ref!r}",
            "did_you_mean": projects.project_suggestions(ref),
            "hint": "Retry with a project_key from did_you_mean or list_projects. If the work is "
                    "not a registered project (events, product, ops), answer with ask_vault instead.",
        })
    return project


def _coverage(p: dict) -> dict:
    """Fact-extraction coverage plus, when it is thin, a note telling the agent that
    an empty result means 'not extracted yet' and to fall back to document search."""
    cov = projects.fact_coverage(p["id"])
    out: dict = {"coverage": cov}
    if cov["files"] and cov["files_with_facts"] == 0:
        out["note"] = (f"No facts have been extracted from this project's {cov['files']} files yet, so "
                       "empty lists here mean UNKNOWN, not 'nothing open'. Answer from the documents "
                       f"with ask_vault (mention \"{p['name']}\" / {p.get('client') or ''} in the query).")
    elif cov["files"] and cov["files_with_facts"] * 3 < cov["files"]:
        out["note"] = (f"Only {cov['files_with_facts']} of {cov['files']} files have extracted facts; "
                       "results may be incomplete. Cross-check with ask_vault.")
    return out


def _with_note(markdown: str, cov: dict) -> str:
    return f"> **Coverage:** {cov['note']}\n\n{markdown}" if cov.get("note") else markdown


@router.get("/projects", operation_id="list_projects")
async def list_projects(
    status: Optional[str] = Query(default=None, description='Filter by status, e.g. "ACTIVE", "DORMANT", "ARCHIVED".'),
    client: Optional[str] = Query(default=None, description="Filter by client name fragment."),
) -> dict:
    """List known projects with client, type, status, owner, last activity, and the
    confidence and source of each field. Use for "what projects do I have"."""
    rows = await run_in_threadpool(projects.list_projects, status, client)
    return {"count": len(rows), "projects": rows}


@router.get("/projects/similar-to", operation_id="find_projects_similar_to")
async def find_projects_similar_to(
    query: str = Query(description='Describe the work, e.g. "data platform for a bank".'),
    limit: int = Query(default=5, ge=1, le=20),
) -> dict:
    """Past projects most similar to a description (content similarity). Use for
    "have I done something like X before?"."""
    try:
        vec = await retrieval.embed_query(query)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"embedding unavailable: {e}") from e
    rows = await run_in_threadpool(projects.projects_similar_to_vector, vec, limit)
    return {"query": query, "count": len(rows), "projects": rows}


@router.get("/reuse", operation_id="find_reusable_assets")
async def find_reusable_assets(
    query: Optional[str] = Query(default=None, description="Asset name fragment, e.g. \"SOW template\"."),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Reusable assets (templates, decks, specs) seen across several projects or
    customers, with where the canonical copy lives."""
    rows = await run_in_threadpool(projects.reuse_candidates, None, query, False, limit)
    return {"count": len(rows), "assets": rows}


@router.get("/projects/{project}", operation_id="get_project")
async def get_project(project: str) -> dict:
    """Resolve a project by id, key, name, alias, or name fragment ("HLB", "CL89")."""
    return await run_in_threadpool(_project_or_404, project)


@router.get("/projects/{project}/documents", operation_id="get_project_documents")
async def get_project_documents(
    project: str,
    group: str = Query(default="version", description='"version" groups files into version families; "none" lists files.'),
) -> dict:
    """A project's documents. Grouped by version family, each family lists its
    versions oldest to newest and names the latest."""
    p = await run_in_threadpool(_project_or_404, project)
    docs = await run_in_threadpool(projects.project_documents, p["id"], group)
    return {"project": p, **docs}


@router.get("/projects/{project}/entities", operation_id="get_project_entities")
async def get_project_entities(
    project: str,
    entity_type: Optional[str] = Query(default=None, description='e.g. "person", "company", "technology".'),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Entities scoped to one project: who is involved, which clients, vendors and
    technologies appear, ranked by how many of the project's files mention them."""
    p = await run_in_threadpool(_project_or_404, project)
    rows = await run_in_threadpool(projects.project_entities, p["id"], entity_type, limit)
    return {"project": p["name"], "count": len(rows), "entities": rows}


@router.get("/projects/{project}/state", operation_id="get_project_state")
async def get_project_state(project: str) -> dict:
    """Current project state: phase, objectives, priorities, decisions, requirements,
    risks, blockers, open questions, next actions, milestones and health. Every field
    carries value, confidence, sources (file + fact id) and last_verified. A field
    the evidence does not support is "UNKNOWN"; say so instead of guessing."""
    p = await run_in_threadpool(_project_or_404, project)
    state = await run_in_threadpool(projects.project_state, p["id"])
    cov = await run_in_threadpool(_coverage, p)
    if state is None:
        return {"project": p, "state": None, **cov,
                "note": cov.get("note") or "No state built yet. Run `python -m career_history.cli project-state` on the indexer."}
    return {"project": p, **state, **cov}


async def _facts(project: str, kinds: list[str] | None, open_only: bool, limit: int) -> dict:
    p = await run_in_threadpool(_project_or_404, project)
    rows = await run_in_threadpool(projects.project_facts, p["id"], kinds, open_only, limit)
    cov = await run_in_threadpool(_coverage, p)
    return {"project": p["name"], "count": len(rows), "facts": rows, **cov}


_KIND_HELP = ('One of "decision", "commitment", "event", "requirement", "risk", "action_item", '
              '"open_question", "dependency", "milestone". Repeat for several.')


@router.get("/projects/{project}/facts", operation_id="get_project_facts")
async def get_project_facts(
    project: str,
    kind: Optional[list[str]] = Query(default=None, description=_KIND_HELP),
    open_only: bool = Query(default=False, description="Exclude done/cancelled/rejected/mitigated."),
    limit: int = Query(default=50, ge=1, le=300),
) -> dict:
    """Typed facts for a project with owner, status, priority, source file,
    whether the source is the latest version, stale reasons and conflict ids."""
    return await _facts(project, kind, open_only, limit)


@router.get("/projects/{project}/decisions", operation_id="get_project_decisions")
async def get_project_decisions(project: str, limit: int = Query(default=30, ge=1, le=200)) -> dict:
    """Decisions made on a project, newest first, with rationale/alternatives when recorded."""
    return await _facts(project, ["decision"], False, limit)


@router.get("/projects/{project}/requirements", operation_id="get_project_requirements")
async def get_project_requirements(project: str, limit: int = Query(default=50, ge=1, le=300)) -> dict:
    """Requirements for a project with status and source."""
    return await _facts(project, ["requirement"], False, limit)


@router.get("/projects/{project}/risks", operation_id="get_project_risks")
async def get_project_risks(project: str, include_closed: bool = Query(default=False),
                            limit: int = Query(default=30, ge=1, le=200)) -> dict:
    """Open risks and dependencies for a project, with severity and mitigation."""
    return await _facts(project, ["risk", "dependency"], not include_closed, limit)


@router.get("/projects/{project}/actions", operation_id="get_project_actions")
async def get_project_actions(project: str, include_closed: bool = Query(default=False),
                              limit: int = Query(default=30, ge=1, le=200)) -> dict:
    """Action items and commitments with owner, due date and status."""
    return await _facts(project, ["action_item", "commitment"], not include_closed, limit)


@router.get("/projects/{project}/questions", operation_id="get_project_open_questions")
async def get_project_open_questions(project: str, limit: int = Query(default=30, ge=1, le=200)) -> dict:
    """Unresolved questions on a project."""
    return await _facts(project, ["open_question"], True, limit)


@router.get("/projects/{project}/timeline", operation_id="get_project_timeline")
async def get_project_timeline(project: str, limit: int = Query(default=100, ge=1, le=500)) -> dict:
    """Chronological timeline: events, milestones, decisions, due dates, document
    updates and detected changes, oldest first."""
    p = await run_in_threadpool(_project_or_404, project)
    rows = await run_in_threadpool(projects.project_timeline, p["id"], limit)
    return {"project": p["name"], "count": len(rows), "timeline": rows}


@router.get("/projects/{project}/changes", operation_id="get_project_changes")
async def get_project_changes(
    project: str,
    since_days: int = Query(default=14, ge=1, le=365),
    min_severity: str = Query(default="info", description='"info", "notice", "warning" or "critical".'),
    limit: int = Query(default=50, ge=1, le=300),
) -> dict:
    """What changed in a project recently (documents, versions, facts) and the impact
    card for each batch: why it matters, affected areas, and the rationale only if the
    documents state one ("rationale not found" otherwise)."""
    p = await run_in_threadpool(_project_or_404, project)
    rows = await run_in_threadpool(projects.project_changes, p["id"], since_days, min_severity, limit)
    return {"project": p["name"], "count": len(rows), "changes": rows}


@router.get("/projects/{project}/conflicts", operation_id="get_project_conflicts")
async def get_project_conflicts(
    project: str,
    include_resolved: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=300),
) -> dict:
    """Contradictions between project documents (dates, decisions, requirements,
    statuses): both statements, their source files, and which is likely the latest.
    Present these as needing confirmation, never silently pick one."""
    p = await run_in_threadpool(_project_or_404, project)
    rows = await run_in_threadpool(projects.project_conflicts, p["id"], include_resolved, limit)
    return {"project": p["name"], "count": len(rows), "conflicts": rows}


@router.get("/projects/{project}/stale", operation_id="get_project_stale_knowledge")
async def get_project_stale_knowledge(project: str, limit: int = Query(default=100, ge=1, le=500)) -> dict:
    """Facts that are probably out of date, with the reason and the newer evidence."""
    p = await run_in_threadpool(_project_or_404, project)
    rows = await run_in_threadpool(projects.project_stale, p["id"], limit)
    return {"project": p["name"], "count": len(rows), "stale": rows}


@router.get("/projects/{project}/similar", operation_id="get_similar_projects")
async def get_similar_projects(project: str, limit: int = Query(default=5, ge=1, le=20)) -> dict:
    """Projects similar to this one, with the score breakdown (content cosine,
    shared-entity overlap) and the shared clients/technologies/people."""
    p = await run_in_threadpool(_project_or_404, project)
    rows = await run_in_threadpool(projects.similar_projects, p["id"], limit)
    return {"project": p["name"], "count": len(rows), "similar": rows}


@router.get("/projects/{project}/reuse", operation_id="get_project_reuse_candidates")
async def get_project_reuse_candidates(
    project: str,
    include_similar: bool = Query(default=True, description="Also suggest assets from similar projects."),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Reusable assets for a project: ones it already uses, then ones used by
    similar projects that it does not have yet (with the reason)."""
    p = await run_in_threadpool(_project_or_404, project)
    rows = await run_in_threadpool(projects.reuse_candidates, p, None, include_similar, limit)
    return {"project": p["name"], "count": len(rows), "assets": rows}


# --- Deliverables ---------------------------------------------------------------

@router.get("/projects/{project}/brief", operation_id="get_project_brief")
async def get_project_brief(
    project: str,
    narrative: bool = Query(default=False, description="Add a short LLM narrative (FACT/INFERENCE/UNKNOWN labelled)."),
) -> dict:
    """One-page project brief: client, phase, health, objectives, decisions,
    milestones, risks, open actions and questions, conflicts, recent changes and
    similar past projects. Every item cites [F<fact id>, file]. Return the markdown
    to the user as is."""
    p = await run_in_threadpool(_project_or_404, project)
    data = await run_in_threadpool(deliverables.gather, p)
    md = deliverables.render_brief(p, data["state"], data["facts"], data["changes"],
                                   data["conflicts"], data["similar"])
    cov = await run_in_threadpool(_coverage, p)
    out = {"project": p["name"], "markdown": _with_note(md, cov), "generated_at": deliverables.now_iso(), **cov}
    if narrative:
        out["narrative"] = await deliverables.narrative(md, "project brief")
    return out


@router.get("/projects/{project}/meeting-prep", operation_id="prepare_project_meeting")
async def prepare_project_meeting(
    project: str,
    attendees: Optional[list[str]] = Query(default=None, description="Attendee names; repeat for several."),
    topic: Optional[str] = Query(default=None, description="Focus the prep on a topic."),
    narrative: bool = Query(default=False),
) -> dict:
    """Meeting prep: suggested agenda, what changed, per-attendee open items,
    actions to review, questions to ask, risks to raise and conflicts to settle."""
    p = await run_in_threadpool(_project_or_404, project)
    data = await run_in_threadpool(deliverables.gather, p, 21)
    md = deliverables.render_meeting_prep(p, data["facts"], data["changes"], data["conflicts"],
                                          attendees or [], topic)
    cov = await run_in_threadpool(_coverage, p)
    out = {"project": p["name"], "markdown": _with_note(md, cov), "generated_at": deliverables.now_iso(), **cov}
    if narrative:
        out["narrative"] = await deliverables.narrative(md, "meeting preparation")
    return out


@router.get("/projects/{project}/next-actions", operation_id="get_project_next_actions")
async def get_project_next_actions(project: str, limit: int = Query(default=15, ge=1, le=50)) -> dict:
    """Ranked next actions with the reason for each: overdue or due-soon items,
    blocked work, high risks without mitigation, open questions, conflicts to
    confirm and stale items to re-verify."""
    p = await run_in_threadpool(_project_or_404, project)
    data = await run_in_threadpool(deliverables.gather, p)
    actions = deliverables.rank_next_actions(data["facts"], data["conflicts"], limit=limit)
    cov = await run_in_threadpool(_coverage, p)
    return {"project": p["name"], "actions": actions,
            "markdown": _with_note(deliverables.render_next_actions(p["name"], actions), cov), **cov}


@router.get("/whats-happening", operation_id="whats_happening")
async def whats_happening(
    since_days: int = Query(default=7, ge=1, le=90),
    narrative: bool = Query(default=False),
) -> dict:
    """Portfolio view: notable changes by project with impact, projects that are
    amber/red and why, and what is due in the next 14 days."""
    data = await run_in_threadpool(deliverables.portfolio, since_days)
    md = deliverables.render_whats_happening(data["changes"], data["health"], data["upcoming"], since_days)
    out = {"markdown": md, "generated_at": deliverables.now_iso(),
           "counts": {"changes": len(data["changes"]), "upcoming": len(data["upcoming"])}}
    if narrative:
        out["narrative"] = await deliverables.narrative(md, "weekly portfolio update")
    return out


class ProposeActionRequest(BaseModel):
    project: Optional[str] = Field(default=None, description="Project id/key/name, if any.")
    action_type: str = Field(description="follow_up | create_task | update_status | resolve_conflict | "
                                         "schedule_meeting | draft_message | reverify_fact | other")
    title: str = Field(description="Short imperative title.")
    detail: Optional[str] = Field(default=None, description="What exactly should happen and why.")
    payload: dict = Field(default_factory=dict, description="Draft content, recipients, dates, etc.")
    source_fact_ids: list[int] = Field(default_factory=list, description="Fact ids that justify the action.")


@router.post("/actions/propose", operation_id="propose_action")
async def propose_action(req: ProposeActionRequest) -> dict:
    """Queue a suggested action for the user's approval. Nothing is sent or
    changed; the user approves or rejects it later. Tell the user it is pending."""
    project_id = None
    if req.project:
        project_id = (await run_in_threadpool(_project_or_404, req.project))["id"]
    try:
        row = await run_in_threadpool(projects.propose_action, project_id, req.action_type, req.title,
                                      req.detail, req.payload, req.source_fact_ids)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"proposed": row, "note": "Pending approval; nothing has been executed."}


@router.get("/actions/proposed", operation_id="list_proposed_actions")
async def list_proposed_actions(
    status: str = Query(default="pending", description='"pending", "approved", "rejected" or "done".'),
    project: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Actions proposed by the agent and their approval status."""
    project_id = (await run_in_threadpool(_project_or_404, project))["id"] if project else None
    rows = await run_in_threadpool(projects.list_proposed_actions, status, project_id, limit)
    return {"count": len(rows), "actions": rows}


@router.get("/digest/latest", operation_id="get_latest_digest")
async def get_latest_digest() -> dict:
    """The most recent monitoring digest: only items above the attention threshold."""
    row = await run_in_threadpool(projects.latest_digest)
    if row is None:
        return {"digest": None, "note": "No digest yet. The indexer's `monitor` job writes one."}
    return row


@router.get("/changes", operation_id="get_recent_changes")
async def get_recent_changes(
    since_days: int = Query(default=7, ge=1, le=365),
    min_severity: str = Query(default="notice"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """Recent changes across all projects, newest first."""
    rows = await run_in_threadpool(projects.project_changes, None, since_days, min_severity, limit)
    return {"count": len(rows), "changes": rows}


@router.get("/documents/{file_id}/diff", operation_id="diff_document_versions")
async def diff_document_versions(
    file_id: int,
    other_file_id: Optional[int] = Query(default=None, description="Compare against this file; "
                                         "default is the previous version in the chain."),
    summarize: bool = Query(default=True, description="Add an LLM summary of the changes."),
    max_lines: int = Query(default=200, ge=10, le=2000),
) -> dict:
    """What changed between two versions of a document: section-level changes, a
    line diff, and (optionally) a summary that says plainly when no rationale is given."""
    pair = await run_in_threadpool(docdiff.resolve_pair, file_id, other_file_id)
    if pair.get("error"):
        raise HTTPException(status_code=404, detail=pair["error"])
    if pair["old_text"] is None:
        return {"current": pair["current"], "previous": None, "basis": pair["basis"],
                "note": "No earlier version or earlier conversion of this document is stored."}
    diff = await run_in_threadpool(docdiff.diff_texts, pair["old_text"], pair["new_text"], max_lines)
    out = {"current": pair["current"], "previous": pair["previous"], "basis": pair["basis"], **diff}
    if summarize and (diff["lines_added"] or diff["lines_removed"]):
        out["summary"] = await docdiff.summarize(diff, pair["current"]["file_name"])
    return out


@router.get("/documents/{file_id}/versions", operation_id="get_document_versions")
async def get_document_versions(file_id: int) -> dict:
    """The version chain (v1 -> v2 -> v3) a document belongs to."""
    return await run_in_threadpool(projects.document_versions, file_id)
