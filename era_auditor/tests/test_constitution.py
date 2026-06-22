from __future__ import annotations

import unittest
from datetime import datetime, timezone

from auditor.config import load_config
from auditor.constitution import FolderConstitution
from auditor.findings import FindingsGenerator
from auditor.models import AuditFinding, FolderRecord


def folder_record(folder_id: int, path: str, file_count: int = 0, child_count: int = 0) -> FolderRecord:
    parent = None if path in {".", ""} or "/" not in path else path.rsplit("/", 1)[0]
    depth = 0 if path == "." else len(path.split("/"))
    return FolderRecord(
        id=folder_id,
        root_path="/Volumes/homes/Erathia/Career/14. ST-Engg",
        path=path,
        absolute_path=f"/Volumes/homes/Erathia/Career/14. ST-Engg/{path}",
        parent_path=parent,
        depth=depth,
        file_count=file_count,
        child_folder_count=child_count,
        total_size_bytes=0,
        latest_modified_at=datetime.now(timezone.utc),
        sample_filenames=[],
        content_signature=f"sig-{folder_id}",
    )


class ConstitutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config("config.yaml")
        cls.constitution = FolderConstitution(cls.config)

    def test_top_level_project_is_root(self) -> None:
        classification = self.constitution.classify_deterministic(folder_record(1, "01 Project"))
        self.assertIsNotNone(classification)
        self.assertEqual(classification.folder_type, "root")

    def test_agent_inbox_is_allowed_empty_inbox(self) -> None:
        classification = self.constitution.classify_deterministic(folder_record(2, "00 Agent Inbox"))
        self.assertIsNotNone(classification)
        self.assertEqual(classification.folder_type, "inbox")
        self.assertTrue(classification.is_intentional_empty)

    def test_years_are_temporal(self) -> None:
        for path in ["01 Project/2025", "01 Project/2026"]:
            classification = self.constitution.classify_deterministic(folder_record(3, path))
            self.assertIsNotNone(classification)
            self.assertEqual(classification.folder_type, "temporal")

    def test_customer_year_child_is_customer(self) -> None:
        # A bare customer-named year child that is NOT a registered initiative
        # classifies as folder_type=customer (year-child container rule).
        classification = self.constitution.classify_deterministic(folder_record(4, "01 Project/2026/99_FakeCorp"))
        self.assertIsNotNone(classification)
        self.assertEqual(classification.folder_type, "customer")

    def test_registered_single_initiative_customer_folder_is_initiative(self) -> None:
        # Single-initiative customers register the customer FOLDER as the
        # initiative (stage tree sits directly under it), so it classifies as
        # an initiative carrying the customer identity.
        classification = self.constitution.classify_deterministic(folder_record(4, "01 Project/2026/07_MY_MOH"))
        self.assertIsNotNone(classification)
        self.assertEqual(classification.folder_type, "initiative")
        self.assertEqual(classification.customer_code, "MY_MOH")
        self.assertEqual(classification.classification_source, "project_registry")

    def test_project_registry_enriches_initiative(self) -> None:
        classification = self.constitution.classify_deterministic(
            folder_record(7, "01 Project/2026/01_IBF/1 AI Staff Training")
        )
        self.assertIsNotNone(classification)
        self.assertEqual(classification.folder_type, "initiative")
        self.assertEqual(classification.registry_project_id, "2026-IBF-AI-STAFF-TRAINING")
        self.assertEqual(classification.classification_source, "project_registry")

    def test_unknown_project_year_child_is_customer_not_initiative(self) -> None:
        # An unregistered customer-named year child must be a customer container,
        # never an initiative (initiatives live in the registry or deeper).
        classification = self.constitution.classify_deterministic(
            folder_record(6, "01 Project/2026/88_SomeNewClient")
        )
        self.assertIsNotNone(classification)
        self.assertEqual(classification.folder_type, "customer")

    def test_stage_folder_resolves(self) -> None:
        classification = self.constitution.classify_deterministic(
            folder_record(5, "01 Project/2026/01_IBF/1 AI Staff Training/A.2. Proposal")
        )
        self.assertIsNotNone(classification)
        self.assertEqual(classification.folder_type, "stage")
        self.assertEqual(classification.stage, "A.2. Proposal")

    def test_false_positive_findings_are_filtered(self) -> None:
        folders = [
            folder_record(1, "01 Project", child_count=1),
            folder_record(2, "00 Agent Inbox"),
            folder_record(3, "01 Project/2026"),
            folder_record(4, "01 Project/2026/07_MY_MOH"),
            folder_record(5, "01 Project/2026/01_IBF/1 AI Staff Training/A.2. Proposal"),
        ]
        classifications = {
            folder.id: self.constitution.classify_deterministic(folder)
            for folder in folders
        }
        generator = FindingsGenerator.__new__(FindingsGenerator)
        generator.constitution = self.constitution

        findings = [
            AuditFinding(
                folder_path="01 Project",
                issue_type="resource_inside_project",
                severity="medium",
                confidence=0.8,
                suggested_action="review",
                reasoning="Bad generic finding.",
            ),
            AuditFinding(
                folder_path="00 Agent Inbox",
                issue_type="orphan_folder",
                severity="low",
                confidence=0.7,
                suggested_action="review",
                reasoning="Bad generic finding.",
            ),
            AuditFinding(
                folder_path="01 Project/2026",
                issue_type="duplicate_topic",
                severity="low",
                confidence=0.68,
                suggested_action="review",
                reasoning="Bad generic finding.",
            ),
            AuditFinding(
                folder_path="01 Project/2026/07_MY_MOH",
                issue_type="unclear_name",
                severity="low",
                confidence=0.4,
                suggested_action="review",
                reasoning="Bad generic finding.",
            ),
            AuditFinding(
                folder_path="01 Project/2026/01_IBF/1 AI Staff Training/A.2. Proposal",
                issue_type="duplicate_topic",
                severity="low",
                confidence=0.68,
                suggested_action="review",
                reasoning="Bad generic finding.",
            ),
        ]

        filtered = generator._filter_findings(findings, folders, classifications)
        self.assertEqual(filtered, [])

    def test_unknown_customer_is_registry_enrichment(self) -> None:
        from auditor.asset_registry import AssetRegistryBuilder
        from auditor.folder_roles import FolderRoleResolver
        from auditor.name_lint import NameLinter
        from auditor.template_diff import TemplateDiffer

        folder = folder_record(8, "01 Project/2026/99_FakeCorp")
        classification = self.constitution.classify_deterministic(folder)
        generator = FindingsGenerator.__new__(FindingsGenerator)
        generator.constitution = self.constitution
        generator.template_differ = TemplateDiffer(self.constitution.project_templates)
        generator.name_linter = NameLinter(self.constitution.naming_standards)
        generator.role_resolver = FolderRoleResolver(self.constitution.naming_standards)
        generator.database = None
        generator.asset_registry = AssetRegistryBuilder(None)
        generator.config = None
        findings = generator._deterministic_findings([folder], {folder.id: classification})

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].issue_type, "unknown_customer")
        self.assertEqual(findings[0].suggested_action, "enrich_registry")

    def test_rejected_finding_pattern_is_suppressed(self) -> None:
        folder = folder_record(9, "01 Project/2026/99_FakeCorp")
        classification = self.constitution.classify_deterministic(folder)
        generator = FindingsGenerator.__new__(FindingsGenerator)
        generator.constitution = self.constitution
        finding = AuditFinding(
            folder_path=folder.path,
            issue_type="unknown_customer",
            severity="low",
            confidence=0.74,
            suggested_action="enrich_registry",
            suggested_destination="customer_registry",
            reasoning="Rejected already.",
        )

        filtered = generator._filter_findings(
            [finding],
            [folder],
            {folder.id: classification},
            rejected_patterns={(finding.issue_type, finding.folder_path)},
        )
        self.assertEqual(filtered, [])


if __name__ == "__main__":
    unittest.main()
