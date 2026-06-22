from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import AppConfig, resolve_report_directory
from .db import AuditorDatabase


class ReportWriter:
    def __init__(self, config: AppConfig, database: AuditorDatabase):
        self.config = config
        self.database = database

    def write_report(self, run_id: int) -> Path:
        findings = self.database.findings_for_run(run_id)
        scores = self.database.scores_for_run(run_id)
        report_dir = resolve_report_directory(self.config)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = report_dir / f"auditor_report_run_{run_id}_{timestamp}.md"
        path.write_text(self._render(run_id, findings, scores), encoding="utf-8")
        return path

    def _render(
        self,
        run_id: int,
        findings: list[dict[str, Any]],
        scores: list[dict[str, Any]],
    ) -> str:
        try:
            status_summary = self.database.findings_status_summary()
        except Exception:
            status_summary = {}

        # Asset-centric priority order: physical dupes, semantic dupes,
        # reusable asset candidates, resource leakage, architecture review,
        # naming corrections, then registry/informational maintenance.
        physical_dupes = [finding for finding in findings if finding["issue_type"] == "knowledge_duplication"]
        semantic_dupes = [finding for finding in findings if finding["issue_type"] == "semantic_duplication"]
        reusable = [finding for finding in findings if finding["issue_type"] == "reusable_asset"]
        leakage = [finding for finding in findings if finding["issue_type"] == "resource_leakage"]
        arch_review = [finding for finding in findings if finding["issue_type"] == "architecture_review"]
        naming = [finding for finding in findings if finding["issue_type"] in {"naming_inconsistency", "naming_ambiguity"}]
        template_drift = [finding for finding in findings if finding["issue_type"] in {"template_drift", "project_completeness"}]
        registry = [finding for finding in findings if finding["issue_type"] in {"unknown_customer", "unknown_initiative"}]
        leads = [finding for finding in findings if finding["issue_type"] == "orphaned_knowledge"]
        librarian = [finding for finding in findings if finding["issue_type"] == "missing_initiative_metadata"]
        other_types = {
            "knowledge_duplication",
            "semantic_duplication",
            "reusable_asset",
            "resource_leakage",
            "architecture_review",
            "naming_inconsistency",
            "naming_ambiguity",
            "template_drift",
            "project_completeness",
            "unknown_customer",
            "unknown_initiative",
            "orphaned_knowledge",
            "missing_initiative_metadata",
        }
        other = [finding for finding in findings if finding["issue_type"] not in other_types]

        open_high = status_summary.get("open_high", 0)
        open_medium = status_summary.get("open_medium", 0)
        open_low = status_summary.get("open_low", 0)
        resolved = status_summary.get("status_accepted", 0) + status_summary.get("status_rejected", 0)
        suppressed_summary = [
            "Folder-name similarity never generates duplication findings; only content evidence (hashes, embeddings) does.",
            "Numbering prefixes are ordering aids, not identifiers: shared sibling prefixes never generate findings.",
            "Month/version/Resources/Templates container names and temporal partitions never generate findings.",
            "Resources/Templates folders inside projects are project self-containment, never leakage findings.",
            "Asset reuse is advisory only: promotion is suggested solely for multi-customer, actively maintained assets, and never as a move (copy only).",
            "Empty inbox folders, temporal year folders, code repositories, and pure depth warnings are intentionally suppressed.",
            "App-settings subtrees in scanner.ignore_subtrees are skipped entirely.",
            "Previously rejected recommendation patterns are skipped when present in auditor decision history.",
        ]

        lines = [
            f"# AI Auditor Knowledge Architecture Report - Run {run_id}",
            "",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "No files were moved, renamed, deleted, archived, or created by this run.",
            "",
            "## Action Summary",
            "",
            f"- Findings in this run: {len(findings)}",
            f"- Open actions overall: {open_high} high, {open_medium} medium, {open_low} low",
            f"- Reviewed (accepted or rejected) to date: {resolved}",
            "- Registry suggestions can be applied in one step: `python -m auditor.cli bootstrap-registry`",
            "",
            "## 1. Physical Duplicate Files",
            "",
            "Byte-identical copies (content hash evidence). Keep one canonical copy.",
            "",
            *self._finding_lines(physical_dupes),
            "",
            "## 2. Semantic Duplicate Files",
            "",
            "Near-identical content by embedding similarity (era_indexer bridge); edited copies and re-saved versions.",
            "",
            *self._finding_lines(semantic_dupes),
            "",
            "## 3. Reusable Asset Advisory (informational)",
            "",
            "Advisory only. The auditor never recommends moving files out of a "
            "project: project copies preserve archive self-containment. "
            "Centralization is suggested only when an asset crosses multiple "
            "customers and shows active maintenance, and even then the action "
            "is to COPY a canonical version into 04 Resources, not relocate.",
            "",
            *self._asset_leaderboard_lines(),
            "",
            *self._finding_lines(reusable),
            "",
            "## 4. Resource Leakage",
            "",
            *self._finding_lines(leakage),
            "",
            "## 5. Architecture Review",
            "",
            "Structural decisions, not violations: the same topic lives under multiple roots. Decide a canonical home or document the split.",
            "",
            *self._finding_lines(arch_review),
            "",
            "## 6. Naming Corrections",
            "",
            *self._finding_lines(naming),
            "",
            "## Template Drift",
            "",
            "Validated against each initiative's archetype template (sales opportunities use the A/B/C stage tree; workshops, strategic initiatives, and artifacts are never asked for PreSales).",
            "",
            *self._finding_lines(template_drift),
            "",
            "## Registry Enrichment",
            "",
            "Registry gaps are maintenance tasks, not architecture issues.",
            "",
            *self._registry_lines(registry),
            "",
            "## Librarian Training Signals",
            "",
            "Findings that improve future placement accuracy. Registering these "
            "initiatives (customer + initiative_type + canonical_path) teaches "
            "the Placement Engine where new files belong.",
            "",
            *self._finding_lines(librarian),
            "",
            "## Informational: Leads and Unconnected Knowledge",
            "",
            *self._finding_lines(leads),
            "",
            "## Other Findings",
            "",
            *self._finding_lines(other),
            "",
            "## Suppressed Noise Summary",
            "",
            *[f"- {line}" for line in suppressed_summary],
            "",
        ]
        return "\n".join(lines)

    def _asset_leaderboard_lines(self) -> list[str]:
        """Most Reused Assets leaderboard from the asset registry."""
        try:
            assets = self.database.top_assets(limit=10, min_reuse_score=1)
        except Exception:
            return []
        if not assets:
            return []
        lines = [
            "### Most Reused Assets",
            "",
            "| Score | Asset | Type | Copies | Projects | Customers | Canonical Location |",
            "| ---: | --- | --- | ---: | ---: | ---: | --- |",
        ]
        for asset in assets:
            canonical = asset.get("canonical_location") or "-"
            # Steward threshold: only hint at promotion when the asset crosses
            # multiple customers AND has multiple diverging copies. Otherwise
            # it is project-local and stays put for self-containment.
            qualifies = (
                not asset.get("in_resources")
                and asset.get("customer_count", 0) >= 2
                and asset.get("copy_count", 0) >= 3
            )
            if asset.get("in_resources"):
                note = ""
            elif qualifies:
                note = " (advisory: consider COPYING to 04 Resources)"
            else:
                note = " (project-local, keep in place)"
            lines.append(
                f"| {asset['reuse_score']} | {asset['asset_name']} | {asset['file_type']} "
                f"| {asset['copy_count']} | {asset['project_count']} | {asset['customer_count']} "
                f"| `{canonical}`{note} |"
            )
        lines.append("")
        return lines

    def _registry_lines(self, registry: list[dict[str, Any]]) -> list[str]:
        if not registry:
            return ["No findings in this category."]
        folders = ", ".join(f"`{finding['folder_path']}`" for finding in registry)
        return [
            f"{len(registry)} folder(s) are not in the customer/project registries: {folders}",
            "",
            "Run `python -m auditor.cli bootstrap-registry` to generate a reviewable patch,",
            "then re-run with `--apply` to merge it.",
        ]

    def _finding_lines(self, findings: list[dict[str, Any]]) -> list[str]:
        if not findings:
            return ["No findings in this category."]

        lines: list[str] = []
        for index, finding in enumerate(findings, start=1):
            destination = finding.get("suggested_destination") or "None"
            confidence = float(finding["confidence"])
            lines.extend(
                [
                    f"{index}. Finding #{finding['id']} - `{finding['folder_path']}`",
                    f"   - Issue: `{finding['issue_type']}`",
                    f"   - Severity: `{finding['severity']}`",
                    f"   - Confidence: {confidence:.0%}",
                    f"   - Suggested action: `{finding['suggested_action']}`",
                    f"   - Suggested destination: `{destination}`",
                    f"   - Reason: {finding['reasoning']}",
                ]
            )
        return lines


def _placement_report_path(config: AppConfig, run_id: int, kind: str) -> Path:
    report_dir = resolve_report_directory(config)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return report_dir / f"placement_{kind}_run_{run_id}_{timestamp}.md"


def write_placement_simulation_report(
    config: AppConfig, run_id: int, summary: dict[str, Any]
) -> Path:
    """Render the placement-accuracy report (Librarian readiness)."""
    path = _placement_report_path(config, run_id, "simulation")
    lines = [
        f"# Placement Simulation - Run {run_id}",
        "",
        "Blind predictions on already-placed files. This measures how ready an",
        "AI Librarian is to replicate the user's filing decisions. **No files",
        "were moved.**",
        "",
        "## Accuracy",
        "",
        f"- Files tested: **{summary['total']}**",
        f"- Exact-folder accuracy: **{summary['exact_accuracy']:.1%}**",
        f"- Initiative-level accuracy: **{summary['initiative_accuracy']:.1%}**",
        f"- Customer-level accuracy: **{summary['customer_accuracy']:.1%}**",
        "",
        "| Match level | Count |",
        "| --- | ---: |",
        f"| exact | {summary['exact']} |",
        f"| initiative | {summary['initiative']} |",
        f"| customer | {summary['customer']} |",
        f"| wrong | {summary['wrong']} |",
        "",
        "## Misplacements (predicted != actual)",
        "",
    ]
    wrong = [r for r in summary["results"] if r["match_level"] in {"wrong", "customer"}]
    if not wrong:
        lines.append("None - every sampled file landed in its initiative or exact folder.")
    else:
        lines.append("| File | Predicted | Actual | Conf | Method |")
        lines.append("| --- | --- | --- | ---: | --- |")
        for r in wrong[:50]:
            name = r["file_path"].rsplit("/", 1)[-1]
            lines.append(
                f"| `{name}` | `{r['predicted_path'] or '-'}` | `{r['actual_path']}` "
                f"| {r['confidence']:.0%} | {r['method']} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_placement_plan_report(config: AppConfig, run_id: int, plans: list[Any]) -> Path:
    """Render predicted destinations for inbox files (no moves)."""
    path = _placement_report_path(config, run_id, "plan")
    bands: dict[str, list[Any]] = {"auto_place": [], "suggest": [], "needs_review": []}
    for plan in plans:
        from .placement import confidence_band

        bands[confidence_band(plan.confidence)].append(plan)
    lines = [
        f"# Inbox Placement Plan - Run {run_id}",
        "",
        "Predicted destinations for files currently in the inbox/staging area.",
        "**Phase 1 plans only - no files were moved.** A future supervised",
        "executor (Phase 2) can act on the high-confidence rows below.",
        "",
        f"- Total inbox files: **{len(plans)}**",
        f"- Auto-place candidates (>95%): **{len(bands['auto_place'])}**",
        f"- Suggestions (75-95%): **{len(bands['suggest'])}**",
        f"- Needs review (<75%): **{len(bands['needs_review'])}**",
        "",
    ]
    for band, title in (
        ("auto_place", "Auto-place candidates (>95% confidence)"),
        ("suggest", "Suggestions (75-95% confidence)"),
        ("needs_review", "Needs review (<75% confidence)"),
    ):
        rows = bands[band]
        lines.append(f"## {title}")
        lines.append("")
        if not rows:
            lines.append("None.")
            lines.append("")
            continue
        lines.append("| File | Predicted Destination | Conf | Method | Why |")
        lines.append("| --- | --- | ---: | --- | --- |")
        for plan in rows:
            name = plan.file_path.rsplit("/", 1)[-1]
            lines.append(
                f"| `{name}` | `{plan.predicted_path or '(none)'}` "
                f"| {plan.confidence:.0%} | {plan.method} | {plan.rationale} |"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

