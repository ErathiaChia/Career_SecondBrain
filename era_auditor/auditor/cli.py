from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from .classifier import FolderClassifier
from .config import load_config
from .db import create_database
from .findings import FindingsGenerator
from .reports import ReportWriter
from .scanner import FolderScanner, write_scan_json
from .scoring import FolderScorer


app = typer.Typer(
    help="Standalone read-only AI Auditor Agent.",
    pretty_exceptions_show_locals=False,
)
findings_app = typer.Typer(
    help="Review audit findings.",
    pretty_exceptions_show_locals=False,
)
report_app = typer.Typer(
    help="Generate or view reports.",
    pretty_exceptions_show_locals=False,
)
registry_app = typer.Typer(
    help="Manage auditor project and customer registries.",
    pretty_exceptions_show_locals=False,
)
assets_app = typer.Typer(
    help="Inspect the knowledge asset registry.",
    pretty_exceptions_show_locals=False,
)
placement_app = typer.Typer(
    help="Librarian training: learn placement patterns, simulate accuracy, plan inbox moves.",
    pretty_exceptions_show_locals=False,
)
console = Console()


def database_from_config(config_path: str):
    config = load_config(config_path)
    return config, create_database(config)


def openai_client(config):
    from .openai_client import OpenAIClient

    return OpenAIClient(config)


@app.command("init-db")
def init_db(config: str = typer.Option("config.yaml", help="Path to auditor config YAML.")) -> None:
    """Apply the auditor-owned database schema."""
    cfg, database = database_from_config(config)
    database.init_db()
    console.print(f"Initialized auditor schema using {cfg.config_path}")


@app.command()
def scan(
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
    dry_run: bool = typer.Option(False, help="Write scan JSON without touching the database."),
    write_db: bool = typer.Option(False, help="Write scan inventory to Postgres."),
    limit: int | None = typer.Option(None, help="Limit scanned folders for testing."),
) -> None:
    """Scan configured folder roots."""
    cfg, database = database_from_config(config)
    result = FolderScanner(cfg).scan(limit=limit)

    if dry_run or not write_db:
        path = write_scan_json(cfg, result)
        console.print(f"Scan JSON written to {path}")

    if write_db:
        run_id = database.create_run("scan")
        counts = database.upsert_scan_result(run_id, result)
        database.finish_run(run_id, counts=counts)
        console.print(f"Scan run {run_id} saved: {counts}")


@app.command()
def classify(
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
    limit: int | None = typer.Option(None, help="Limit folders classified this run."),
    full: bool = typer.Option(False, help="Reclassify all folders, including unchanged folders."),
) -> None:
    """Classify new or changed folders using OpenAI."""
    cfg, database = database_from_config(config)
    run_id = database.create_run("classify")
    try:
        client = openai_client(cfg)
        count = FolderClassifier(cfg, database, client).classify_pending(run_id, limit=limit, full=full)
        database.finish_run(run_id, counts={"total_folders": count})
        console.print(f"Classified {count} folder(s) in run {run_id}")
    except Exception as exc:
        database.finish_run(run_id, status="failed", error_message=str(exc))
        raise


@app.command()
def audit(
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
    limit: int | None = typer.Option(None, help="Limit folders included in this audit."),
    no_ai: bool = typer.Option(False, help="Generate deterministic findings without OpenAI."),
) -> None:
    """Generate audit findings."""
    cfg, database = database_from_config(config)
    run_id = database.create_run("audit")
    try:
        client = None if no_ai else openai_client(cfg)
        findings = FindingsGenerator(cfg, database, client).generate(run_id, limit=limit, use_ai=not no_ai)
        database.finish_run(run_id, counts={"total_findings": len(findings)})
        console.print(f"Generated {len(findings)} finding(s) in run {run_id}")
    except Exception as exc:
        database.finish_run(run_id, status="failed", error_message=str(exc))
        raise


@app.command()
def run(
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
    limit: int | None = typer.Option(None, help="Limit folders for a small maintenance pass."),
    full: bool = typer.Option(False, help="Force complete reclassification."),
    no_ai: bool = typer.Option(False, help="Scan and audit deterministic signals without OpenAI."),
) -> None:
    """Run the recurring on-demand maintenance pass."""
    from .asset_registry import AssetRegistryBuilder
    from .placement import PlacementEngine

    cfg, database = database_from_config(config)
    run_id = database.create_run("maintenance")
    try:
        scan_result = FolderScanner(cfg).scan(limit=limit)
        counts = database.upsert_scan_result(run_id, scan_result)
        asset_count = AssetRegistryBuilder(database).refresh(run_id)

        classified_count = 0
        if not no_ai:
            client = openai_client(cfg)
            classifier = FolderClassifier(cfg, database, client)
            classified_count = classifier.classify_pending(run_id, limit=limit, full=full)
            findings = FindingsGenerator(cfg, database, client).generate(run_id, limit=limit, use_ai=True)
        else:
            findings = FindingsGenerator(cfg, database).generate(run_id, limit=limit, use_ai=False)

        # Learn placement patterns from the (now classified) vault so the
        # Librarian training layer stays in sync with each maintenance pass.
        pattern_count = PlacementEngine(database, cfg).refresh_patterns(run_id)

        FolderScorer(database).score_run(run_id)
        report_path = ReportWriter(cfg, database).write_report(run_id)
        database.finish_run(
            run_id,
            report_path=str(report_path),
            counts={**counts, "total_findings": len(findings)},
            metadata={
                "classified_folders": classified_count,
                "no_ai": no_ai,
                "full": full,
                "asset_count": asset_count,
                "placement_patterns": pattern_count,
            },
        )
        console.print(f"Maintenance run {run_id} complete.")
        console.print(f"Report: {report_path}")
        _print_top_findings(database.findings_for_run(run_id))
    except Exception as exc:
        database.finish_run(run_id, status="failed", error_message=str(exc))
        raise


@findings_app.command("list")
def findings_list(config: str = typer.Option("config.yaml", help="Path to auditor config YAML.")) -> None:
    """List open findings."""
    _, database = database_from_config(config)
    _print_findings_table(database.open_findings())


@findings_app.command("accept")
def findings_accept(
    finding_id: int,
    decision_note: str | None = typer.Option(None, help="Optional note for why this finding was accepted."),
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
) -> None:
    """Mark a finding as accepted."""
    _, database = database_from_config(config)
    if database.review_finding(finding_id, "accepted", decision_note):
        console.print(f"Accepted finding {finding_id}")
    else:
        console.print(f"Finding {finding_id} was not found.")
        raise typer.Exit(1)


@findings_app.command("reject")
def findings_reject(
    finding_id: int,
    reason: str = typer.Option(..., help="Reason for rejecting this finding."),
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
) -> None:
    """Mark a finding as rejected."""
    _, database = database_from_config(config)
    if database.review_finding(finding_id, "rejected", reason):
        console.print(f"Rejected finding {finding_id}")
    else:
        console.print(f"Finding {finding_id} was not found.")
        raise typer.Exit(1)


@app.command("bootstrap-registry")
def bootstrap_registry(
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
    apply: bool = typer.Option(False, "--apply", help="Merge the generated patch into the registry YAML files."),
    patch_file: str | None = typer.Option(None, help="Apply a previously generated patch file instead of building a new one."),
) -> None:
    """Generate a reviewable registry patch from the scanned folder tree."""
    from .registry_bootstrap import RegistryBootstrapper, load_patch

    cfg, database = database_from_config(config)
    bootstrapper = RegistryBootstrapper(cfg, database)

    if patch_file:
        patch = load_patch(patch_file)
    else:
        patch = bootstrapper.build_patch()
        path = bootstrapper.write_patch(patch)
        console.print(f"Registry patch written to {path}")

    customers = patch.get("customers") or {}
    projects = patch.get("projects") or []
    console.print(f"Proposed: {len(customers)} customer(s), {len(projects)} project(s)")
    for code, entry in customers.items():
        console.print(f"- customer `{code}`: {entry.get('full_name')} ({entry.get('source_folder')})")
    for project in projects:
        console.print(
            f"- project `{project.get('project_id')}`: {project.get('folder_path')} "
            f"[lifecycle={project.get('lifecycle')}]"
        )

    if apply:
        counts = bootstrapper.apply_patch(patch)
        console.print(
            f"Applied patch: {counts['customers']} customer(s), {counts['projects']} project(s) merged."
        )
    elif not patch_file:
        console.print("Review the patch file, then re-run with --apply (optionally --patch-file PATH).")


@registry_app.command("sync")
def registry_sync(config: str = typer.Option("config.yaml", help="Path to auditor config YAML.")) -> None:
    """Load YAML registry files into auditor registry tables."""
    _, database = database_from_config(config)
    database.sync_registries_from_yaml()
    console.print("Synced registry YAML files into auditor tables.")


@registry_app.command("add-customer")
def registry_add_customer(
    code: str,
    full_name: str | None = typer.Option(None, help="Customer full name."),
    industry: str | None = typer.Option(None, help="Customer industry."),
    country: str | None = typer.Option(None, help="Customer country."),
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
) -> None:
    """Add or update a customer registry entry."""
    _, database = database_from_config(config)
    database.add_customer(code, full_name=full_name, industry=industry, country=country, source="cli")
    console.print(f"Saved customer registry entry `{code}`.")


@registry_app.command("add-project")
def registry_add_project(
    project_id: str = typer.Option(..., help="Stable project ID."),
    path: str = typer.Option(..., help="Project folder path relative to the source root."),
    customer_code: str | None = typer.Option(None, help="Customer code."),
    customer_name: str | None = typer.Option(None, help="Customer full name."),
    initiative_name: str | None = typer.Option(None, help="Initiative name."),
    status: str | None = typer.Option(None, help="Project status."),
    year: int | None = typer.Option(None, help="Project year."),
    tag: list[str] | None = typer.Option(None, help="Project tag. Can be repeated."),
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
) -> None:
    """Add or update a project registry entry."""
    _, database = database_from_config(config)
    database.add_project(
        project_id=project_id,
        folder_path=path,
        customer_code=customer_code,
        customer_name=customer_name,
        initiative_name=initiative_name,
        status=status,
        year=year,
        tags=tag or [],
        source="cli",
    )
    console.print(f"Saved project registry entry `{project_id}`.")


@assets_app.command("refresh")
def assets_refresh(config: str = typer.Option("config.yaml", help="Path to auditor config YAML.")) -> None:
    """Rebuild the knowledge asset registry from the latest scan."""
    from .asset_registry import AssetRegistryBuilder

    _, database = database_from_config(config)
    run_id = database.latest_run_id()
    if run_id is None:
        console.print("No auditor runs found. Run a scan first.")
        raise typer.Exit(1)
    count = AssetRegistryBuilder(database).refresh(run_id)
    console.print(f"Asset registry refreshed: {count} asset(s).")


@assets_app.command("list")
def assets_list(
    top: int = typer.Option(20, help="Number of assets to show."),
    min_score: int = typer.Option(0, help="Only show assets with reuse_score >= this value."),
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
) -> None:
    """List the most reused knowledge assets."""
    _, database = database_from_config(config)
    assets = database.top_assets(limit=top, min_reuse_score=min_score)
    if not assets:
        console.print("No assets in the registry. Run `assets refresh` after a scan.")
        return
    table = Table(title="Most Reused Knowledge Assets")
    table.add_column("Score", justify="right")
    table.add_column("Asset")
    table.add_column("Type")
    table.add_column("Copies", justify="right")
    table.add_column("Projects", justify="right")
    table.add_column("Customers", justify="right")
    table.add_column("Canonical Location")
    for asset in assets:
        table.add_row(
            str(asset["reuse_score"]),
            asset["asset_name"],
            asset["file_type"],
            str(asset["copy_count"]),
            str(asset["project_count"]),
            str(asset["customer_count"]),
            asset["canonical_location"] or "-",
        )
    console.print(table)


@report_app.callback(invoke_without_command=True)
def report_callback(
    ctx: typer.Context,
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
) -> None:
    if ctx.invoked_subcommand is None:
        _write_latest_report(config)


@report_app.command("latest")
def report_latest(config: str = typer.Option("config.yaml", help="Path to auditor config YAML.")) -> None:
    """Generate a Markdown report for the latest run."""
    _write_latest_report(config)


def _write_latest_report(config: str) -> None:
    cfg, database = database_from_config(config)
    run_id = database.latest_run_id()
    if run_id is None:
        console.print("No auditor runs found.")
        raise typer.Exit(1)
    FolderScorer(database).score_run(run_id)
    path = ReportWriter(cfg, database).write_report(run_id)
    database.finish_run(run_id, report_path=str(path))
    console.print(f"Report written to {path}")


def _print_top_findings(findings: list[dict], limit: int = 5) -> None:
    if not findings:
        console.print("No findings generated.")
        return
    console.print("Top findings:")
    for finding in findings[:limit]:
        console.print(
            f"- #{finding['id']} {finding['severity']} {float(finding['confidence']):.0%} "
            f"`{finding['folder_path']}`: {finding['issue_type']}"
        )


def _print_findings_table(findings: list[dict]) -> None:
    table = Table(title="Open Auditor Findings")
    table.add_column("ID", justify="right")
    table.add_column("Severity")
    table.add_column("Confidence")
    table.add_column("Action")
    table.add_column("Folder")
    table.add_column("Issue")
    for finding in findings:
        table.add_row(
            str(finding["id"]),
            finding["severity"],
            f"{float(finding['confidence']):.0%}",
            finding["suggested_action"],
            finding["folder_path"],
            finding["issue_type"],
        )
    console.print(table)


@placement_app.command("learn")
def placement_learn(config: str = typer.Option("config.yaml", help="Path to auditor config YAML.")) -> None:
    """Extract placement patterns from the vault into the training tables."""
    from .placement import PlacementEngine

    cfg, database = database_from_config(config)
    run_id = database.latest_run_id()
    if run_id is None:
        console.print("No auditor runs found. Run a scan first.")
        raise typer.Exit(1)
    count = PlacementEngine(database, cfg).refresh_patterns(run_id)
    console.print(f"Learned {count} placement pattern(s) from the vault.")


@placement_app.command("simulate")
def placement_simulate(
    sample: int | None = typer.Option(None, help="Sample N placed files (default: all)."),
    no_embeddings: bool = typer.Option(False, help="Disable the embedding nearest-neighbour fallback."),
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
) -> None:
    """Measure Librarian readiness: predict placed files blind and score accuracy."""
    from .placement import PlacementEngine
    from .reports import write_placement_simulation_report

    cfg, database = database_from_config(config)
    run_id = database.latest_run_id()
    if run_id is None:
        console.print("No auditor runs found. Run a scan first.")
        raise typer.Exit(1)
    engine = PlacementEngine(database, cfg)
    summary = engine.simulate(
        run_id=run_id, sample=sample, use_embeddings=not no_embeddings
    )
    if summary["total"] == 0:
        console.print("No placed files available to simulate.")
        return
    table = Table(title=f"Placement Simulation (run {run_id})")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Files tested", str(summary["total"]))
    table.add_row("Exact-folder accuracy", f"{summary['exact_accuracy']:.1%}")
    table.add_row("Initiative-level accuracy", f"{summary['initiative_accuracy']:.1%}")
    table.add_row("Customer-level accuracy", f"{summary['customer_accuracy']:.1%}")
    console.print(table)
    path = write_placement_simulation_report(cfg, run_id, summary)
    console.print(f"Report: {path}")


@placement_app.command("plan")
def placement_plan(
    inbox: str = typer.Option("00", help="Top-level root prefix treated as inbox/staging."),
    no_embeddings: bool = typer.Option(False, help="Disable the embedding nearest-neighbour fallback."),
    config: str = typer.Option("config.yaml", help="Path to auditor config YAML."),
) -> None:
    """Predict destinations for inbox files. Phase 1 plans only - no moves."""
    from .placement import PlacementEngine, confidence_band
    from .reports import write_placement_plan_report

    cfg, database = database_from_config(config)
    run_id = database.latest_run_id()
    if run_id is None:
        console.print("No auditor runs found. Run a scan first.")
        raise typer.Exit(1)
    engine = PlacementEngine(database, cfg)
    plans = engine.plan_inbox(
        run_id=run_id,
        inbox_prefixes=(inbox,),
        use_embeddings=not no_embeddings,
    )
    if not plans:
        console.print(f"No files found under an inbox root starting with '{inbox}'.")
        return
    table = Table(title=f"Inbox Placement Plan (run {run_id})")
    table.add_column("Confidence", justify="right")
    table.add_column("Band")
    table.add_column("File")
    table.add_column("Predicted Destination")
    for plan in plans[:25]:
        table.add_row(
            f"{plan.confidence:.0%}",
            confidence_band(plan.confidence),
            plan.file_path.rsplit("/", 1)[-1],
            plan.predicted_path or "(needs review)",
        )
    console.print(table)
    path = write_placement_plan_report(cfg, run_id, plans)
    console.print(f"Plan: {path} ({len(plans)} file(s), no moves performed)")


app.add_typer(findings_app, name="findings")
app.add_typer(report_app, name="report")
app.add_typer(registry_app, name="registry")
app.add_typer(assets_app, name="assets")
app.add_typer(placement_app, name="placement")


if __name__ == "__main__":
    app()
