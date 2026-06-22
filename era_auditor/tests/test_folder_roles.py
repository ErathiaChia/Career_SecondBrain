from __future__ import annotations

import unittest
from datetime import datetime, timezone

from auditor.config import load_config
from auditor.constitution import FolderConstitution
from auditor.findings import FindingsGenerator
from auditor.folder_roles import FolderRole, FolderRoleResolver
from auditor.models import FolderClassification, FolderRecord
from auditor.name_lint import NameLinter
from auditor.template_diff import TemplateDiffer


def folder_record(
    folder_id: int,
    path: str,
    file_count: int = 0,
    child_folder_count: int = 0,
) -> FolderRecord:
    parent = None if path in {".", ""} or "/" not in path else path.rsplit("/", 1)[0]
    depth = 0 if path == "." else len(path.split("/"))
    return FolderRecord(
        id=folder_id,
        root_path="/root",
        path=path,
        absolute_path=f"/root/{path}",
        parent_path=parent,
        depth=depth,
        file_count=file_count,
        child_folder_count=child_folder_count,
        total_size_bytes=0,
        latest_modified_at=datetime.now(timezone.utc),
        sample_filenames=[],
        content_signature=f"sig-{folder_id}",
    )


def make_generator(constitution: FolderConstitution) -> FindingsGenerator:
    from auditor.asset_registry import AssetRegistryBuilder

    generator = FindingsGenerator.__new__(FindingsGenerator)
    generator.constitution = constitution
    generator.template_differ = TemplateDiffer(constitution.project_templates)
    generator.name_linter = NameLinter(constitution.naming_standards)
    generator.role_resolver = FolderRoleResolver(constitution.naming_standards)
    generator.database = None
    generator.asset_registry = AssetRegistryBuilder(None)
    return generator


class FolderRoleResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = load_config("config.yaml")
        constitution = FolderConstitution(config)
        cls.resolver = FolderRoleResolver(constitution.naming_standards)

    def test_container_names(self) -> None:
        for name in ["Resources", "Templates", "Materials", "Slides", "drafts", "Final", "Misc"]:
            folder = folder_record(1, f"x/{name}", file_count=2)
            self.assertEqual(
                self.resolver.resolve(folder), FolderRole.CONTAINER, name
            )

    def test_numbered_container_names(self) -> None:
        folder = folder_record(1, "02 Ops/09 Approved_Icons/03 Templates")
        self.assertEqual(self.resolver.resolve(folder), FolderRole.CONTAINER)

    def test_version_folders_are_containers(self) -> None:
        for name in ["Version 1", "Version 2", "v2", "V3.1", "version_4"]:
            folder = folder_record(1, f"x/{name}")
            self.assertEqual(
                self.resolver.resolve(folder), FolderRole.CONTAINER, name
            )

    def test_temporal_names(self) -> None:
        for name in ["2026", "Jan", "01_Jan", "202510_Oct", "202602_Feb", "Sprint 7", "Q1", "Q3 2026", "Week 12", "03"]:
            folder = folder_record(1, f"x/{name}")
            self.assertEqual(
                self.resolver.resolve(folder), FolderRole.TEMPORAL, name
            )

    def test_topic_names_are_not_containers(self) -> None:
        for name in ["FDE", "BrownBag", "AI Governance", "Kubernetes"]:
            folder = folder_record(1, f"x/{name}", file_count=3)
            role = self.resolver.resolve(folder)
            self.assertNotIn(
                role, {FolderRole.CONTAINER, FolderRole.TEMPORAL}, name
            )

    def test_structural_classification_wins(self) -> None:
        folder = folder_record(1, "01 Project/2026/01_IBF")
        classification = FolderClassification(
            folder_type="customer", confidence=0.9, reasoning="test"
        )
        self.assertEqual(
            self.resolver.resolve(folder, classification), FolderRole.CUSTOMER
        )

    def test_container_and_temporal_are_audit_exempt(self) -> None:
        self.assertTrue(self.resolver.audit_exempt(FolderRole.CONTAINER))
        self.assertTrue(self.resolver.audit_exempt(FolderRole.TEMPORAL))
        self.assertFalse(self.resolver.audit_exempt(FolderRole.RESOURCE_LIBRARY))

    def test_role_set_matches_directive(self) -> None:
        # The Knowledge Steward directive defines exactly nine folder roles.
        expected = {
            "root",
            "project",
            "customer",
            "initiative",
            "stage",
            "container",
            "temporal",
            "resource_library",
            "administrative",
        }
        self.assertEqual({role.value for role in FolderRole}, expected)

    def test_templates_resolve_to_container(self) -> None:
        folder = folder_record(1, "x/Templates", file_count=2)
        classification = FolderClassification(
            folder_type="template", confidence=0.9, reasoning="test"
        )
        self.assertEqual(
            self.resolver.resolve(folder, classification), FolderRole.CONTAINER
        )

    def test_topic_leaf_resolves_to_resource_library(self) -> None:
        folder = folder_record(1, "x/AI Governance", file_count=3)
        self.assertEqual(
            self.resolver.resolve(folder), FolderRole.RESOURCE_LIBRARY
        )


class NoiseEliminationTests(unittest.TestCase):
    """Run-2 noise cases must produce ZERO findings under the new system."""

    @classmethod
    def setUpClass(cls) -> None:
        config = load_config("config.yaml")
        cls.constitution = FolderConstitution(config)

    def _arch_findings(self, paths: list[str], file_count: int = 3) -> list:
        generator = make_generator(self.constitution)
        folders = [
            folder_record(i + 1, path, file_count=file_count)
            for i, path in enumerate(paths)
        ]
        return generator._architecture_review_findings(folders, {})

    def test_resources_name_match_produces_no_findings(self) -> None:
        findings = self._arch_findings(
            [
                "01 Project/2026/01_IBF/Training/Resources",
                "02 Ops/04 FDE/Resources",
                "04 Resources/01 PreSales/Resources",
            ]
        )
        self.assertEqual(findings, [])

    def test_version_folders_produce_no_findings(self) -> None:
        findings = self._arch_findings(
            ["02 Ops/Deck/Version 1", "03 Product/Deck/Version 2"]
        )
        self.assertEqual(findings, [])

    def test_month_folders_produce_no_findings(self) -> None:
        findings = self._arch_findings(
            ["02 Ops/Reports/Jan", "03 Product/Updates/Jan", "02 Ops/202510_Oct", "05 Administrative/202510_Oct"]
        )
        self.assertEqual(findings, [])

    def test_templates_produce_no_findings(self) -> None:
        findings = self._arch_findings(
            ["02 Ops/Templates", "04 Resources/02 Delivery/00 Templates"]
        )
        self.assertEqual(findings, [])

    def test_fde_cross_root_becomes_architecture_review(self) -> None:
        findings = self._arch_findings(
            ["02 Ops/04 FDE", "04 Resources/03 FDE"]
        )
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.issue_type, "architecture_review")
        self.assertEqual(finding.suggested_action, "document_decision")
        self.assertIn("fde", finding.reasoning.lower())

    def test_brownbag_cross_root_becomes_architecture_review(self) -> None:
        findings = self._arch_findings(
            ["02 Ops/03 Events/BrownBag", "03 Product/BrownBag"]
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].issue_type, "architecture_review")

    def test_same_root_topics_are_not_flagged(self) -> None:
        findings = self._arch_findings(
            ["02 Ops/04 FDE", "02 Ops/Old/FDE"]
        )
        self.assertEqual(findings, [])

    def test_one_finding_per_topic_not_per_copy(self) -> None:
        findings = self._arch_findings(
            ["02 Ops/04 FDE", "03 Product/FDE", "04 Resources/03 FDE"]
        )
        self.assertEqual(len(findings), 1)


if __name__ == "__main__":
    unittest.main()
