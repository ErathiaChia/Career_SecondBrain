from __future__ import annotations

import unittest
from datetime import datetime, timezone

from auditor.config import load_config
from auditor.constitution import FolderConstitution
from auditor.name_lint import NameLinter
from auditor.template_diff import (
    TemplateDiffer,
    build_children_by_parent,
    parse_stage_name,
)
from auditor.models import FolderRecord


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


def make_tree(paths: list[str]) -> tuple[dict[str, FolderRecord], dict[str | None, list[str]]]:
    folders = [folder_record(i + 1, path) for i, path in enumerate(paths)]
    by_path = {folder.path: folder for folder in folders}
    return by_path, build_children_by_parent(folders)


class ParseStageNameTests(unittest.TestCase):
    def test_parses_stage_names(self) -> None:
        parsed = parse_stage_name("A.2.5. Contract")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.letter, "A")
        self.assertEqual(parsed.indices, (2, 5))
        self.assertEqual(parsed.label, "Contract")
        self.assertEqual(parsed.prefix, "A.2.5")

    def test_parses_without_trailing_dot(self) -> None:
        parsed = parse_stage_name("B.1.1 Resources")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.prefix, "B.1.1")

    def test_parses_letter_only_stage(self) -> None:
        parsed = parse_stage_name("A. PreSales")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.letter, "A")
        self.assertEqual(parsed.indices, ())

    def test_rejects_plain_names(self) -> None:
        self.assertIsNone(parse_stage_name("Resources"))
        self.assertIsNone(parse_stage_name("2026"))
        self.assertIsNone(parse_stage_name("01_IBF"))


class TemplateDifferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = load_config("config.yaml")
        constitution = FolderConstitution(config)
        cls.differ = TemplateDiffer(constitution.project_templates)
        cls.naming_standards = constitution.naming_standards

    def test_hongleong_index_collision_suggests_renumber(self) -> None:
        base = "01 Project/2026/03_HongLeong"
        by_path, children = make_tree(
            [
                base,
                f"{base}/A.2. Proposal",
                f"{base}/A.2. Proposal/A.2.5. Contract",
                f"{base}/A.2. Proposal/A.2.5. Proposal",
            ]
        )
        findings = self.differ.diff_initiative(base, by_path, children, enforce_core=False)
        renumber = [f for f in findings if f.suggested_action == "renumber"]
        self.assertEqual(len(renumber), 1)
        self.assertEqual(renumber[0].folder_path, f"{base}/A.2. Proposal/A.2.5. Proposal")
        self.assertIn("A.2.6. Proposal", renumber[0].suggested_destination)

    def test_musimmas_wrong_letter_nesting_is_flagged(self) -> None:
        base = "01 Project/2026/06_MusimMas"
        by_path, children = make_tree(
            [
                base,
                f"{base}/A.1. RFI_RFP_RFQ",
                f"{base}/A.1. RFI_RFP_RFQ/A.1.1. Logo",
                f"{base}/A.1. RFI_RFP_RFQ/B.1.1. Introduction_Deck",
            ]
        )
        findings = self.differ.diff_initiative(base, by_path, children, enforce_core=False)
        wrong_letter = [
            f
            for f in findings
            if f.folder_path == f"{base}/A.1. RFI_RFP_RFQ/B.1.1. Introduction_Deck"
            and f.suggested_action == "move"
        ]
        self.assertEqual(len(wrong_letter), 1)
        self.assertIn("B. Delivery", wrong_letter[0].suggested_destination)

    def test_alias_spelling_suggests_standardize(self) -> None:
        base = "01 Project/2026/07_MY_MOH"
        by_path, children = make_tree([base, f"{base}/A.1. RFI.RFP.RFQ"])
        findings = self.differ.diff_initiative(base, by_path, children, enforce_core=False)
        standardize = [f for f in findings if f.suggested_action == "standardize"]
        self.assertEqual(len(standardize), 1)
        self.assertEqual(standardize[0].suggested_destination, "A.1. RFI_RFP_RFQ")

    def test_ibf_silent_renumbering_is_flagged(self) -> None:
        base = "01 Project/2026/01_IBF/6 Transformation"
        by_path, children = make_tree(
            [
                base,
                f"{base}/A.2. Proposal",
                f"{base}/A.2. Proposal/A.2.1. Clarification",
                f"{base}/A.2. Proposal/A.2.2. Effort Estimation",
                f"{base}/A.2. Proposal/A.2.3. Consumption_Estimation",
                f"{base}/A.2. Proposal/A.2.4. Timeline",
                f"{base}/A.2. Proposal/A.2.5. Presentation Slide",
                f"{base}/A.2. Proposal/A.2.6. Contract",
            ]
        )
        findings = self.differ.diff_initiative(base, by_path, children, enforce_core=False)
        renumber = {f.folder_path: f for f in findings if f.suggested_action == "renumber"}
        self.assertIn(f"{base}/A.2. Proposal/A.2.4. Timeline", renumber)
        self.assertEqual(
            renumber[f"{base}/A.2. Proposal/A.2.4. Timeline"].suggested_destination,
            "A.2.3. Timeline",
        )

    def test_extension_folders_with_matching_letter_are_allowed(self) -> None:
        base = "01 Project/2026/12_TTSH"
        by_path, children = make_tree(
            [
                base,
                f"{base}/A.1. RFI_RFP_RFQ",
                f"{base}/A.1. RFI_RFP_RFQ/A.1.4. Additional Resources",
            ]
        )
        findings = self.differ.diff_initiative(base, by_path, children, enforce_core=False)
        flagged = [f for f in findings if "A.1.4" in f.folder_path]
        self.assertEqual(flagged, [])

    def test_missing_core_stage_reported_when_enforced(self) -> None:
        base = "01 Project/2026/05_ITE_AMK"
        by_path, children = make_tree([base, f"{base}/A.1. RFI_RFP_RFQ"])
        findings = self.differ.diff_initiative(base, by_path, children, enforce_core=True)
        completeness = [f for f in findings if f.issue_type == "project_completeness"]
        self.assertEqual(len(completeness), 1)
        self.assertIn("A.2. Proposal", completeness[0].suggested_destination)

    def test_leads_are_not_required_to_have_template(self) -> None:
        base = "01 Project/2026/08_NUHS"
        by_path, children = make_tree([base, f"{base}/01Oct2025 - NUHS"])
        findings = self.differ.diff_initiative(base, by_path, children, enforce_core=False)
        self.assertEqual(findings, [])


class NameLinterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = load_config("config.yaml")
        constitution = FolderConstitution(config)
        cls.linter = NameLinter(constitution.naming_standards)

    def test_sibling_numeric_prefix_collision_is_allowed(self) -> None:
        # Numbering policy: numbers are ordering aids, not unique identifiers.
        # "09 Approved_Icons" next to "09 SG_Companies_Logo" is intentional.
        folders = [
            folder_record(1, "02 Ops/09 Approved_Icons"),
            folder_record(2, "02 Ops/09 SG_Companies_Logo"),
        ]
        findings = self.linter.lint(folders)
        self.assertEqual(findings, [])

    def test_stage_prefixes_are_not_linted_here(self) -> None:
        folders = [
            folder_record(1, "x/A.2.5. Contract"),
            folder_record(2, "x/A.2.5. Proposal"),
        ]
        findings = self.linter.lint(folders)
        self.assertEqual(findings, [])

    def test_known_typo_is_flagged(self) -> None:
        folders = [folder_record(1, "04 Resources/05 Challanges_n_ValueProposition")]
        findings = self.linter.lint(folders)
        typos = [f for f in findings if f.suggested_action == "rename"]
        self.assertEqual(len(typos), 1)
        self.assertIn("Challenges", typos[0].suggested_destination)


if __name__ == "__main__":
    unittest.main()
