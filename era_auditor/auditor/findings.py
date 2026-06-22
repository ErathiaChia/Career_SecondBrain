from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .asset_registry import AssetRegistryBuilder
from .config import AppConfig
from .constitution import FolderConstitution, normalize_name
from .db import AuditorDatabase
from .folder_roles import FolderRole, FolderRoleResolver
from .models import AuditFinding, FolderClassification, FolderRecord
from .name_lint import NameLinter
from .template_diff import TemplateDiffer, build_children_by_parent, parse_stage_name

if TYPE_CHECKING:
    from .openai_client import OpenAIClient


class FindingsResponse(BaseModel):
    findings: list[AuditFinding]


class FindingsGenerator:
    def __init__(
        self,
        config: AppConfig,
        database: AuditorDatabase,
        client: OpenAIClient | None = None,
    ):
        self.config = config
        self.database = database
        self.client = client
        self.constitution = FolderConstitution(config)
        self.rules = self.constitution.as_prompt_payload()
        self.template_differ = TemplateDiffer(self.constitution.project_templates)
        self.name_linter = NameLinter(self.constitution.naming_standards)
        self.role_resolver = FolderRoleResolver(self.constitution.naming_standards)
        self.asset_registry = AssetRegistryBuilder(database)
        self.prompt = client.load_prompt("generate_findings.md") if client else ""

    def generate(self, run_id: int, limit: int | None = None, use_ai: bool = True) -> list[AuditFinding]:
        folders = self.database.active_folders(limit=limit)
        classifications = self.database.latest_classifications()
        rejected_patterns = self.database.rejected_patterns()
        deterministic = self._deterministic_findings(folders, classifications)

        if not use_ai or self.client is None:
            findings = deterministic
        else:
            findings = self._ai_findings(folders, classifications, deterministic)

        findings = self._filter_findings(findings, folders, classifications, rejected_patterns)
        self.database.save_findings(run_id, findings)
        return findings

    def _ai_findings(
        self,
        folders: list[FolderRecord],
        classifications: dict[int, FolderClassification],
        deterministic: list[AuditFinding],
    ) -> list[AuditFinding]:
        payload = {
            "constitution": self.rules,
            "folders": [
                {
                    "id": folder.id,
                    "path": folder.path,
                    "parent": folder.parent_path,
                    "depth": folder.depth,
                    "file_count": folder.file_count,
                    "child_folder_count": folder.child_folder_count,
                    "sample_filenames": folder.sample_filenames,
                    "classification": classifications.get(folder.id).model_dump()
                    if folder.id in classifications
                    else None,
                    "file_category_counts": folder.file_category_counts,
                    "metadata_signals": folder.metadata_signals,
                }
                for folder in folders
            ],
            "deterministic_signals": [finding.model_dump() for finding in deterministic],
        }
        response = self.client.json_completion(self.prompt, payload, FindingsResponse)
        return response.findings

    def _filter_findings(
        self,
        findings: list[AuditFinding],
        folders: list[FolderRecord],
        classifications: dict[int, FolderClassification],
        rejected_patterns: set[tuple[str, str]] | None = None,
    ) -> list[AuditFinding]:
        rejected_patterns = rejected_patterns or set()
        folders_by_path = {folder.path: folder for folder in folders}
        classifications_by_path = {
            folder.path: classifications[folder.id]
            for folder in folders
            if folder.id in classifications
        }
        filtered: list[AuditFinding] = []
        seen: set[tuple[str, str, str]] = set()

        for finding in findings:
            if (finding.issue_type, finding.folder_path) in rejected_patterns:
                continue
            folder = folders_by_path.get(finding.folder_path)
            classification = classifications_by_path.get(finding.folder_path)
            if folder and self._is_false_positive(finding, folder, classification):
                continue
            key = (finding.folder_path, finding.issue_type, finding.reasoning)
            if key in seen:
                continue
            seen.add(key)
            filtered.append(finding)
        return filtered

    def _is_false_positive(
        self,
        finding: AuditFinding,
        folder: FolderRecord,
        classification: FolderClassification | None,
    ) -> bool:
        role = classification.folder_type if classification else None
        structural_roles = {"root", "inbox", "temporal", "customer", "stage", "project_artifact", "archive", "code_repo"}

        if role in structural_roles and finding.issue_type in {
            "resource_inside_project",
            "project_inside_resource",
            "resource_leakage",
            "duplicate_topic",
            "orphan_folder",
            "too_deep",
            "mixed_purpose_folder",
        }:
            return True

        if finding.issue_type == "duplicate_topic":
            if normalize_name(folder.name) in self.constitution.duplicate_ignore_names():
                return True
            if role in self.constitution.duplicate_ignore_roles():
                return True

        if finding.issue_type == "orphan_folder":
            if classification and classification.is_intentional_empty:
                return True
            if self.constitution.allowed_empty_match(folder.path):
                return True

        if finding.issue_type == "unclear_name":
            if classification and classification.customer_code and classification.customer_name:
                return True
            if role in {"root", "temporal", "stage", "inbox"}:
                return True

        if finding.issue_type == "too_deep" and role in {"stage", "project_artifact"}:
            return True

        return False

    def _deterministic_findings(
        self,
        folders: list[FolderRecord],
        classifications: dict[int, FolderClassification],
    ) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        classifications_by_path = {
            folder.path: classifications[folder.id]
            for folder in folders
            if folder.id in classifications
        }
        child_paths_by_parent: dict[str | None, set[str]] = defaultdict(set)
        for folder in folders:
            child_paths_by_parent[folder.parent_path].add(folder.path)

        for folder in folders:
            classification = classifications.get(folder.id)
            role = classification.folder_type if classification else None

            if _looks_like_unknown_customer_code(folder, classification):
                findings.append(
                    AuditFinding(
                        folder_path=folder.path,
                        issue_type="unknown_customer",
                        severity="low",
                        confidence=0.74,
                        suggested_action="enrich_registry",
                        suggested_destination="customer_registry",
                        reasoning="Folder is a customer/account container but is not yet represented in the Customer Registry.",
                    )
                )
                continue

            if role in {"root", "inbox", "temporal", "customer", "stage", "project_artifact", "archive", "code_repo"}:
                if role == "stage" and classification and classification.stage and classification.stage != folder.name:
                    findings.append(
                        AuditFinding(
                            folder_path=folder.path,
                            issue_type="naming_inconsistency",
                            severity="low",
                            confidence=0.76,
                            suggested_action="standardize",
                            suggested_destination=classification.stage,
                            reasoning="Stage folder matches a known alias but differs from the canonical naming standard.",
                        )
                    )
                continue

            if folder.name.lower() in {"misc", "others", "general", "temp", "new folder", "untitled"}:
                findings.append(
                    AuditFinding(
                        folder_path=folder.path,
                        issue_type="naming_ambiguity",
                        severity="low",
                        confidence=0.8,
                        suggested_action="review",
                        suggested_destination=None,
                        reasoning="Folder name is generic and may not communicate ownership or purpose later.",
                    )
                )

            if classification and classification.folder_type == "resource" and _looks_inside_project(folder):
                findings.append(
                    AuditFinding(
                        folder_path=folder.path,
                        issue_type="resource_leakage",
                        severity="medium",
                        confidence=min(0.9, classification.confidence),
                        suggested_action="review",
                        suggested_destination="Resources",
                        reasoning="Folder is classified as reusable knowledge but appears to live under a project-like path.",
                    )
                )

            if role == "unknown" and folder.file_count > 0:
                findings.append(
                    AuditFinding(
                        folder_path=folder.path,
                        issue_type="orphaned_knowledge",
                        severity="medium",
                        confidence=0.66,
                        suggested_action="review",
                        suggested_destination=None,
                        reasoning="Folder contains content but is not connected to a known project, customer, product, operation, administration area, or resource category.",
                    )
                )

        findings.extend(self._template_findings(folders, classifications))
        findings.extend(self.name_linter.lint(folders))
        findings.extend(self._scaffold_findings(folders))
        findings.extend(self._architecture_review_findings(folders, classifications))
        findings.extend(self._missing_initiative_metadata_findings(folders, classifications))
        findings.extend(self._duplicate_file_findings())
        findings.extend(self._semantic_duplicate_findings())
        findings.extend(self._reusable_asset_findings(folders, classifications))
        return findings

    def _semantic_duplicate_findings(self) -> list[AuditFinding]:
        """Embedding-based near-duplicates via era_indexer; no-op without it."""
        from .semantic_dupes import SemanticDuplicateDetector

        config = getattr(self, "config", None)
        if config is None:
            return []
        return SemanticDuplicateDetector(config).detect()

    def _reusable_asset_findings(
        self,
        folders: list[FolderRecord],
        classifications: dict[int, FolderClassification],
    ) -> list[AuditFinding]:
        """Reusable Asset Advisory: steward, not architect.

        The auditor surfaces assets that MIGHT be worth centralizing, but it
        never assumes relocation. Per the Knowledge Steward directive, a
        finding is only generated when an asset crosses MULTIPLE CUSTOMERS
        (a genuine reuse signal) AND has multiple diverging copies (a proxy
        for active maintenance, i.e. duplicate maintenance effort). Even
        then it is advisory: low severity, no suggested destination, and the
        reasoning explicitly tells the human to COPY (never move) so project
        self-containment is preserved.

        Container folders (Resources/Templates inside a project) are project
        self-containment working as designed and never generate findings.
        """
        return self._asset_leakage_findings(max_findings=15)

    # Promotion threshold (Knowledge Steward directive): an asset must cross
    # multiple customers AND show signs of active maintenance (multiple
    # diverging copies) before we even suggest centralization.
    PROMOTION_MIN_CUSTOMERS = 2
    PROMOTION_MIN_COPIES = 3

    def _asset_leakage_findings(self, max_findings: int = 15) -> list[AuditFinding]:
        try:
            assets = self.asset_registry.build()
        except Exception:
            # Asset registry unavailable (e.g. files table missing); skip.
            return []
        findings: list[AuditFinding] = []
        for asset in assets:
            if asset.in_resources:
                continue
            # Steward threshold: multi-customer AND multi-copy. A deck copied
            # into two project folders for one customer does NOT qualify.
            if asset.customer_count < self.PROMOTION_MIN_CUSTOMERS:
                continue
            if asset.copy_count < self.PROMOTION_MIN_COPIES:
                continue
            folder_path = asset.paths[0].rsplit("/", 1)[0] if "/" in asset.paths[0] else asset.paths[0]
            copies = ", ".join(f"`{path}`" for path in asset.paths[:6])
            findings.append(
                AuditFinding(
                    folder_path=folder_path,
                    issue_type="reusable_asset",
                    severity="low",
                    confidence=0.6,
                    suggested_action="review",
                    suggested_destination=None,
                    reasoning=(
                        f"Advisory: asset '{asset.asset_name}' appears across "
                        f"{asset.customer_count} customers with {asset.copy_count} "
                        "diverging copies, so it may be worth centralizing IF it "
                        "requires ongoing maintenance and a shared canonical "
                        "version would reduce future work. The copies inside "
                        "project folders preserve archive self-containment - do "
                        "NOT move them. If you promote, COPY one canonical version "
                        f"into 04 Resources and keep the project copies. Copies: {copies}."
                    ),
                )
            )
            if len(findings) >= max_findings:
                break
        return findings

    def _architecture_review_findings(
        self,
        folders: list[FolderRecord],
        classifications: dict[int, FolderClassification],
    ) -> list[AuditFinding]:
        """Structural ambiguity: the same topic under multiple top-level roots.

        This is NOT duplication. When 'FDE' exists under both 02 Ops and
        04 Resources, that is an architectural decision waiting to be made:
        is it an operational function, a knowledge library, or both?

        Containers, temporal partitions, and structural roles never qualify;
        only meaningful topic subtrees that actually hold knowledge files.
        One finding per topic (not per copy), framed as a question with
        suggested action document_decision.
        """
        findings: list[AuditFinding] = []
        ignore_names = self.constitution.duplicate_ignore_names()

        groups: dict[str, list[FolderRecord]] = defaultdict(list)
        for folder in folders:
            if folder.path == "." or "/" not in folder.path:
                continue
            classification = classifications.get(folder.id)
            role = self.role_resolver.resolve(folder, classification)
            if self.role_resolver.audit_exempt(role):
                continue
            if role in {FolderRole.CUSTOMER, FolderRole.INITIATIVE, FolderRole.STAGE}:
                continue
            # Only non-trivial subtrees: must hold knowledge somewhere below.
            if folder.file_count == 0 and folder.child_folder_count == 0:
                continue
            normalized = normalize_name(_strip_numeric_prefix(folder.name))
            if not normalized or normalized in ignore_names:
                continue
            if self.role_resolver.is_container_name(folder.name):
                continue
            if self.role_resolver.is_temporal_name(folder.name):
                continue
            groups[normalized].append(folder)

        for normalized, entries in sorted(groups.items()):
            roots = {folder.path.split("/")[0] for folder in entries}
            if len(entries) < 2 or len(roots) < 2:
                continue
            # Skip nested copies of the same subtree (parent/child pairs).
            paths = sorted(folder.path for folder in entries)
            if any(
                other != path and other.startswith(f"{path}/")
                for path in paths
                for other in paths
            ):
                continue
            primary = min(entries, key=lambda f: f.path)
            locations = ", ".join(f"`{path}`" for path in paths)
            root_list = " and ".join(sorted(roots))
            findings.append(
                AuditFinding(
                    folder_path=primary.path,
                    issue_type="architecture_review",
                    severity="low",
                    confidence=0.7,
                    suggested_action="document_decision",
                    suggested_destination=None,
                    reasoning=(
                        f"Topic '{normalized}' lives under {root_list} ({locations}). "
                        "Is it an operational function, a reusable knowledge library, "
                        "or intentionally both? Decide a canonical home or document "
                        "the split so future retrieval is unambiguous."
                    ),
                )
            )
        return findings

    def _duplicate_file_findings(
        self,
        min_size_bytes: int = 1024 * 1024,
        max_groups: int = 20,
    ) -> list[AuditFinding]:
        """Byte-identical files (by content hash) living in different folders."""
        findings: list[AuditFinding] = []
        try:
            groups = self.database.duplicate_file_groups(min_size_bytes=min_size_bytes)
        except Exception:
            # Older databases without content_hash; skip silently.
            return findings
        for group in groups[:max_groups]:
            folder_paths = [path for path in group["folder_paths"] if path]
            if len(set(folder_paths)) < 2:
                continue
            size_mb = int(group["size_bytes"]) / (1024 * 1024)
            asset_name = group["paths"][0].rsplit("/", 1)[-1]
            paths = ", ".join(f"`{path}`" for path in group["paths"])
            findings.append(
                AuditFinding(
                    folder_path=folder_paths[0],
                    issue_type="knowledge_duplication",
                    severity="medium",
                    confidence=0.95,
                    suggested_action="review",
                    suggested_destination=None,
                    reasoning=(
                        f"Asset '{asset_name}' has {int(group['copy_count'])} "
                        f"byte-identical copies ({size_mb:.1f} MB each): {paths}. "
                        "Keep one canonical copy and remove or link the rest."
                    ),
                )
            )
        return findings

    def _missing_initiative_metadata_findings(
        self,
        folders: list[FolderRecord],
        classifications: dict[int, FolderClassification],
    ) -> list[AuditFinding]:
        """Initiative folders that lack the metadata the Librarian needs.

        Librarian-training finding (not a tidy-up nag): an initiative whose
        archetype cannot be resolved from the registry OR a classification
        leaves the placement engine guessing. Recording it as a finding nudges
        the user to register the initiative (customer + initiative_type +
        canonical_path), which directly raises future placement accuracy.

        Deterministic and quiet: fires only for initiative folders that are
        absent from the project registry AND carry no initiative_type on their
        classification.
        """
        findings: list[AuditFinding] = []
        for folder in folders:
            classification = classifications.get(folder.id)
            if not classification or classification.folder_type != "initiative":
                continue
            if self.constitution.registered_initiative_type(folder.path):
                continue
            if getattr(classification, "initiative_type", None):
                continue
            # Needs real content to be worth registering.
            if folder.file_count == 0 and folder.child_folder_count == 0:
                continue
            findings.append(
                AuditFinding(
                    folder_path=folder.path,
                    issue_type="missing_initiative_metadata",
                    severity="low",
                    confidence=0.6,
                    suggested_action="document_decision",
                    suggested_destination=None,
                    reasoning=(
                        f"Initiative '{folder.name}' has no registered archetype "
                        "(customer / initiative_type / canonical_path). The Librarian "
                        "cannot confidently place new files for it until this is known. "
                        "Add it to the project registry to improve placement accuracy."
                    ),
                )
            )
        return findings

    def _template_findings(
        self,
        folders: list[FolderRecord],
        classifications: dict[int, FolderClassification],
    ) -> list[AuditFinding]:
        """Run template-diff validation per initiative subtree.

        Archetype-aware: the initiative type (registry-first, then inferred
        from folder evidence) decides WHICH template applies. Only
        sales-lifecycle archetypes are validated against the canonical A/B/C
        stage tree; workshops, strategic initiatives, artifacts, research and
        support activities are never asked for PreSales/Delivery/Post Sales.

        Core stage presence is additionally gated by lifecycle: it is only
        enforced for active_presales or delivery projects. Structural
        validation (collisions, wrong-letter nesting, alias drift) applies
        wherever stage-prefixed folders actually exist, regardless of type.
        """
        findings: list[AuditFinding] = []
        folders_by_path = {folder.path: folder for folder in folders}
        children_by_parent = build_children_by_parent(folders)

        initiative_paths: set[str] = set()
        for folder in folders:
            classification = classifications.get(folder.id)
            if classification and classification.folder_type == "initiative":
                initiative_paths.add(folder.path)
        # Customer folders whose direct children include stage folders act as
        # the initiative themselves (e.g. 02_Bank_Negara/A.1...).
        for folder in folders:
            classification = classifications.get(folder.id)
            if classification and classification.folder_type == "customer":
                child_names = [
                    path.rsplit("/", 1)[-1]
                    for path in children_by_parent.get(folder.path, [])
                ]
                if any(parse_stage_name(name) for name in child_names):
                    initiative_paths.add(folder.path)

        # Avoid double-processing nested initiatives: keep only the outermost
        # paths that aren't inside another initiative path.
        deduped = {
            path
            for path in initiative_paths
            if not any(path.startswith(f"{other}/") for other in initiative_paths if other != path)
        }

        for initiative_path in sorted(deduped):
            initiative_type = self._initiative_type_for(
                initiative_path, classifications, folders_by_path, children_by_parent
            )
            uses_stage_tree = self.constitution.initiative_uses_stage_tree(initiative_type)

            has_stage_children = self._has_stage_descendants(
                initiative_path, children_by_parent
            )
            if not uses_stage_tree and not has_stage_children:
                # Non-sales archetype with no stage folders: nothing to diff.
                continue

            lifecycle = self._lifecycle_for(initiative_path, children_by_parent)
            enforce_core = uses_stage_tree and lifecycle in {
                "active_presales",
                "delivery",
                "active",
            }
            findings.extend(
                self.template_differ.diff_initiative(
                    initiative_path,
                    folders_by_path,
                    children_by_parent,
                    enforce_core=enforce_core,
                )
            )
        return findings

    def _initiative_type_for(
        self,
        initiative_path: str,
        classifications: dict[int, FolderClassification],
        folders_by_path: dict[str, FolderRecord],
        children_by_parent: dict[str | None, list[str]],
    ) -> str:
        """Registry-first archetype resolution, then deterministic inference
        from the initiative name and direct children."""
        registered = self.constitution.registered_initiative_type(initiative_path)
        if registered:
            return registered
        folder = folders_by_path.get(initiative_path)
        if folder is not None:
            classification = classifications.get(folder.id)
            if classification and classification.initiative_type:
                return classification.initiative_type
        name = initiative_path.rsplit("/", 1)[-1]
        child_names = [
            path.rsplit("/", 1)[-1]
            for path in children_by_parent.get(initiative_path, [])
        ]
        return self.constitution.infer_initiative_type(name, child_names)

    @staticmethod
    def _has_stage_descendants(
        initiative_path: str,
        children_by_parent: dict[str | None, list[str]],
    ) -> bool:
        stack = [initiative_path]
        while stack:
            current = stack.pop()
            for child_path in children_by_parent.get(current, []):
                if parse_stage_name(child_path.rsplit("/", 1)[-1]):
                    return True
                stack.append(child_path)
        return False

    def _lifecycle_for(
        self,
        initiative_path: str,
        children_by_parent: dict[str | None, list[str]],
    ) -> str:
        registered = self.constitution.project_lifecycle(initiative_path)
        if registered:
            return registered
        # Inference for unregistered projects: stage children present means the
        # template is in use, so treat as active presales; otherwise a lead.
        stack = [initiative_path]
        while stack:
            current = stack.pop()
            for child_path in children_by_parent.get(current, []):
                name = child_path.rsplit("/", 1)[-1]
                parsed = parse_stage_name(name)
                if parsed and parsed.indices:
                    return "active_presales"
                if parsed:
                    stack.append(child_path)
        return "lead"

    def _scaffold_findings(self, folders: list[FolderRecord]) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        for folder in folders:
            if folder.name.startswith("<") and folder.name.endswith(">"):
                findings.append(
                    AuditFinding(
                        folder_path=folder.path,
                        issue_type="template_drift",
                        severity="low",
                        confidence=0.9,
                        suggested_action="move",
                        suggested_destination="04 Resources/02 Delivery/00 Templates",
                        reasoning=(
                            "Placeholder scaffold folder sits among real project folders. "
                            "Either rename it for a real project or relocate the scaffold "
                            "next to the other templates."
                        ),
                    )
                )
        return findings


def _strip_numeric_prefix(name: str) -> str:
    return re.sub(r"^[0-9]{1,3}[._ -]+", "", name.strip())


def _looks_inside_project(folder: FolderRecord) -> bool:
    parts = [part.lower() for part in folder.path.split("/")]
    return any(part.startswith("01") and "project" in part for part in parts) or "project" in parts


def _looks_like_unknown_customer_code(
    folder: FolderRecord,
    classification: FolderClassification | None,
) -> bool:
    if not classification:
        return False
    return (
        classification.folder_type == "customer"
        and classification.customer_code is not None
        and classification.customer_name is None
        and classification.matched_rule in {"customer_code:unknown", "project_template:customer"}
    )
