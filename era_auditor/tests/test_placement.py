"""Placement Intelligence Engine: pattern extraction, prediction, simulation.

These pin the Librarian-training behaviour: the engine learns from where the
user already placed files and predicts blind without ever moving anything.
"""

from __future__ import annotations

import unittest

from auditor.placement import (
    AUTO_PLACE_THRESHOLD,
    SUGGEST_THRESHOLD,
    PlacementEngine,
    confidence_band,
    file_kind,
    name_signals,
    parent_folder,
)


class FakePlacementDB:
    """Minimal stand-in for AuditorDatabase used by the placement engine."""

    def __init__(self, files: list[dict], projects: list[dict] | None = None):
        self._files = files
        self._projects = projects or []
        self.saved_patterns: list[dict] = []
        self.saved_sims: list[dict] = []
        self.saved_plans: list[dict] = []

    def placed_files_with_context(self, min_size_bytes: int = 0) -> list[dict]:
        return list(self._files)

    def projects_registry(self) -> list[dict]:
        return list(self._projects)

    def replace_placement_patterns(self, run_id, patterns):
        self.saved_patterns = patterns
        return len(patterns)

    def save_placement_simulations(self, run_id, rows):
        self.saved_sims = rows
        return len(rows)

    def save_placement_plans(self, run_id, rows):
        self.saved_plans = rows
        return len(rows)


class FakeConfig:
    class _DB:
        connection_string = "postgresql://invalid/none"

    class _Semantic:
        indexer_database_url = None

    base_dir = "/vault"
    database = _DB()
    semantic = _Semantic()


def _file(path, *, customer=None, init_type=None, stage=None, size=20000):
    return {
        "path": path,
        "folder_path": parent_folder(path),
        "extension": "." + path.rsplit(".", 1)[-1] if "." in path else "",
        "size_bytes": size,
        "content_hash": None,
        "customer_code": customer,
        "customer_name": customer,
        "initiative_type": init_type,
        "stage": stage,
    }


class HelperTests(unittest.TestCase):
    def test_file_kind(self):
        self.assertEqual(file_kind("Proposal.pptx"), "presentation")
        self.assertEqual(file_kind("notes.md"), "note")
        self.assertEqual(file_kind("estimate.xlsx"), "spreadsheet")
        self.assertEqual(file_kind("mystery.bin"), "other")

    def test_name_signals(self):
        self.assertIn("proposal", name_signals("RFP_MusimMas_Proposal.pptx"))
        self.assertIn("demo", name_signals("HongLeong POC Demo.mov"))
        self.assertEqual(name_signals("randomfile.pdf"), [])

    def test_confidence_bands(self):
        self.assertEqual(confidence_band(AUTO_PLACE_THRESHOLD), "auto_place")
        self.assertEqual(confidence_band(SUGGEST_THRESHOLD), "suggest")
        self.assertEqual(confidence_band(0.5), "needs_review")

    def test_parent_folder(self):
        self.assertEqual(parent_folder("a/b/c.pdf"), "a/b")
        self.assertEqual(parent_folder("toplevel.pdf"), "")


class PatternExtractionTests(unittest.TestCase):
    def test_patterns_count_supporting_files(self):
        files = [
            _file("01 Project/2026/IBF/A.2 Proposal/p1.pptx", customer="IBF", stage="proposal"),
            _file("01 Project/2026/IBF/A.2 Proposal/p2.pptx", customer="IBF", stage="proposal"),
            _file("01 Project/2026/IBF/A.2 Proposal/p3.pdf", customer="IBF", stage="proposal"),
        ]
        engine = PlacementEngine(FakePlacementDB(files), FakeConfig())
        patterns = engine.extract_patterns()
        # Two file kinds (presentation x2, document x1) under one destination.
        dest_patterns = [p for p in patterns if p.destination_path == "01 Project/2026/IBF/A.2 Proposal"]
        self.assertTrue(dest_patterns)
        presentation = next(p for p in dest_patterns if p.file_kind == "presentation")
        self.assertEqual(presentation.support_count, 2)

    def test_exclude_paths_holds_out_files(self):
        files = [
            _file("01 Project/IBF/x.pptx", customer="IBF"),
            _file("01 Project/IBF/y.pptx", customer="IBF"),
        ]
        engine = PlacementEngine(FakePlacementDB(files), FakeConfig())
        patterns = engine.extract_patterns(exclude_paths={"01 Project/IBF/x.pptx"})
        total = sum(p.support_count for p in patterns)
        self.assertEqual(total, 1)


class PredictionTests(unittest.TestCase):
    def _engine(self):
        files = [
            _file("01 Project/2026/IBF/A.2 Proposal/p1.pptx", customer="IBF", init_type="sales_opportunity", stage="proposal"),
            _file("01 Project/2026/IBF/A.2 Proposal/p2.pptx", customer="IBF", init_type="sales_opportunity", stage="proposal"),
            _file("01 Project/2026/HongLeong/B.2 POC/d1.pdf", customer="HongLeong", init_type="sales_opportunity", stage="poc"),
        ]
        return PlacementEngine(FakePlacementDB(files), FakeConfig())

    def test_predicts_matching_destination(self):
        engine = self._engine()
        pred = engine.predict(
            "INBOX/IBF_Proposal_v2.pptx",
            known_customer="IBF",
            known_initiative_type="sales_opportunity",
            known_stage="proposal",
            use_embeddings=False,
        )
        self.assertEqual(pred.predicted_path, "01 Project/2026/IBF/A.2 Proposal")
        self.assertEqual(pred.method, "deterministic")
        self.assertGreaterEqual(pred.confidence, SUGGEST_THRESHOLD)

    def test_wrong_customer_is_disqualified(self):
        engine = self._engine()
        pred = engine.predict(
            "INBOX/Proposal.pptx",
            known_customer="UnknownCo",
            known_initiative_type="sales_opportunity",
            known_stage="proposal",
            use_embeddings=False,
        )
        # No IBF/HongLeong pattern matches UnknownCo; cannot confidently place.
        self.assertNotEqual(pred.predicted_path, "01 Project/2026/IBF/A.2 Proposal")

    def test_no_pattern_leaves_in_inbox(self):
        engine = PlacementEngine(FakePlacementDB([]), FakeConfig())
        pred = engine.predict("INBOX/mystery.bin", use_embeddings=False)
        self.assertIsNone(pred.predicted_path)
        self.assertEqual(pred.method, "none")
        self.assertEqual(pred.confidence, 0.0)


class SimulationTests(unittest.TestCase):
    def test_simulation_scores_match_levels(self):
        files = [
            _file("01 Project/2026/IBF/A.2 Proposal/p1.pptx", customer="IBF", init_type="sales_opportunity", stage="proposal"),
            _file("01 Project/2026/IBF/A.2 Proposal/p2.pptx", customer="IBF", init_type="sales_opportunity", stage="proposal"),
            _file("01 Project/2026/IBF/A.2 Proposal/p3.pptx", customer="IBF", init_type="sales_opportunity", stage="proposal"),
        ]
        db = FakePlacementDB(files)
        engine = PlacementEngine(db, FakeConfig())
        summary = engine.simulate(run_id=1, use_embeddings=False)
        self.assertEqual(summary["total"], 3)
        # All three live in the same destination backed by their siblings, so
        # leave-one-out should still place them correctly (exact).
        self.assertGreaterEqual(summary["exact"], 1)
        self.assertEqual(len(db.saved_sims), 3)

    def test_match_level_initiative_vs_customer(self):
        self.assertEqual(
            PlacementEngine._match_level(
                "01 Project/2026/IBF/A.2 Proposal",
                "01 Project/2026/IBF/A.2 Proposal",
            ),
            "exact",
        )
        # Same root/year/customer/initiative, different stage -> initiative match.
        self.assertEqual(
            PlacementEngine._match_level(
                "01 Project/2026/IBF/Training/A.3 Other",
                "01 Project/2026/IBF/Training/A.2 Proposal",
            ),
            "initiative",
        )
        # Same root/year/customer, different initiative -> customer match.
        self.assertEqual(
            PlacementEngine._match_level(
                "01 Project/2026/IBF/Workshop/A.1",
                "01 Project/2026/IBF/Training/A.2 Proposal",
            ),
            "customer",
        )
        self.assertEqual(
            PlacementEngine._match_level("02 Ops/x", "01 Project/2026/IBF/A.2"),
            "wrong",
        )


class PlanTests(unittest.TestCase):
    def test_plan_inbox_records_no_moves(self):
        files = [
            _file("01 Project/2026/IBF/A.2 Proposal/p1.pptx", customer="IBF", init_type="sales_opportunity", stage="proposal"),
            _file("01 Project/2026/IBF/A.2 Proposal/p2.pptx", customer="IBF", init_type="sales_opportunity", stage="proposal"),
            _file("00 Agent Inbox/IBF_Proposal.pptx"),
        ]
        db = FakePlacementDB(files)
        engine = PlacementEngine(db, FakeConfig())
        plans = engine.plan_inbox(run_id=1, inbox_prefixes=("00",), use_embeddings=False)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].file_path, "00 Agent Inbox/IBF_Proposal.pptx")
        self.assertEqual(len(db.saved_plans), 1)
        self.assertIn("confidence_band", db.saved_plans[0])


if __name__ == "__main__":
    unittest.main()
