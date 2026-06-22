from __future__ import annotations

import unittest
from datetime import datetime, timezone

from auditor.config import load_config
from auditor.constitution import FolderConstitution
from auditor.findings import FindingsGenerator
from auditor.models import FolderClassification, FolderRecord
from auditor.name_lint import NameLinter
from auditor.template_diff import TemplateDiffer


def folder_record(folder_id: int, path: str, file_count: int = 0) -> FolderRecord:
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
        child_folder_count=0,
        total_size_bytes=0,
        latest_modified_at=datetime.now(timezone.utc),
        sample_filenames=[],
        content_signature=f"sig-{folder_id}",
    )


def make_generator(constitution: FolderConstitution) -> FindingsGenerator:
    from auditor.asset_registry import AssetRegistryBuilder
    from auditor.folder_roles import FolderRoleResolver

    generator = FindingsGenerator.__new__(FindingsGenerator)
    generator.constitution = constitution
    generator.template_differ = TemplateDiffer(constitution.project_templates)
    generator.name_linter = NameLinter(constitution.naming_standards)
    generator.role_resolver = FolderRoleResolver(constitution.naming_standards)
    generator.database = None
    generator.asset_registry = AssetRegistryBuilder(None)
    return generator


def initiative_classification(name: str) -> FolderClassification:
    return FolderClassification(
        folder_type="initiative",
        initiative=name,
        confidence=0.9,
        reasoning="test",
    )


class InitiativeTypeInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = load_config("config.yaml")
        cls.constitution = FolderConstitution(config)

    def test_stage_children_imply_sales_opportunity(self) -> None:
        inferred = self.constitution.infer_initiative_type(
            "1 AI Staff Training", ["A.1. RFI_RFP_RFQ", "A.2. Proposal"]
        )
        self.assertEqual(inferred, "sales_opportunity")

    def test_workshop_name_signal(self) -> None:
        inferred = self.constitution.infer_initiative_type(
            "GenAI Trends Sharing", ["Materials", "Slides"]
        )
        self.assertEqual(inferred, "workshop")

    def test_strategic_initiative_name_signal(self) -> None:
        inferred = self.constitution.infer_initiative_type(
            "Strategy Forward", ["Discussions", "Planning"]
        )
        self.assertEqual(inferred, "strategic_initiative")

    def test_architecture_artifact_name_signal(self) -> None:
        inferred = self.constitution.infer_initiative_type(
            "IVEE Architecture Diagram", []
        )
        self.assertEqual(inferred, "architecture_artifact")

    def test_default_falls_back_to_sales_opportunity(self) -> None:
        inferred = self.constitution.infer_initiative_type("Mystery Engagement", [])
        self.assertEqual(inferred, "sales_opportunity")

    def test_registry_overrides_inference(self) -> None:
        registered = self.constitution.registered_initiative_type(
            "01 Project/2026/01_IBF/1 AI Staff Training"
        )
        self.assertEqual(registered, "sales_opportunity")

    def test_stage_tree_usage_per_type(self) -> None:
        self.assertTrue(self.constitution.initiative_uses_stage_tree("sales_opportunity"))
        self.assertTrue(self.constitution.initiative_uses_stage_tree("delivery_project"))
        self.assertFalse(self.constitution.initiative_uses_stage_tree("workshop"))
        self.assertFalse(self.constitution.initiative_uses_stage_tree("strategic_initiative"))
        self.assertFalse(self.constitution.initiative_uses_stage_tree("architecture_artifact"))
        self.assertFalse(self.constitution.initiative_uses_stage_tree("nonexistent_type"))


class ArchetypeGatedTemplateTests(unittest.TestCase):
    """Non-sales initiatives must never be asked for PreSales/Delivery/Post Sales."""

    @classmethod
    def setUpClass(cls) -> None:
        config = load_config("config.yaml")
        cls.constitution = FolderConstitution(config)

    def _findings_for(self, paths: list[str], initiative_path: str) -> list:
        folders = [folder_record(i + 1, path) for i, path in enumerate(paths)]
        classifications = {}
        for folder in folders:
            if folder.path == initiative_path:
                classifications[folder.id] = initiative_classification(folder.name)
        generator = make_generator(self.constitution)
        return generator._template_findings(folders, classifications)

    def test_workshop_initiative_gets_no_completeness_findings(self) -> None:
        base = "01 Project/2026/01_IBF/GenAI Trends Sharing"
        findings = self._findings_for(
            [
                "01 Project",
                "01 Project/2026",
                "01 Project/2026/01_IBF",
                base,
                f"{base}/Materials",
                f"{base}/Slides",
                f"{base}/Meeting Notes",
            ],
            base,
        )
        self.assertEqual(findings, [])

    def test_strategic_initiative_gets_no_completeness_findings(self) -> None:
        base = "01 Project/2026/01_IBF/Strategy Forward"
        findings = self._findings_for(
            [base, f"{base}/Discussions", f"{base}/Planning", f"{base}/Deliverables"],
            base,
        )
        self.assertEqual(findings, [])

    def test_artifact_initiative_gets_no_completeness_findings(self) -> None:
        base = "01 Project/2026/01_IBF/IVEE Architecture Diagram"
        findings = self._findings_for([base], base)
        self.assertEqual(findings, [])

    def test_sales_opportunity_still_enforces_core_stages(self) -> None:
        base = "01 Project/2026/01_IBF/1 AI Staff Training"
        findings = self._findings_for(
            [base, f"{base}/A.1. RFI_RFP_RFQ"],
            base,
        )
        completeness = [f for f in findings if f.issue_type == "project_completeness"]
        self.assertTrue(completeness, "registered sales opportunity must enforce core stages")
        destinations = {f.suggested_destination for f in completeness}
        self.assertIn(f"{base}/A.2. Proposal", destinations)

    def test_workshop_with_stray_stage_folders_still_lints_structure(self) -> None:
        # Even a workshop gets structural validation when stage-prefixed
        # folders actually exist (collisions, alias drift), without core
        # completeness demands.
        base = "01 Project/2026/01_IBF/GenAI Trends Workshop"
        findings = self._findings_for(
            [
                base,
                f"{base}/A.2.5. Contract",
                f"{base}/A.2.5. Proposal",
            ],
            base,
        )
        completeness = [f for f in findings if f.issue_type == "project_completeness"]
        self.assertEqual(completeness, [])
        renumber = [f for f in findings if f.suggested_action == "renumber"]
        self.assertTrue(renumber)


class ReusableAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = load_config("config.yaml")
        cls.constitution = FolderConstitution(config)

    def test_resources_inside_project_is_not_flagged(self) -> None:
        # Knowledge Steward directive: a Resources folder inside a project is
        # project self-containment working as designed, never leakage.
        generator = make_generator(self.constitution)
        folder = folder_record(
            1, "01 Project/2026/01_IBF/Strategy Forward/Resources", file_count=4
        )
        self.assertEqual(generator._reusable_asset_findings([folder], {}), [])

    def test_empty_resources_not_flagged(self) -> None:
        generator = make_generator(self.constitution)
        folder = folder_record(
            1, "01 Project/2026/01_IBF/Strategy Forward/Resources", file_count=0
        )
        self.assertEqual(generator._reusable_asset_findings([folder], {}), [])

    def test_templates_inside_project_is_not_flagged(self) -> None:
        generator = make_generator(self.constitution)
        folder = folder_record(
            1, "01 Project/2026/01_IBF/Strategy Forward/Templates", file_count=9
        )
        self.assertEqual(generator._reusable_asset_findings([folder], {}), [])


if __name__ == "__main__":
    unittest.main()
