"""Placement Intelligence Engine (Librarian training).

The repository the user already built is treated as labeled training data:
every placed file is an example of where THIS user puts files like it. This
module learns placement patterns from those examples and predicts where a new
file would go, using a hybrid strategy:

1. Deterministic first  - learned patterns keyed by
   (customer, initiative_type, stage, file_kind) plus filename signals, and
   the project registry's canonical paths.
2. Embedding second     - nearest-neighbour vote over era_indexer embeddings:
   the destination folders of the most semantically similar placed files.
3. LLM last (optional)  - only consulted for ambiguous cases, behind a flag.

Phase 1 is learn + simulate + plan only. No files are ever moved here.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import AppConfig
from .db import AuditorDatabase

logger = logging.getLogger(__name__)

# Confidence bands per the directive: >0.95 auto-place, 0.75-0.95 suggest,
# <0.75 leave in inbox / needs review. Phase 1 never auto-moves; the band is
# recorded so Phase 2 can act on it.
AUTO_PLACE_THRESHOLD = 0.95
SUGGEST_THRESHOLD = 0.75


def confidence_band(confidence: float) -> str:
    if confidence >= AUTO_PLACE_THRESHOLD:
        return "auto_place"
    if confidence >= SUGGEST_THRESHOLD:
        return "suggest"
    return "needs_review"


# File kind buckets - coarser than extension, the unit the Librarian reasons in.
_KIND_BY_EXT: dict[str, str] = {
    ".pdf": "document",
    ".doc": "document",
    ".docx": "document",
    ".md": "note",
    ".txt": "note",
    ".rtf": "document",
    ".ppt": "presentation",
    ".pptx": "presentation",
    ".key": "presentation",
    ".xls": "spreadsheet",
    ".xlsx": "spreadsheet",
    ".csv": "spreadsheet",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".svg": "image",
    ".mp4": "video",
    ".mov": "video",
    ".drawio": "diagram",
    ".vsdx": "diagram",
}


def file_kind(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return _KIND_BY_EXT.get(ext, "other")


# Filename signal vocabulary: tokens that hint at the stage/intent of a file.
# These are the human-readable cues a person uses when filing by hand.
_NAME_SIGNALS: dict[str, str] = {
    "proposal": "proposal",
    "rfp": "proposal",
    "rfi": "proposal",
    "sow": "proposal",
    "quote": "proposal",
    "quotation": "proposal",
    "pricing": "proposal",
    "poc": "poc",
    "demo": "demo",
    "workshop": "workshop",
    "presentation": "presentation",
    "deck": "presentation",
    "slides": "presentation",
    "agenda": "meeting",
    "minutes": "meeting",
    "mom": "meeting",
    "notes": "notes",
    "report": "report",
    "summary": "report",
    "architecture": "architecture",
    "design": "architecture",
    "diagram": "architecture",
    "contract": "legal",
    "nda": "legal",
    "invoice": "finance",
}


def name_signals(filename: str) -> list[str]:
    stem = os.path.splitext(filename)[0].lower()
    tokens = re.split(r"[\s_\-.]+", stem)
    found = []
    for tok in tokens:
        sig = _NAME_SIGNALS.get(tok)
        if sig and sig not in found:
            found.append(sig)
    return found


def parent_folder(path: str) -> str:
    """Destination = the folder a file sits in (its parent directory)."""
    return path.rsplit("/", 1)[0] if "/" in path else ""


@dataclass
class PlacementPrediction:
    file_path: str
    predicted_path: str | None
    confidence: float
    method: str
    rationale: str

    def as_plan_row(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "predicted_path": self.predicted_path,
            "confidence": round(self.confidence, 4),
            "confidence_band": confidence_band(self.confidence),
            "method": self.method,
            "rationale": self.rationale,
        }


@dataclass
class _PatternStat:
    destination_path: str
    customer_code: str | None
    initiative_type: str | None
    stage: str | None
    file_kind: str | None
    name_signals: set[str] = field(default_factory=set)
    support_count: int = 0

    @property
    def pattern_key(self) -> str:
        return "|".join(
            [
                self.customer_code or "*",
                self.initiative_type or "*",
                self.stage or "*",
                self.file_kind or "*",
                self.destination_path,
            ]
        )

    def as_row(self) -> dict[str, Any]:
        return {
            "pattern_key": self.pattern_key,
            "destination_path": self.destination_path,
            "customer_code": self.customer_code,
            "initiative_type": self.initiative_type,
            "stage": self.stage,
            "file_kind": self.file_kind,
            "name_signals": sorted(self.name_signals),
            "support_count": self.support_count,
        }


# Nearest-neighbour query against era_indexer embeddings: given a target file's
# path, return the most semantically similar OTHER indexed files. We vote on
# their destination folders. Degrades to no-op when the indexer is unavailable.
_NEIGHBOUR_SQL = """
WITH target AS (
    SELECT AVG(dc.embedding) AS mean_embedding
    FROM file_registry fr
    JOIN document_chunks dc ON dc.file_id = fr.id
    WHERE dc.embedding IS NOT NULL
      AND fr.file_path LIKE :target_suffix
    GROUP BY fr.id
    LIMIT 1
),
candidates AS (
    SELECT
        fr.file_path,
        AVG(dc.embedding) AS mean_embedding
    FROM file_registry fr
    JOIN document_chunks dc ON dc.file_id = fr.id
    WHERE dc.embedding IS NOT NULL
      AND fr.file_path NOT LIKE :target_suffix
    GROUP BY fr.id, fr.file_path
)
SELECT
    c.file_path,
    1 - (c.mean_embedding <=> t.mean_embedding) AS similarity
FROM candidates c, target t
ORDER BY similarity DESC
LIMIT :k
"""


class PlacementEngine:
    """Learns placement patterns from the vault and predicts destinations.

    Read-only: the engine never moves files. It extracts patterns, scores
    blind predictions (simulation), and proposes plans for inbox files.
    """

    def __init__(self, database: AuditorDatabase, config: AppConfig):
        self.database = database
        self.config = config
        self._patterns: list[_PatternStat] = []
        self._registry: list[dict[str, Any]] = []
        self._indexer_engine: Engine | None = None
        self._neighbour_cache: dict[str, list[tuple[str, float]]] = {}

    # ------------------------------------------------------------------
    # Pattern extraction
    # ------------------------------------------------------------------

    def extract_patterns(self, exclude_paths: set[str] | None = None) -> list[_PatternStat]:
        """Build placement patterns from every placed file in the vault.

        When ``exclude_paths`` is given, those files are held out (used by the
        simulator to avoid a file voting for its own location).
        """
        exclude_paths = exclude_paths or set()
        files = self.database.placed_files_with_context()
        stats: dict[str, _PatternStat] = {}
        for f in files:
            path = f["path"]
            if path in exclude_paths:
                continue
            dest = parent_folder(path)
            if not dest:
                continue
            kind = file_kind(path.rsplit("/", 1)[-1])
            customer = f.get("customer_code") or f.get("customer_name")
            init_type = f.get("initiative_type")
            stage = f.get("stage")
            stat = _PatternStat(
                destination_path=dest,
                customer_code=customer,
                initiative_type=init_type,
                stage=stage,
                file_kind=kind,
            )
            existing = stats.get(stat.pattern_key)
            if existing is None:
                stats[stat.pattern_key] = stat
                existing = stat
            existing.support_count += 1
            existing.name_signals.update(name_signals(path.rsplit("/", 1)[-1]))
        self._patterns = sorted(
            stats.values(), key=lambda s: s.support_count, reverse=True
        )
        return self._patterns

    def refresh_patterns(self, run_id: int) -> int:
        patterns = self.extract_patterns()
        rows = [p.as_row() for p in patterns]
        return self.database.replace_placement_patterns(run_id, rows)

    # ------------------------------------------------------------------
    # Prediction (hybrid)
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._patterns:
            self.extract_patterns()
        if not self._registry:
            self._registry = self.database.projects_registry()

    def predict(
        self,
        file_path: str,
        *,
        known_customer: str | None = None,
        known_initiative_type: str | None = None,
        known_stage: str | None = None,
        use_embeddings: bool = True,
    ) -> PlacementPrediction:
        """Predict the destination folder for ``file_path``.

        Deterministic patterns first; if they are weak/absent, fall back to an
        embedding nearest-neighbour vote. LLM fallback is intentionally left as
        a Phase-2 hook (we only flag low confidence here).
        """
        self._ensure_loaded()
        det = self._predict_deterministic(
            file_path, known_customer, known_initiative_type, known_stage
        )
        if det is not None and det.confidence >= SUGGEST_THRESHOLD:
            return det

        if use_embeddings:
            emb = self._predict_embedding(file_path)
            if emb is not None and (det is None or emb.confidence > det.confidence):
                return emb

        if det is not None:
            return det
        return PlacementPrediction(
            file_path=file_path,
            predicted_path=None,
            confidence=0.0,
            method="none",
            rationale="No learned pattern or similar file found; leave in inbox for review.",
        )

    def _predict_deterministic(
        self,
        file_path: str,
        customer: str | None,
        init_type: str | None,
        stage: str | None,
    ) -> PlacementPrediction | None:
        name = file_path.rsplit("/", 1)[-1]
        kind = file_kind(name)
        signals = set(name_signals(name))

        best: tuple[float, _PatternStat] | None = None
        for stat in self._patterns:
            score, matched = self._match_score(
                stat, customer, init_type, stage, kind, signals
            )
            if score <= 0:
                continue
            # Confidence blends specificity (how many context keys matched) with
            # support (how many real files back this pattern).
            support_factor = min(stat.support_count / 5.0, 1.0)
            confidence = min(0.40 + 0.5 * score + 0.1 * support_factor, 0.99)
            if best is None or confidence > best[0]:
                best = (confidence, stat)

        if best is None:
            return None
        confidence, stat = best
        return PlacementPrediction(
            file_path=file_path,
            predicted_path=stat.destination_path,
            confidence=confidence,
            method="deterministic",
            rationale=(
                f"Matches learned pattern (customer={stat.customer_code or 'any'}, "
                f"initiative_type={stat.initiative_type or 'any'}, stage={stat.stage or 'any'}, "
                f"kind={stat.file_kind or 'any'}) backed by {stat.support_count} placed file(s)."
            ),
        )

    @staticmethod
    def _match_score(
        stat: _PatternStat,
        customer: str | None,
        init_type: str | None,
        stage: str | None,
        kind: str,
        signals: set[str],
    ) -> tuple[float, int]:
        """Weighted overlap between a candidate file's context and a pattern.

        Returns (normalized_score in 0..1, matched_keys). A mismatch on a known
        key (e.g. wrong customer) disqualifies the pattern entirely.
        """
        score = 0.0
        matched = 0
        # Customer is the strongest signal.
        if stat.customer_code is not None:
            if customer is None:
                return 0.0, 0
            if customer != stat.customer_code:
                return 0.0, 0
            score += 0.45
            matched += 1
        if stat.initiative_type is not None:
            if init_type is not None and init_type != stat.initiative_type:
                return 0.0, 0
            if init_type == stat.initiative_type:
                score += 0.20
                matched += 1
        if stat.stage is not None:
            if stage is not None and stage != stat.stage:
                return 0.0, 0
            if stage == stat.stage:
                score += 0.15
                matched += 1
        if stat.file_kind is not None and stat.file_kind == kind:
            score += 0.10
            matched += 1
        if stat.name_signals and signals & stat.name_signals:
            score += 0.10
            matched += 1
        return min(score, 1.0), matched

    # ------------------------------------------------------------------
    # Embedding nearest-neighbour fallback
    # ------------------------------------------------------------------

    def _get_indexer_engine(self) -> Engine | None:
        if self._indexer_engine is None:
            url = (
                self.config.semantic.indexer_database_url
                or self.config.database.connection_string
            )
            try:
                self._indexer_engine = create_engine(url, future=True)
            except Exception as exc:  # pragma: no cover - config/driver issues
                logger.info("Placement embedding engine unavailable: %s", exc)
                return None
        return self._indexer_engine

    def _neighbours(self, file_path: str, k: int = 8) -> list[tuple[str, float]]:
        if file_path in self._neighbour_cache:
            return self._neighbour_cache[file_path]
        engine = self._get_indexer_engine()
        if engine is None:
            return []
        # Match on a path suffix because indexer paths may be absolute while
        # auditor paths are vault-relative.
        suffix = "%" + file_path.rsplit("/", 1)[-1]
        try:
            with engine.begin() as conn:
                rows = conn.execute(
                    text(_NEIGHBOUR_SQL),
                    {"target_suffix": suffix, "k": k},
                ).mappings().all()
        except Exception as exc:  # missing tables / no pgvector
            logger.info("Placement neighbour lookup skipped: %s", exc)
            self._neighbour_cache[file_path] = []
            return []
        result = [(r["file_path"], float(r["similarity"])) for r in rows]
        self._neighbour_cache[file_path] = result
        return result

    def _predict_embedding(self, file_path: str) -> PlacementPrediction | None:
        neighbours = self._neighbours(file_path)
        if not neighbours:
            return None
        # Vote on neighbour destination folders, weighted by similarity.
        votes: dict[str, float] = defaultdict(float)
        for path, sim in neighbours:
            dest = parent_folder(self._relativize(path))
            if dest:
                votes[dest] += max(sim, 0.0)
        if not votes:
            return None
        total = sum(votes.values()) or 1.0
        best_dest, best_weight = max(votes.items(), key=lambda kv: kv[1])
        share = best_weight / total
        top_sim = max(sim for _, sim in neighbours)
        # Confidence = agreement among neighbours * how similar they are.
        confidence = round(min(share * top_sim, 0.95), 4)
        return PlacementPrediction(
            file_path=file_path,
            predicted_path=best_dest,
            confidence=confidence,
            method="embedding",
            rationale=(
                f"{len(neighbours)} most-similar placed files agree on '{best_dest}' "
                f"({share:.0%} of weighted vote, top similarity {top_sim:.0%})."
            ),
        )

    def _relativize(self, path: str) -> str:
        """Strip the vault base dir prefix from an indexer (absolute) path."""
        base = str(self.config.base_dir)
        if path.startswith(base):
            path = path[len(base):].lstrip("/")
        return path

    # ------------------------------------------------------------------
    # Simulation: blind predictions on already-placed files
    # ------------------------------------------------------------------

    def simulate(
        self,
        run_id: int | None = None,
        sample: int | None = None,
        use_embeddings: bool = True,
    ) -> dict[str, Any]:
        """Measure placement accuracy by predicting placed files blind.

        For each sampled file we hide its actual location, rebuild patterns
        without it (leave-one-out at the pattern level), predict, then score:
        - exact:      predicted folder == actual folder
        - initiative: predicted folder shares the initiative path of the actual
        - customer:   predicted folder shares the customer segment
        - wrong:      none of the above
        """
        files = self.database.placed_files_with_context()
        if sample is not None and sample < len(files):
            # Deterministic stride sampling for reproducibility.
            step = max(len(files) // sample, 1)
            files = files[::step][:sample]

        # Build patterns once excluding the whole sample, so no sampled file
        # contributes to the patterns used to predict it.
        sample_paths = {f["path"] for f in files}
        self.extract_patterns(exclude_paths=sample_paths)
        self._registry = self.database.projects_registry()

        results: list[dict[str, Any]] = []
        counts = Counter()
        for f in files:
            path = f["path"]
            actual = parent_folder(path)
            pred = self.predict(
                path,
                known_customer=f.get("customer_code") or f.get("customer_name"),
                known_initiative_type=f.get("initiative_type"),
                known_stage=f.get("stage"),
                use_embeddings=use_embeddings,
            )
            level = self._match_level(pred.predicted_path, actual)
            counts[level] += 1
            results.append(
                {
                    "file_path": path,
                    "actual_path": actual,
                    "predicted_path": pred.predicted_path,
                    "confidence": round(pred.confidence, 4),
                    "match_level": level,
                    "method": pred.method,
                    "rationale": pred.rationale,
                }
            )

        # Restore full patterns after simulation.
        self.extract_patterns()
        total = len(results) or 1
        summary = {
            "total": len(results),
            "exact": counts["exact"],
            "initiative": counts["initiative"],
            "customer": counts["customer"],
            "wrong": counts["wrong"],
            "exact_accuracy": round(counts["exact"] / total, 4),
            "initiative_accuracy": round(
                (counts["exact"] + counts["initiative"]) / total, 4
            ),
            "customer_accuracy": round(
                (counts["exact"] + counts["initiative"] + counts["customer"]) / total,
                4,
            ),
            "results": results,
        }
        if run_id is not None:
            self.database.save_placement_simulations(run_id, results)
        return summary

    @staticmethod
    def _match_level(predicted: str | None, actual: str) -> str:
        if not predicted:
            return "wrong"
        if predicted == actual:
            return "exact"
        pred_parts = predicted.split("/")
        act_parts = actual.split("/")
        # Initiative match: share the first 4 path segments (root/year/cust/init)
        # or one is a prefix of the other below the customer level.
        depth = min(len(pred_parts), len(act_parts))
        if depth >= 4 and pred_parts[:4] == act_parts[:4]:
            return "initiative"
        # Customer match: share the first 3 segments (root/year/customer).
        if depth >= 3 and pred_parts[:3] == act_parts[:3]:
            return "customer"
        return "wrong"

    # ------------------------------------------------------------------
    # Inbox plans: predict destinations for staged/inbox files (no moves)
    # ------------------------------------------------------------------

    def plan_inbox(
        self,
        run_id: int | None = None,
        inbox_prefixes: tuple[str, ...] = ("00",),
        use_embeddings: bool = True,
    ) -> list[PlacementPrediction]:
        """Predict destinations for files currently in inbox/staging folders.

        Identifies files whose top-level root looks like an inbox (default any
        root starting with '00', e.g. '00 Agent Inbox'). Phase 1 records plans
        only - nothing is moved.
        """
        self._ensure_loaded()
        files = self.database.placed_files_with_context()
        plans: list[PlacementPrediction] = []
        for f in files:
            path = f["path"]
            root = path.split("/")[0]
            if not any(root.startswith(pfx) for pfx in inbox_prefixes):
                continue
            pred = self.predict(path, use_embeddings=use_embeddings)
            plans.append(pred)
        if run_id is not None and plans:
            self.database.save_placement_plans(
                run_id, [p.as_plan_row() for p in plans]
            )
        return plans
