"""CLI for the Era Vault indexer."""
from __future__ import annotations

import time
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from career_history import bootstrap as bootstrap_mod
from career_history import config
from career_history import db
from career_history import discover as discover_mod
from career_history import envfile
from career_history import graph
from career_history import runner
from career_history import seed_entities
from career_history import v3


app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Era Vault indexer: discover, transcribe, embed, and build V3 knowledge graph.",
)
console = Console()


@app.callback()
def _global(
    config_path: str = typer.Option(
        "config.yaml", "--config", "-c", help="Path to config.yaml"
    ),
):
    envfile.load()
    config.load(config_path)


@app.command("init")
def init_cmd(
    schema: str = typer.Option("schema.sql", "--schema", help="Path to schema.sql"),
):
    """Apply schema.sql and additive migrations."""
    db.init_schema(schema)
    console.log("[green]Schema applied.[/green]")


@app.command("migrate")
def migrate_cmd(
    migrations_dir: Optional[str] = typer.Option(None, "--migrations-dir"),
):
    """Apply unapplied additive migrations."""
    applied = db.migrate(migrations_dir=migrations_dir)
    if applied:
        console.log(f"[green]Applied migrations:[/green] {', '.join(applied)}")
    else:
        console.log("[dim]No migrations pending.[/dim]")


@app.command("bootstrap")
def bootstrap_cmd():
    """Pre-download all models so the pipeline can run fully offline."""
    bootstrap_mod.bootstrap()


@app.command("discover")
def discover_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
):
    """Scan filesystem; register new/changed files into the queue."""
    discover_mod.discover(folder=folder)


@app.command("run")
def run_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
):
    """Process pending queue items."""
    runner.run(folder=folder, limit=limit)


@app.command("update")
def update_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
):
    """Discover + run in one step."""
    _update(folder=folder, limit=limit, run_settings=config.run_everything())


@app.command("update-documents")
def update_documents_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
):
    """Discover + run only document files."""
    _update(folder=folder, limit=limit, run_settings=config.run_documents())


@app.command("update-meetings")
def update_meetings_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
):
    """Discover + run only audio/video meeting files."""
    _update(folder=folder, limit=limit, run_settings=config.run_meetings_audio())


@app.command("sync")
def sync_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
    interval: Optional[int] = typer.Option(None, "--interval"),
    mode: str = typer.Option("all", "--mode"),
    once: bool = typer.Option(False, "--once"),
):
    """Continuously discover and process new or changed files."""
    run_settings = _run_settings_for_mode(mode)
    sleep_seconds = interval or config.sync_interval_seconds()
    while True:
        console.rule(f"[bold]Sync cycle ({run_settings['label']})[/bold]")
        _update(folder=folder, limit=limit, run_settings=run_settings)
        if once:
            return
        console.log(f"[dim]Sleeping {sleep_seconds}s before next sync cycle.[/dim]")
        time.sleep(sleep_seconds)


@app.command("reindex-documents-v2")
def reindex_documents_v2_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(25, "--limit", "-n"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Re-enqueue existing documents that are missing V2 structure metadata."""
    result = db.reindex_documents_v2(folder=folder, limit=limit, dry_run=dry_run)
    table = Table(title="V2 document reindex")
    table.add_column("Field")
    table.add_column("Value", justify="right")
    table.add_row("folder", folder or "all")
    table.add_row("dry_run", str(result["dry_run"]))
    table.add_row("matched", str(result["matched"]))
    table.add_row("enqueued", str(result["enqueued"]))
    console.print(table)


@app.command("reindex-documents")
def reindex_documents_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Re-enqueue existing document files for full conversion and embedding."""
    result = db.reindex_documents(folder=folder, limit=limit, dry_run=dry_run)
    table = Table(title="Document reindex")
    table.add_column("Field")
    table.add_column("Value", justify="right")
    table.add_row("folder", folder or "all")
    table.add_row("limit", str(limit or "all"))
    table.add_row("dry_run", str(result["dry_run"]))
    table.add_row("matched", str(result["matched"]))
    table.add_row("enqueued", str(result["enqueued"]))
    console.print(table)


@app.command("reindex-audio")
def reindex_audio_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Re-enqueue existing audio files for full re-transcription and embedding."""
    result = db.reindex_audio(folder=folder, limit=limit, dry_run=dry_run)
    table = Table(title="Audio reindex")
    table.add_column("Field")
    table.add_column("Value", justify="right")
    table.add_row("folder", folder or "all")
    table.add_row("limit", str(limit or "all"))
    table.add_row("dry_run", str(result["dry_run"]))
    table.add_row("matched", str(result["matched"]))
    table.add_row("enqueued", str(result["enqueued"]))
    console.print(table)


@app.command("v3-refresh")
def v3_refresh_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
    force_graph: bool = typer.Option(False, "--force-graph"),
):
    """Build V3 summaries, communities, graph metadata, and graph export."""
    result = v3.refresh(folder=folder, limit=limit, force_graph=force_graph)
    table = Table(title="V3 knowledge refresh")
    table.add_column("Stage")
    table.add_column("Result", justify="right")
    table.add_row("folder", folder or "all")
    table.add_row("chunk_alias_updates", str(result["alias_updates"]))
    table.add_row("document_summaries", str(result["document_summaries"]))
    table.add_row("section_summaries", str(result["section_summaries"]))
    table.add_row("graph_processed_chunks", str(result["graph"]["processed_chunks"]))
    table.add_row("graph_failed_chunks", str(result["graph"]["failed_chunks"]))
    table.add_row("communities", str(result["communities"]["communities"]))
    table.add_row(
        "graph_metadata",
        ", ".join(f"{k}={v}" for k, v in result["graph_metadata"].items()),
    )
    snapshot = result.get("snapshot") or {}
    table.add_row("snapshot_nodes", str(snapshot.get("node_count", 0)))
    table.add_row("snapshot_edges", str(snapshot.get("edge_count", 0)))
    console.print(table)


@app.command("v3-status")
def v3_status_cmd():
    """Show V3 knowledge object counts."""
    counts = v3.status()
    table = Table(title="V3 knowledge status")
    table.add_column("Object")
    table.add_column("Count", justify="right")
    for name, count in counts.items():
        table.add_row(name, str(count))
    console.print(table)


@app.command("v3-validate")
def v3_validate_cmd(
    query: str = typer.Option(
        "What do we know about ArgoCD?",
        "--query",
        "-q",
        help="Known validation question to track during rollout.",
    ),
):
    """Validate V3 object readiness for a known rollout question."""
    result = v3.validate(query=query)
    table = Table(title="V3 validation")
    table.add_column("Check")
    table.add_column("Result")
    table.add_row("query", result["query"])
    table.add_row("ready", str(result["ready"]))
    for name, ok in result["checks"].items():
        table.add_row(name, "ok" if ok else "missing")
    console.print(table)

    counts = Table(title="V3 object counts")
    counts.add_column("Object")
    counts.add_column("Count", justify="right")
    for name, count in result["counts"].items():
        counts.add_row(name, str(count))
    console.print(counts)
    console.log(f"[dim]{result['guidance']}[/dim]")


@app.command("graph-refresh")
def graph_refresh_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
    force: bool = typer.Option(False, "--force"),
    entities_only: bool = typer.Option(False, "--entities-only"),
):
    """Extract graph data from chunks and rebuild graph snapshot."""
    result = graph.refresh(
        folder=folder,
        limit=limit,
        force=force,
        include_relationships=not entities_only,
    )
    table = Table(title="Graph refresh")
    table.add_column("Field")
    table.add_column("Value", justify="right")
    table.add_row("folder", folder or "all")
    table.add_row("processed_chunks", str(result["processed_chunks"]))
    table.add_row("failed_chunks", str(result["failed_chunks"]))
    table.add_row("entities_seen", str(result["entities_seen"]))
    table.add_row("relationships_seen", str(result["relationships_seen"]))
    snapshot = result.get("snapshot") or {}
    table.add_row("snapshot_nodes", str(snapshot.get("node_count", 0)))
    table.add_row("snapshot_edges", str(snapshot.get("edge_count", 0)))
    console.print(table)


@app.command("extract-documents")
def extract_documents_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
    force: bool = typer.Option(False, "--force"),
    upgrade: bool = typer.Option(False, "--upgrade", help="Also re-extract files done at an older extractor version."),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="Stop before starting a file past this time ('HH:MM', '+2h', ISO)."),
):
    """Document-level graph extraction: ONE LLM call per FILE (not per chunk).
    The scalable path for large vaults. Folder-scoped + incremental + resumable."""
    from career_history.weekly import parse_deadline
    result = graph.refresh_documents(folder=folder, limit=limit, force=force, upgrade=upgrade,
                                     deadline=parse_deadline(deadline))
    table = Table(title="Document extraction" + (f" - {folder}" if folder else ""))
    table.add_column("Field")
    table.add_column("Value", justify="right")
    for key in ("folder", "processed_documents", "failed_documents",
                "entities_seen", "relationships_seen", "facts_seen"):
        table.add_row(key, str(result.get(key)))
    snapshot = result.get("snapshot") or {}
    table.add_row("snapshot_nodes", str(snapshot.get("node_count", 0)))
    table.add_row("snapshot_edges", str(snapshot.get("edge_count", 0)))
    console.print(table)


@app.command("graph-status")
def graph_status_cmd(
    scope: str = typer.Option("all", "--scope"),
):
    """Show graph extraction and latest snapshot status."""
    status = graph.status(scope=scope)
    extraction = status["extraction"]
    snapshot = status["snapshot"] or {}
    table = Table(title="Graph status")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("scope", status["scope"])
    table.add_row("extraction", _jsonish(extraction))
    table.add_row("snapshot_id", str(snapshot.get("id") or ""))
    table.add_row("snapshot_nodes", str(snapshot.get("node_count") or 0))
    table.add_row("snapshot_edges", str(snapshot.get("edge_count") or 0))
    table.add_row("created_at", str(snapshot.get("created_at") or ""))
    console.print(table)


@app.command("status")
def status_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
):
    """Show queue status counts by stage."""
    summary = db.status_summary(folder=folder)
    table = Table(title="Queue status" + (f" - {folder}" if folder else ""))
    table.add_column("Stage")
    table.add_column("Count", justify="right")
    for stage in ["pending", "transcribing", "converting", "chunking", "embedding", "done", "failed"]:
        if stage in summary:
            table.add_row(stage, str(summary[stage]))
    console.print(table)


@app.command("retry")
def retry_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
):
    """Reset all failed items to pending."""
    n = db.retry_failed(folder=folder)
    console.log(f"[green]Reset {n} failed item(s) to pending.[/green]")


@app.command("seed-entities")
def seed_entities_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
):
    """Seed canonical project entities + file mentions from the folder taxonomy
    (no LLM). Configure seed.project_roots in config.yaml. Also runs inside
    `discover`; this command runs it standalone."""
    result = seed_entities.seed(folder=folder)
    table = Table(title="Seed entities" + (f" - {folder}" if folder else ""))
    table.add_column("Field")
    table.add_column("Value", justify="right")
    for key, value in result.items():
        table.add_row(key, str(value))
    console.print(table)


# --- Project intelligence -------------------------------------------------------
# Imports are local so a missing optional dependency never breaks the core CLI.


def _print_result(title: str, result: dict) -> None:
    table = Table(title=title)
    table.add_column("Field")
    table.add_column("Value")
    for key, value in result.items():
        if isinstance(value, (list, dict)) and key in {"sample", "items"}:
            continue
        table.add_row(key, _jsonish(value) if isinstance(value, dict) else str(value))
    console.print(table)


@app.command("discover-projects")
def discover_projects_cmd():
    """Build/refresh the projects table from the auditor manifest (vault_manifest)
    plus folder-taxonomy seeds, and assign files to projects. Also runs in `discover`."""
    from career_history import projects
    _print_result("Projects", projects.discover_projects())


@app.command("enrich-projects")
def enrich_projects_cmd(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project id/key/name."),
    min_confidence: float = typer.Option(0.5, "--min-confidence"),
):
    """Fill low-confidence project fields (client, type, owner, objective) with the
    local LLM, citing facts and file names. Deterministic values are never overwritten."""
    from career_history import projects
    _print_result("Project enrichment", projects.enrich_with_llm(project, min_confidence=min_confidence))


@app.command("link-versions")
def link_versions_cmd():
    """Group documents into version families (v1 -> v2 -> final) and mark the latest."""
    from career_history import versions
    _print_result("Document versions", versions.link_versions())


@app.command("resolve-entities")
def resolve_entities_cmd(
    apply: bool = typer.Option(False, "--apply", help="Merge duplicates (default: dry-run)."),
    entity_type: Optional[list[str]] = typer.Option(None, "--type", "-t"),
    embeddings: bool = typer.Option(False, "--embeddings", help="Also merge on name-embedding similarity."),
    threshold: float = typer.Option(0.93, "--threshold"),
):
    """Find duplicate entities ("Nova Engg" / "Nova Engineering") and fold them into one."""
    from career_history import resolve
    result = resolve.resolve_entities(apply=apply, entity_types=entity_type,
                                      use_embeddings=embeddings, threshold=threshold)
    _print_result("Entity resolution", result)
    table = Table(title="Merges" + ("" if apply else " (dry-run)"))
    for col in ("from", "into", "type", "method", "score"):
        table.add_column(col)
    for m in result["sample"]:
        table.add_row(m["source_name"], m["target_name"], m["entity_type"], m["method"], str(m["score"]))
    console.print(table)


@app.command("project-state")
def project_state_cmd(
    project: Optional[str] = typer.Option(None, "--project", "-p"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Deterministic fields only."),
    force: bool = typer.Option(False, "--force", help="Rebuild even if inputs are unchanged."),
):
    """Build the current state + health of each project from typed facts."""
    from career_history import project_state
    _print_result("Project state", project_state.refresh_states(project, use_llm=not no_llm, force=force))


@app.command("detect-changes")
def detect_changes_cmd(
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM impact notes."),
):
    """Turn new vault events and fact diffs into project_changes with impact notes."""
    from career_history import changes
    _print_result("Changes", changes.detect_changes(use_llm=not no_llm))


@app.command("detect-conflicts")
def detect_conflicts_cmd(
    project: Optional[str] = typer.Option(None, "--project", "-p"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Deterministic checks only."),
    max_pairs: int = typer.Option(200, "--max-pairs", help="LLM-judged pairs per project."),
):
    """Find contradicting facts (dates, decisions, requirements) within each project."""
    from career_history import conflicts
    _print_result("Conflicts", conflicts.detect_conflicts(project, use_llm=not no_llm, max_pairs=max_pairs))


@app.command("resolve-conflict")
def resolve_conflict_cmd(
    conflict_id: int = typer.Argument(...),
    status: str = typer.Option(..., "--status", help='"confirmed" or "dismissed".'),
    latest: Optional[int] = typer.Option(None, "--latest", help="Fact id that is correct now."),
):
    """Confirm or dismiss a detected conflict; the decision survives re-detection."""
    from career_history import intel_db
    if status not in {"confirmed", "dismissed"}:
        raise typer.BadParameter('status must be "confirmed" or "dismissed"')
    ok = intel_db.set_conflict_status(conflict_id, status, latest)
    console.log(f"[green]Conflict {conflict_id} -> {status}[/green]" if ok else f"[red]No conflict {conflict_id}[/red]")


@app.command("detect-stale")
def detect_stale_cmd(
    max_age_days: int = typer.Option(365, "--max-age-days"),
    active_days: int = typer.Option(60, "--active-days",
                                    help="Projects with no file activity for longer are inactive."),
):
    """Flag facts that are superseded, contradicted, from old versions, or too old."""
    from career_history import conflicts
    _print_result("Stale knowledge", conflicts.detect_stale(max_age_days=max_age_days,
                                                             active_days=active_days))


@app.command("project-similarity")
def project_similarity_cmd(
    top_k: int = typer.Option(5, "--top-k"),
):
    """Compute similar projects (content embeddings + shared clients/tech/people)."""
    from career_history import similarity
    _print_result("Project similarity", similarity.refresh_similarity(top_k=top_k))


@app.command("proposed-actions")
def proposed_actions_cmd(
    approve: Optional[int] = typer.Option(None, "--approve", help="Approve this action id."),
    reject: Optional[int] = typer.Option(None, "--reject", help="Reject this action id."),
    done: Optional[int] = typer.Option(None, "--done", help="Mark this action id done."),
    status: str = typer.Option("pending", "--status"),
):
    """Review actions the agent proposed via era_mcp. Nothing runs until approved."""
    from career_history import intel_db
    for action_id, new_status in ((approve, "approved"), (reject, "rejected"), (done, "done")):
        if action_id is not None:
            ok = intel_db.decide_proposed_action(action_id, new_status)
            console.log(f"[green]Action {action_id} -> {new_status}[/green]" if ok
                        else f"[red]No action {action_id}[/red]")
            return
    table = Table(title=f"Proposed actions ({status})")
    for col in ("id", "project", "type", "title", "created"):
        table.add_column(col)
    for a in intel_db.list_proposed_actions(status):
        table.add_row(str(a["id"]), a["project"] or "", a["action_type"], a["title"], str(a["created_at"])[:16])
    console.print(table)


@app.command("monitor")
def monitor_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    skip_sync: bool = typer.Option(False, "--skip-sync"),
    skip_extract: bool = typer.Option(False, "--skip-extract"),
    no_llm: bool = typer.Option(False, "--no-llm"),
    threshold: int = typer.Option(40, "--threshold", help="Minimum attention score for the digest."),
):
    """Scheduled pipeline: sync -> extract -> projects/versions -> changes ->
    conflicts/stale -> state -> similarity -> digest."""
    from career_history import monitor
    _print_result("Monitor", monitor.run(folder=folder, skip_sync=skip_sync, skip_extract=skip_extract,
                                         use_llm=not no_llm, threshold=threshold))


@app.command("build-cards")
def build_cards_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Max cards to (re)build this run."),
    backfill: bool = typer.Option(False, "--backfill", help="Only the one-off card-only LLM pass for already-extracted files."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Re-assemble from stored inputs only (no model calls)."),
    deadline: Optional[str] = typer.Option(None, "--deadline"),
):
    """Document Intelligence Cards: backfill missing cards (one cheap LLM call each),
    re-assemble cards whose facts/entities/versions changed (no LLM), refresh relations."""
    from career_history import cards
    from career_history.weekly import parse_deadline
    dl = parse_deadline(deadline)
    if backfill:
        _print_result("Card backfill", cards.backfill_cards(folder=folder, limit=limit, use_llm=not no_llm, deadline=dl))
    else:
        _print_result("Cards", cards.refresh_cards(folder=folder, limit=limit, use_llm=not no_llm,
                                                   backfill_limit=limit or 500, deadline=dl))


@app.command("card")
def card_cmd(file_id: int = typer.Argument(..., help="file_registry id")):
    """Print one document's intelligence card."""
    from career_history import cards_db
    card = cards_db.get_card(file_id)
    if not card:
        console.print(f"[yellow]no card for file {file_id}[/yellow]")
        raise typer.Exit(code=1)
    for k in ("embedding", "search_vector", "llm_card", "card_text"):
        card.pop(k, None)
    console.print(card)


@app.command("relate-documents")
def relate_documents_cmd(limit: Optional[int] = typer.Option(None, "--limit", "-n")):
    """Recompute document -> document relations (version family, project siblings, similar cards)."""
    from career_history import cards
    _print_result("Relations", {"refreshed": cards.refresh_relations(limit=limit)})


@app.command("career-refresh")
def career_refresh_cmd(
    project: Optional[str] = typer.Option(None, "--project", "-p"),
    llm: bool = typer.Option(False, "--llm", help="Allow an LLM role-inference pass (default: deterministic)."),
    force: bool = typer.Option(False, "--force"),
):
    """Roles -> achievements -> skill evidence for every project (hash-gated)."""
    from career_history import career
    _print_result("Career", career.refresh_career(project_ref=project, use_llm=llm, force=force))


@app.command("infer-roles")
def infer_roles_cmd(project: Optional[str] = typer.Option(None, "--project", "-p")):
    """Infer my role per project (PM/SA prior + evidence); low confidence -> proposed action."""
    from career_history import career, intel_db
    projects = [intel_db.get_project(project)] if project else intel_db.list_projects()
    table = Table(title="Role inference")
    table.add_column("Project"); table.add_column("Scores"); table.add_column("Proposed?")
    for p in [x for x in projects if x]:
        r = career.infer_roles(p)
        table.add_row(p["name"], ", ".join(f"{k}={v}" for k, v in sorted(r["scores"].items(), key=lambda kv: -kv[1])[:3]),
                      "yes" if r["proposed"] else "")
    console.print(table)


@app.command("achievements")
def achievements_cmd(project: Optional[str] = typer.Option(None, "--project", "-p"),
                     me_only: bool = typer.Option(True, "--me/--all")):
    """List derived achievements with evidence fact ids."""
    from career_history import career_db, intel_db
    pid = intel_db.get_project(project)["id"] if project else None
    table = Table(title="Achievements")
    for col in ("Project", "Statement", "Metric", "Kind", "Conf", "Facts", "Status"):
        table.add_column(col)
    for a in career_db.list_achievements(pid, me_only=me_only):
        table.add_row(str(a.get("project")), a["statement"][:90], str((a.get("metric") or {}).get("raw") or ""),
                      str(a.get("outcome_kind")), f"{float(a['confidence']):.2f}",
                      ",".join(map(str, a.get("evidence_fact_ids") or [])), a["status"])
    console.print(table)


@app.command("skills")
def skills_cmd(limit: int = typer.Option(50, "--limit", "-n")):
    """Technology / product evidence across projects where I held a role."""
    from career_history import career_db
    table = Table(title="Skill evidence")
    for col in ("Skill", "Kind", "Project", "Role", "Mentions", "Strength"):
        table.add_column(col)
    for s in career_db.list_skills(limit):
        table.add_row(s["skill"], s["skill_kind"], s["project"], str(s.get("role")), str(s["mention_count"]),
                      f"{float(s['strength']):.2f}")
    console.print(table)


@app.command("confirm-role")
def confirm_role_cmd(project: str = typer.Argument(...), role: str = typer.Option(..., "--role", "-r"),
                     reject: bool = typer.Option(False, "--reject")):
    """Confirm (or reject) my role on a project; settles the confirm_role proposed action."""
    from career_history import career
    _print_result("Role", career.confirm_role(project, role, reject=reject))


@app.command("weekly")
def weekly_cmd(
    kind: str = typer.Option("weekly", "--kind", help="weekly | manual | catchup | weekday_sync"),
    max_docs: Optional[int] = typer.Option(1200, "--max-docs", help="Cap on documents extracted this run."),
    deadline: Optional[str] = typer.Option("Mon 05:00", "--deadline",
                                           help="Hard stop: 'Mon 05:00', 'HH:MM', '+12h' or ISO."),
    catchup: bool = typer.Option(False, "--catchup", help="Only run if the last run was partial/failed and there is backlog."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan (backlog, deadline, models) and exit."),
    skip_sync: bool = typer.Option(False, "--skip-sync"),
    skip_extract: bool = typer.Option(False, "--skip-extract"),
    no_llm: bool = typer.Option(False, "--no-llm"),
    audio: bool = typer.Option(False, "--audio", help="Also transcribe/queue audio in the sync stage."),
    threshold: int = typer.Option(40, "--threshold"),
    force_hours: bool = typer.Option(False, "--force-hours", help="Allow LLM stages during weekday hours."),
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
):
    """Weekend knowledge pipeline: preflight -> migrate -> sync -> extract (capped,
    deadline-bound, resumable) -> projects/versions/changes/conflicts/stale ->
    state -> digest, tracked in pipeline_runs (see scripts/weekly.sh, launchd/)."""
    from career_history import weekly
    result = weekly.run(kind=kind, max_docs=max_docs, deadline=deadline, catchup=catchup, dry_run=dry_run,
                        skip_sync=skip_sync, skip_extract=skip_extract, use_llm=not no_llm, audio=audio,
                        threshold=threshold, force_hours=force_hours, folder=folder)
    if not dry_run:
        _print_result("Weekly", {k: v for k, v in result.items() if k != "stages"})
        if result.get("stages"):
            _print_result("Stages", result["stages"])
    raise typer.Exit(code=0 if result.get("status") in (None, "finished", "partial") or result.get("skipped") else 1)


@app.command("digest")
def digest_cmd(
    threshold: int = typer.Option(40, "--threshold"),
    since_days: int = typer.Option(7, "--since-days"),
):
    """Build an attention-thresholded digest from current state, changes and conflicts."""
    from career_history import monitor
    result = monitor.build_digest(threshold=threshold, since_days=since_days)
    console.print(result["markdown"])


def _update(
    folder: Optional[str],
    limit: Optional[int],
    run_settings: config.RunSettings,
) -> None:
    discover_mod.discover(folder=folder, run_settings=run_settings)
    runner.run(folder=folder, limit=limit, run_settings=run_settings)
    if config.v3_enabled("knowledge_os_enabled"):
        console.rule("[bold]V3 knowledge refresh[/bold]")
        result = v3.refresh(folder=folder, limit=limit)
        console.log(
            "[green]V3 refreshed[/green] "
            f"documents={result['document_summaries']} "
            f"sections={result['section_summaries']} "
            f"communities={result['communities']['communities']}"
        )
        return
    if _graph_auto_refresh_enabled():
        console.rule("[bold]Graph refresh[/bold]")
        result = graph.refresh(folder=folder)
        console.log(
            "[green]Graph refreshed[/green] "
            f"processed={result['processed_chunks']} "
            f"failed={result['failed_chunks']}"
        )


def _run_settings_for_mode(mode: str) -> config.RunSettings:
    normalized = mode.strip().lower()
    if normalized == "all":
        return config.run_everything()
    if normalized == "documents":
        return config.run_documents()
    if normalized in {"audio", "meetings"}:
        return config.run_meetings_audio()
    raise typer.BadParameter('mode must be "all", "documents", or "audio"')


def _graph_auto_refresh_enabled() -> bool:
    return (
        config.v2_enabled("entity_extraction_enabled")
        and config.v2_enabled("relationship_extraction_enabled")
        and config.v2_enabled("graph_retrieval_enabled")
    )


def _jsonish(value: object) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(dict(value).items())) or "none"


def main():
    app()


if __name__ == "__main__":
    main()
