"""Knowledge Steward behaviour: advisory promotion + semantic clustering.

These tests pin the Human-First directive: project copies are never
relocated, reuse advisories fire only for multi-customer actively-maintained
assets, and semantic working-set siblings collapse instead of spamming.
"""

from __future__ import annotations

import unittest

from auditor.findings import FindingsGenerator
from auditor.models import KnowledgeAsset
from auditor.semantic_dupes import (
    _is_temporal_pair,
    _is_workingset_pair,
    SemanticDuplicateDetector,
)


class FakeAssetRegistry:
    def __init__(self, assets: list[KnowledgeAsset]):
        self._assets = assets

    def build(self) -> list[KnowledgeAsset]:
        return self._assets


def asset(
    name: str,
    *,
    copy_count: int,
    project_count: int,
    customer_count: int,
    in_resources: bool = False,
    paths: list[str] | None = None,
) -> KnowledgeAsset:
    return KnowledgeAsset(
        asset_key=f"hash:{name}",
        asset_name=name,
        file_type="presentation",
        copy_count=copy_count,
        paths=paths or [f"01 Project/2026/01_X/Stage/{name}"] * copy_count,
        customer_count=customer_count,
        project_count=project_count,
        root_count=1,
        reuse_score=50,
        canonical_location=None,
        in_resources=in_resources,
    )


def generator_with_assets(assets: list[KnowledgeAsset]) -> FindingsGenerator:
    generator = FindingsGenerator.__new__(FindingsGenerator)
    generator.asset_registry = FakeAssetRegistry(assets)
    return generator


class AssetPromotionThresholdTests(unittest.TestCase):
    def test_single_customer_two_projects_no_finding(self) -> None:
        # Directive counter-example: a deck copied into two project folders
        # for one customer does NOT qualify.
        findings = generator_with_assets(
            [asset("RFP_Proposal.pptx", copy_count=2, project_count=2, customer_count=1)]
        )._asset_leakage_findings()
        self.assertEqual(findings, [])

    def test_multi_customer_but_few_copies_no_finding(self) -> None:
        findings = generator_with_assets(
            [asset("Deck.pptx", copy_count=2, project_count=2, customer_count=2)]
        )._asset_leakage_findings()
        self.assertEqual(findings, [])

    def test_multi_customer_actively_maintained_is_low_advisory(self) -> None:
        findings = generator_with_assets(
            [
                asset(
                    "Genie_Workshop.pptx",
                    copy_count=4,
                    project_count=4,
                    customer_count=4,
                    paths=[
                        "01 Project/2026/06_MusimMas/A.3. Workshop/Genie_Workshop.pptx",
                        "01 Project/2026/03_HongLeong/A.3. Workshop/Genie_Workshop.pptx",
                        "01 Project/2026/01_IBF/A.3. Workshop/Genie_Workshop.pptx",
                        "01 Project/2026/18_VanguardHealth/A.3. Workshop/Genie_Workshop.pptx",
                    ],
                )
            ]
        )._asset_leakage_findings()
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.issue_type, "reusable_asset")
        self.assertEqual(finding.severity, "low")
        self.assertIsNone(finding.suggested_destination)
        self.assertIn("COPY", finding.reasoning)
        self.assertIn("do", finding.reasoning.lower())

    def test_asset_already_in_resources_no_finding(self) -> None:
        findings = generator_with_assets(
            [
                asset(
                    "Deck.pptx",
                    copy_count=5,
                    project_count=4,
                    customer_count=4,
                    in_resources=True,
                )
            ]
        )._asset_leakage_findings()
        self.assertEqual(findings, [])


class SemanticWorkingSetSuppressionTests(unittest.TestCase):
    def _pair(self, root: str, a: str, b: str, sim: float = 0.99) -> dict:
        return {
            "root": root,
            "path_a": f"{root}/{a}",
            "path_b": f"{root}/{b}",
            "name_a": a.rsplit("/", 1)[-1],
            "name_b": b.rsplit("/", 1)[-1],
            "similarity": sim,
        }

    def test_page_export_siblings_are_suppressed(self) -> None:
        root = "/vault"
        pair = self._pair(
            root,
            "IBF/Slides/Page6_IVEE_Platform_Evolution.pdf",
            "IBF/Slides/Page12_IVEE_Platform_Evolution.pdf",
        )
        self.assertTrue(_is_workingset_pair(pair))

    def test_version_sibling_in_resources_is_suppressed(self) -> None:
        root = "/vault"
        pair = self._pair(
            root,
            "IBF/Slides/IVEE_Platform_Evolution.pdf",
            "IBF/Slides/V3 - Resources/V3_IVEE_Platform_Evolution.pdf",
        )
        self.assertTrue(_is_workingset_pair(pair))

    def test_distinct_names_cross_folder_survive(self) -> None:
        root = "/vault"
        pair = self._pair(
            root,
            "03 Product/10 Sharing/Genie Studio Sharing.pdf",
            "01 Project/2026/05_ITE/A.2.4. Slides/Genie Studio Sharing.pdf",
        )
        self.assertFalse(_is_workingset_pair(pair))


class SemanticTemporalSuppressionTests(unittest.TestCase):
    def _pair(self, root: str, a: str, b: str) -> dict:
        return {
            "root": root,
            "path_a": f"{root}/{a}",
            "path_b": f"{root}/{b}",
            "name_a": a.rsplit("/", 1)[-1],
            "name_b": b.rsplit("/", 1)[-1],
            "similarity": 1.0,
        }

    def test_distinct_daily_notes_are_suppressed(self) -> None:
        pair = self._pair(
            "/vault",
            "01 Daily_Todo/2025/10_Oct/28Oct2025.md",
            "01 Daily_Todo/2025/10_Oct/30Oct2025.md",
        )
        self.assertTrue(_is_temporal_pair(pair))

    def test_non_temporal_pair_is_not_suppressed(self) -> None:
        pair = self._pair(
            "/vault",
            "03 Product/Deck_Alpha.pptx",
            "01 Project/2026/01_X/Deck_Beta.pptx",
        )
        self.assertFalse(_is_temporal_pair(pair))


class SemanticClusteringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = SemanticDuplicateDetector.__new__(SemanticDuplicateDetector)

    def _pair(self, root, a, b, na, nb, sim=0.99) -> dict:
        return {
            "root": root,
            "path_a": f"{root}/{a}",
            "path_b": f"{root}/{b}",
            "name_a": na,
            "name_b": nb,
            "similarity": sim,
        }

    def test_transitive_pairs_collapse_to_one_cluster(self) -> None:
        root = "/vault"
        # A~B, B~C, A~C distinct-name files in different folders => 1 cluster.
        pairs = [
            self._pair(root, "P/Deck_Alpha.pptx", "Q/Deck_Beta.pptx", "Deck_Alpha.pptx", "Deck_Beta.pptx"),
            self._pair(root, "Q/Deck_Beta.pptx", "R/Deck_Gamma.pptx", "Deck_Beta.pptx", "Deck_Gamma.pptx"),
        ]
        findings = self.detector._findings_from_pairs(pairs)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].issue_type, "semantic_duplication")
        # Spans different folders => medium (genuine maintenance duplication).
        self.assertEqual(findings[0].severity, "medium")

    def test_workingset_pairs_produce_no_findings(self) -> None:
        root = "/vault"
        pairs = [
            self._pair(
                root,
                "IBF/Slides/Page6_IVEE.pdf",
                "IBF/Slides/Page12_IVEE.pdf",
                "Page6_IVEE.pdf",
                "Page12_IVEE.pdf",
            ),
            self._pair(
                root,
                "IBF/Slides/Page6_IVEE.pdf",
                "IBF/Slides/Page9_IVEE.pdf",
                "Page6_IVEE.pdf",
                "Page9_IVEE.pdf",
            ),
        ]
        self.assertEqual(self.detector._findings_from_pairs(pairs), [])


if __name__ == "__main__":
    unittest.main()
