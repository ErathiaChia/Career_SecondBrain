from __future__ import annotations

from collections import defaultdict
from typing import Any

from .db import AuditorDatabase
from .models import FolderRecord, FolderScore


SEVERITY_PENALTY = {"high": 30, "medium": 18, "low": 8}


class FolderScorer:
    def __init__(self, database: AuditorDatabase):
        self.database = database

    def score_run(self, run_id: int) -> list[FolderScore]:
        folders = self.database.active_folders()
        findings = self.database.findings_for_run(run_id)
        findings_by_folder: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for finding in findings:
            findings_by_folder[finding["folder_path"]].append(finding)

        scores = [self._score_folder(folder, findings_by_folder.get(folder.path, [])) for folder in folders]
        self.database.save_scores(run_id, scores)
        return scores

    def _score_folder(self, folder: FolderRecord, findings: list[dict[str, Any]]) -> FolderScore:
        # Knowledge-architecture dimensions. The goal is retrieval efficiency,
        # not folder perfection:
        #   naming        -> discoverability (will future-me find this?)
        #   duplicate     -> knowledge duplication (is this the only copy?)
        #   placement     -> reusability (are reusable assets where reuse happens?)
        #   structure     -> standardization (does the tree follow its archetype?)
        #   compliance    -> metadata completeness (registry coverage)
        naming = 100
        duplicate = 100
        placement = 100
        structure = 100
        compliance = 100

        for finding in findings:
            penalty = int(SEVERITY_PENALTY.get(finding["severity"], 8) * float(finding["confidence"]))
            issue_type = finding["issue_type"]
            if issue_type in {"unclear_name", "naming_ambiguity", "naming_inconsistency"}:
                naming -= penalty
            elif issue_type in {"duplicate_topic", "knowledge_duplication", "semantic_duplication"}:
                duplicate -= penalty
            elif issue_type == "architecture_review":
                # An open architecture decision, not a defect: a light
                # structure nudge so the folder surfaces for review.
                structure -= max(3, penalty // 2)
            elif issue_type in {
                "resource_inside_project",
                "project_inside_resource",
                "resource_leakage",
                "reusable_asset",
            }:
                placement -= penalty
                compliance -= max(4, penalty // 2)
            elif issue_type in {"too_deep", "missing_expected_structure", "orphan_folder", "template_drift", "project_completeness", "orphaned_knowledge"}:
                structure -= penalty
            elif issue_type == "mixed_purpose_folder":
                structure -= penalty
                naming -= max(4, penalty // 2)
            elif issue_type in {"unknown_customer", "unknown_initiative", "missing_initiative_metadata"}:
                # Registry/metadata gaps are maintenance tasks that improve
                # Librarian placement, not architecture defects.
                compliance -= max(3, penalty // 2)
            else:
                compliance -= penalty

        # Empty folders are intentional scaffolding (template stages created
        # ahead of artifacts), so emptiness is not penalized.
        dimensions = [clamp(naming), clamp(duplicate), clamp(placement), clamp(structure), clamp(compliance)]
        total = int(round(sum(dimensions) / len(dimensions)))
        explanation = (
            f"Score is based on {len(findings)} finding(s), folder depth {folder.depth}, "
            f"{folder.file_count} file(s), and {folder.child_folder_count} child folder(s)."
        )
        return FolderScore(
            folder_id=folder.id,
            folder_path=folder.path,
            naming_consistency=dimensions[0],
            duplicate_risk=dimensions[1],
            placement_confidence=dimensions[2],
            structure_clarity=dimensions[3],
            rules_compliance=dimensions[4],
            total_score=total,
            explanation=explanation,
        )


def clamp(value: int) -> int:
    return max(0, min(100, value))
