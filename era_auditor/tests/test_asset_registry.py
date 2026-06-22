from __future__ import annotations

import unittest
from typing import Any

from auditor.asset_registry import (
    AssetRegistryBuilder,
    compute_reuse_score,
    normalize_asset_name,
    parse_project_context,
)


def file_row(
    path: str,
    content_hash: str | None = None,
    size_bytes: int = 1024 * 1024,
    extension: str | None = None,
) -> dict[str, Any]:
    if extension is None:
        name = path.rsplit("/", 1)[-1]
        extension = f".{name.rsplit('.', 1)[-1]}" if "." in name else ""
    return {
        "root_path": "/root",
        "folder_path": path.rsplit("/", 1)[0] if "/" in path else path,
        "path": path,
        "extension": extension,
        "size_bytes": size_bytes,
        "content_hash": content_hash,
    }


class FakeDatabase:
    def __init__(self, files: list[dict[str, Any]]):
        self.files = files

    def active_files(self, min_size_bytes: int = 0) -> list[dict[str, Any]]:
        return [f for f in self.files if f["size_bytes"] >= min_size_bytes]


class NormalizeAssetNameTests(unittest.TestCase):
    def test_strips_extension_and_separators(self) -> None:
        self.assertEqual(
            normalize_asset_name("AI_Governance-Deck.pptx"), "ai governance deck"
        )

    def test_strips_version_suffixes(self) -> None:
        self.assertEqual(normalize_asset_name("Proposal v2.docx"), "proposal")
        self.assertEqual(normalize_asset_name("Proposal final.docx"), "proposal")
        self.assertEqual(normalize_asset_name("Proposal (1).docx"), "proposal")


class ParseProjectContextTests(unittest.TestCase):
    def test_standard_project_path(self) -> None:
        customer, project = parse_project_context(
            "01 Project/2026/01_IBF/1 AI Staff Training/A.2. Proposal/deck.pptx"
        )
        self.assertEqual(customer, "01_IBF")
        self.assertEqual(project, "01_IBF/1 AI Staff Training")

    def test_non_project_path(self) -> None:
        customer, project = parse_project_context("04 Resources/01 PreSales/deck.pptx")
        self.assertIsNone(customer)
        self.assertIsNone(project)

    def test_customer_without_initiative(self) -> None:
        customer, project = parse_project_context("01 Project/2026/02_BNM/notes.md")
        self.assertEqual(customer, "02_BNM")
        self.assertEqual(project, "02_BNM")


class ReuseScoreTests(unittest.TestCase):
    def test_single_copy_scores_zero(self) -> None:
        self.assertEqual(compute_reuse_score(1, 0, 0, 1), 0)

    def test_cross_project_reuse_scores_high(self) -> None:
        multi = compute_reuse_score(3, 3, 2, 2)
        single = compute_reuse_score(3, 1, 1, 1)
        self.assertGreater(multi, single)

    def test_score_is_capped_at_100(self) -> None:
        self.assertLessEqual(compute_reuse_score(50, 20, 20, 5), 100)


class AssetRegistryBuilderTests(unittest.TestCase):
    def test_groups_copies_by_hash(self) -> None:
        files = [
            file_row("01 Project/2026/01_IBF/Training/deck.pptx", content_hash="h1"),
            file_row("01 Project/2026/02_BNM/Workshop/deck.pptx", content_hash="h1"),
            file_row("04 Resources/01 PreSales/other.pdf", content_hash="h2"),
        ]
        assets = AssetRegistryBuilder(FakeDatabase(files)).build()
        keyed = {asset.asset_key: asset for asset in assets}
        self.assertEqual(keyed["hash:h1"].copy_count, 2)
        self.assertEqual(keyed["hash:h1"].project_count, 2)
        self.assertEqual(keyed["hash:h1"].customer_count, 2)
        self.assertFalse(keyed["hash:h1"].in_resources)
        self.assertGreater(keyed["hash:h1"].reuse_score, 0)
        self.assertEqual(keyed["hash:h2"].copy_count, 1)
        self.assertTrue(keyed["hash:h2"].in_resources)

    def test_canonical_location_prefers_resources(self) -> None:
        files = [
            file_row("01 Project/2026/01_IBF/Training/deck.pptx", content_hash="h1"),
            file_row("04 Resources/01 PreSales/deck.pptx", content_hash="h1"),
        ]
        assets = AssetRegistryBuilder(FakeDatabase(files)).build()
        self.assertEqual(
            assets[0].canonical_location, "04 Resources/01 PreSales/deck.pptx"
        )
        self.assertTrue(assets[0].in_resources)

    def test_unhashed_files_group_by_normalized_name(self) -> None:
        files = [
            file_row("02 Ops/deck v2.pptx", size_bytes=64 * 1024),
            file_row("03 Product/deck final.pptx", size_bytes=64 * 1024),
        ]
        assets = AssetRegistryBuilder(FakeDatabase(files)).build()
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].copy_count, 2)

    def test_non_knowledge_files_excluded(self) -> None:
        files = [
            file_row("02 Ops/script.py", content_hash="h1"),
            file_row("02 Ops/archive.zip", content_hash="h2"),
        ]
        assets = AssetRegistryBuilder(FakeDatabase(files)).build()
        self.assertEqual(assets, [])

    def test_size_floor_excludes_small_files(self) -> None:
        files = [file_row("02 Ops/icon.png", size_bytes=2 * 1024)]
        assets = AssetRegistryBuilder(FakeDatabase(files)).build()
        self.assertEqual(assets, [])


class AssetFamilyTests(unittest.TestCase):
    def test_working_set_variants_share_family_key(self) -> None:
        # Page exports of the same deck should resolve to one family.
        files = [
            file_row("01 Project/2026/IBF/Slides/Page6_IVEE_Platform.pdf", content_hash="a"),
            file_row("01 Project/2026/IBF/Slides/Page8_IVEE_Platform.pdf", content_hash="b"),
        ]
        assets = AssetRegistryBuilder(FakeDatabase(files)).build()
        families = {a.family_key for a in assets}
        self.assertEqual(len(families), 1)
        self.assertIsNotNone(next(iter(families)))

    def test_distinct_assets_have_distinct_families(self) -> None:
        files = [
            file_row("01 Project/IBF/Proposal.pdf", content_hash="a"),
            file_row("01 Project/IBF/Estimation.pdf", content_hash="b"),
        ]
        assets = AssetRegistryBuilder(FakeDatabase(files)).build()
        families = {a.family_key for a in assets}
        self.assertEqual(len(families), 2)


if __name__ == "__main__":
    unittest.main()
