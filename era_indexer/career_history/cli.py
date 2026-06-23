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
