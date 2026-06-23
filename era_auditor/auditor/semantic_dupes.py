"""Semantic duplicate detection bridging era_indexer's pgvector embeddings.

Physical duplicate detection (SHA256) catches byte-identical copies.
This module catches the other 90 percent: re-saved decks, edited copies,
"v2 final" documents whose CONTENT is nearly the same even though their
bytes differ.

It reuses the indexer's existing tables in the same Postgres instance:
- file_registry (file_path, file_name, file_hash)
- document_chunks (file_id, embedding vector(1024))

Per candidate file pair sharing no content hash, the mean chunk embedding
of each file is compared with cosine distance in SQL. Pairs above the
configured similarity threshold become `semantic_duplication` findings.

Everything degrades gracefully: when the indexer tables are absent, empty,
or pgvector is not installed, the detector is a silent no-op so the auditor
never depends on the indexer being populated.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import AppConfig
from .models import AuditFinding

logger = logging.getLogger(__name__)

# Indexer file types worth comparing semantically.
SEMANTIC_FILE_TYPES = ("pdf", "docx", "doc", "pptx", "ppt", "md", "txt")

# Working-set affixes: a human deliberately derived these from a base file
# (slide exports, version snapshots, sync-conflict copies). Pairs that differ
# only by such an affix and live in the same initiative are intentional, not
# duplicate maintenance effort, so they never generate findings.
_WORKINGSET_AFFIXES = [
    re.compile(r"^page\s*\d+[ _-]?", re.IGNORECASE),        # Page12_, Page 6
    re.compile(r"^v\d+(\.\d+)?[ _-]?", re.IGNORECASE),      # V3_, v2.1
    re.compile(r"[ _-]v\d+(\.\d+)?$", re.IGNORECASE),       # _v2
    re.compile(r"[ _-]?\(\d+\)$"),                          # (1), (2)
    re.compile(r"[ _-]?_?conflict.*$", re.IGNORECASE),      # _Conflict, sync conflict
    re.compile(r"[ _-]?copy$", re.IGNORECASE),              # copy
    re.compile(r"[ _-]?final$", re.IGNORECASE),             # final
    re.compile(r"[ _-]?draft$", re.IGNORECASE),             # draft
]

# Path segments that mark dependency/code/settings noise. The indexer embeds
# these (it has its own ignore rules), but the auditor must never surface them
# as knowledge duplicates. Mirrors scanner.ignore_names for the common cases.
_EXCLUDED_PATH_SEGMENTS = (
    "/.venv/",
    "/venv/",
    "/.conda/",
    "/node_modules/",
    "/__pycache__/",
    "/.git/",
    "/site-packages/",
    "/dist-info/",
    "/.cache/",
)

PAIRWISE_SIMILARITY_SQL = """
WITH file_vectors AS (
    SELECT
        fr.id,
        fr.file_path,
        fr.file_name,
        fr.file_hash,
        AVG(dc.embedding) AS mean_embedding,
        COUNT(dc.id) AS chunk_count
    FROM file_registry fr
    JOIN document_chunks dc ON dc.file_id = fr.id
    WHERE dc.embedding IS NOT NULL
      AND fr.file_type = ANY(:file_types)
      AND fr.file_path LIKE :path_prefix
      AND fr.file_path NOT LIKE ALL(:excluded_segments)
    GROUP BY fr.id, fr.file_path, fr.file_name, fr.file_hash
    HAVING COUNT(dc.id) >= :min_chunks
)
SELECT
    a.file_path AS path_a,
    b.file_path AS path_b,
    a.file_name AS name_a,
    b.file_name AS name_b,
    1 - (a.mean_embedding <=> b.mean_embedding) AS similarity
FROM file_vectors a
JOIN file_vectors b
  ON a.id < b.id
 AND a.file_hash IS DISTINCT FROM b.file_hash
WHERE 1 - (a.mean_embedding <=> b.mean_embedding) >= :threshold
ORDER BY similarity DESC
LIMIT :max_pairs
"""


class SemanticDuplicateDetector:
    def __init__(self, config: AppConfig):
        self.config = config
        self.semantic = config.semantic
        self._engine: Engine | None = None

    def _get_engine(self) -> Engine:
        if self._engine is None:
            url = (
                self.semantic.indexer_database_url
                or self.config.database.connection_string
            )
            self._engine = create_engine(url, future=True)
        return self._engine

    def detect(self) -> list[AuditFinding]:
        """Return semantic_duplication findings, or [] when unavailable.

        Steward behaviour: instead of one finding per similar PAIR (which
        explodes O(n^2) for a folder of slide exports), transitively-similar
        files are grouped into one CLUSTER and reported once. Working-set
        derivations (PageN/Vn/_Conflict siblings inside the same initiative)
        are suppressed entirely - a human deliberately created them and will
        not struggle to find them.
        """
        if not self.semantic.enabled:
            return []
        try:
            pairs = self._similar_pairs()
        except Exception as exc:  # missing tables, no pgvector, bad URL...
            logger.info("Semantic duplicate detection skipped: %s", exc)
            return []
        return self._findings_from_pairs(pairs)

    def _findings_from_pairs(
        self, pairs: list[dict[str, Any]]
    ) -> list[AuditFinding]:
        # Drop intentional working-set derivations and temporal-partition
        # entries (e.g. distinct daily todo notes) before clustering.
        kept = [
            p
            for p in pairs
            if not _is_workingset_pair(p) and not _is_temporal_pair(p)
        ]
        if not kept:
            return []

        # Union-find over file paths to build transitive clusters.
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        meta: dict[str, dict[str, Any]] = {}
        for pair in kept:
            a, b = pair["path_a"], pair["path_b"]
            union(a, b)
            meta.setdefault(a, {"root": pair["root"], "name": pair["name_a"]})
            meta.setdefault(b, {"root": pair["root"], "name": pair["name_b"]})

        clusters: dict[str, list[dict[str, Any]]] = {}
        for pair in kept:
            root_key = find(pair["path_a"])
            clusters.setdefault(root_key, []).append(pair)

        findings: list[AuditFinding] = []
        for cluster_pairs in clusters.values():
            findings.append(self._finding_for_cluster(cluster_pairs, meta))
        return findings

    def _finding_for_cluster(
        self,
        cluster_pairs: list[dict[str, Any]],
        meta: dict[str, dict[str, Any]],
    ) -> AuditFinding:
        paths: set[str] = set()
        max_similarity = 0.0
        for pair in cluster_pairs:
            paths.add(pair["path_a"])
            paths.add(pair["path_b"])
            max_similarity = max(max_similarity, float(pair["similarity"]))
        root = cluster_pairs[0]["root"]
        rel_paths = sorted(_relativize(p, root) for p in paths)
        names = sorted({meta[p]["name"] for p in paths})
        folder_path = rel_paths[0].rsplit("/", 1)[0] if "/" in rel_paths[0] else rel_paths[0]

        # Same-initiative clusters are a tidy-up nudge (low); clusters that
        # span different folders/initiatives mean genuine duplicate
        # maintenance effort across the vault (medium).
        same_initiative = len({_initiative_key(p) for p in rel_paths}) == 1
        severity = "low" if same_initiative else "medium"

        if len(paths) > 2:
            subject = (
                f"{len(paths)} near-identical files "
                f"({', '.join(names[:4])}{'...' if len(names) > 4 else ''})"
            )
        else:
            subject = f"'{names[0]}' and '{names[-1]}'"
        shown = ", ".join(f"`{p}`" for p in rel_paths[:6])
        scope = (
            "within one initiative (likely working drafts/exports - tidy up "
            "if you no longer need every copy)"
            if same_initiative
            else "across different folders, creating duplicate maintenance effort"
        )
        return AuditFinding(
            folder_path=folder_path,
            issue_type="semantic_duplication",
            severity=severity,
            confidence=round(min(max_similarity, 0.99), 2),
            suggested_action="review",
            suggested_destination=None,
            reasoning=(
                f"{subject} are {max_similarity:.0%} semantically similar "
                f"{scope}. Files: {shown}. Keep one canonical version or "
                "document why each copy exists."
            ),
        )

    def _similar_pairs(self) -> list[dict[str, Any]]:
        engine = self._get_engine()
        results: list[dict[str, Any]] = []
        roots = [root.rstrip("/") for root in self.config.paths.source_directories]
        with engine.begin() as conn:
            for root in roots:
                rows = conn.execute(
                    text(PAIRWISE_SIMILARITY_SQL),
                    {
                        "file_types": list(SEMANTIC_FILE_TYPES),
                        "path_prefix": f"{root}/%",
                        "excluded_segments": [f"%{seg}%" for seg in _EXCLUDED_PATH_SEGMENTS],
                        "min_chunks": self.semantic.min_chunks,
                        "threshold": self.semantic.similarity_threshold,
                        "max_pairs": self.semantic.max_pairs,
                    },
                ).mappings().all()
                for row in rows:
                    record = dict(row)
                    record["root"] = root
                    results.append(record)
        return results


def _relativize(path: str, root: str) -> str:
    prefix = f"{root}/"
    return path[len(prefix):] if path.startswith(prefix) else path


def _initiative_key(rel_path: str) -> str:
    """Best-effort initiative identity: the parent folder of the file.

    Two files in the same parent folder (or sibling working folders like
    `V2 - Resources`) are treated as one working set.
    """
    folder = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
    # Collapse trailing container folders (Resources, V2 - Resources, drafts)
    # so a deck and its `Resources/` copy share an initiative key.
    parts = folder.split("/")
    while parts and _is_container_segment(parts[-1]):
        parts.pop()
    return "/".join(parts)


def _is_container_segment(segment: str) -> bool:
    norm = segment.strip().lower()
    if not norm:
        return False
    if "resource" in norm or norm in {"drafts", "draft", "final", "materials"}:
        return True
    if re.match(r"^v\d+([ _-].*)?$", norm) or norm.startswith("version"):
        return True
    return False


def _stem_without_affixes(file_name: str) -> str:
    """Strip extension and known working-set affixes to get the base stem."""
    stem = os.path.splitext(file_name)[0].strip()
    changed = True
    while changed:
        changed = False
        for pattern in _WORKINGSET_AFFIXES:
            new = pattern.sub("", stem).strip(" _-")
            if new != stem and new:
                stem = new
                changed = True
    return stem.lower()


# Temporal partition folders (years, months) and date-stamped filenames.
_TEMPORAL_SEGMENT = re.compile(
    r"^(20\d{2}|q[1-4]|sprint[ _-]?\d+|week[ _-]?\d+|"
    r"(0?[1-9]|1[0-2])[._ -]?(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*|"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*)$",
    re.IGNORECASE,
)
_DATE_STAMPED_NAME = re.compile(
    r"\d{1,2}\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*\s*\d{2,4}",
    re.IGNORECASE,
)


def _is_temporal_pair(pair: dict[str, Any]) -> bool:
    """True when both files live under a temporal partition (year/month/sprint)
    or carry date-stamped names. Distinct daily notes, sprint reviews, and
    monthly reports are intentional time-series entries, not duplicates.
    """
    root = pair["root"]
    for key in ("path_a", "path_b"):
        rel = _relativize(pair[key], root)
        segments = rel.split("/")[:-1]  # folders only
        if not any(_TEMPORAL_SEGMENT.match(seg.strip()) for seg in segments):
            return False
    # Both sit under a temporal partition: only suppress when the file names
    # themselves differ by date (genuine time-series), not identical re-saves.
    if pair["name_a"] == pair["name_b"]:
        return False
    return bool(
        _DATE_STAMPED_NAME.search(pair["name_a"])
        or _DATE_STAMPED_NAME.search(pair["name_b"])
    )


def _is_workingset_pair(pair: dict[str, Any]) -> bool:
    """True when two files are the same base asset differing only by a
    working-set affix (PageN/Vn/_Conflict/copy) AND live in the same
    initiative. Such pairs are intentional derivations, never findings.
    """
    root = pair["root"]
    rel_a = _relativize(pair["path_a"], root)
    rel_b = _relativize(pair["path_b"], root)
    if _initiative_key(rel_a) != _initiative_key(rel_b):
        return False
    stem_a = _stem_without_affixes(pair["name_a"])
    stem_b = _stem_without_affixes(pair["name_b"])
    if not stem_a or not stem_b:
        return False
    # Same base stem (or one is a prefix of the other for page exports).
    return stem_a == stem_b or stem_a.startswith(stem_b) or stem_b.startswith(stem_a)
