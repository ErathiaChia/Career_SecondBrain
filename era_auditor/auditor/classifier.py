from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field, ValidationError

from .config import AppConfig
from .constitution import FolderConstitution
from .db import AuditorDatabase
from .models import FolderClassification, FolderRecord

if TYPE_CHECKING:
    from .openai_client import OpenAIClient

# Folders classified per OpenAI call. Most folders resolve deterministically,
# so a single run usually needs only a few batched calls.
BATCH_SIZE = 30


class BatchItemClassification(FolderClassification):
    """Lenient view of a classification item as returned by the LLM.

    The model occasionally omits `confidence` or `reasoning` for an item. A
    single sloppy item must NOT abort the whole batch (and the whole run), so
    we relax those two fields here and backfill safe defaults when mapping into
    the strict ``FolderClassification`` used everywhere else.
    """

    path: str
    confidence: float = Field(default=0.2, ge=0.0, le=1.0)
    reasoning: str = "Model omitted reasoning; treated as low-confidence."


class BatchClassificationResponse(BaseModel):
    classifications: list[BatchItemClassification]


def load_rules(config: AppConfig) -> dict:
    rules_path = config.base_dir / "auditor" / "rules" / "organization_rules.yaml"
    return yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}


class FolderClassifier:
    def __init__(self, config: AppConfig, database: AuditorDatabase, client: OpenAIClient):
        self.config = config
        self.database = database
        self.client = client
        self.constitution = FolderConstitution(config)
        self.rules = self.constitution.as_prompt_payload()
        self.prompt = client.load_prompt("classify_folder.md")

    def classify_pending(self, run_id: int, limit: int | None = None, full: bool = False) -> int:
        folders = self.database.folders_for_classification(limit=limit, full=full)

        # Deterministic-first: only folders without a constitution match go to
        # the LLM, in batches.
        pending_ai: list[FolderRecord] = []
        for folder in folders:
            deterministic = self.constitution.classify_deterministic(folder)
            if deterministic:
                self.database.save_classification(run_id, folder, deterministic)
            else:
                pending_ai.append(folder)

        for start in range(0, len(pending_ai), BATCH_SIZE):
            batch = pending_ai[start : start + BATCH_SIZE]
            for folder, classification in self._classify_batch(batch):
                self.database.save_classification(run_id, folder, classification)
        return len(folders)

    def classify_folder(self, folder: FolderRecord) -> FolderClassification:
        deterministic = self.constitution.classify_deterministic(folder)
        if deterministic:
            return deterministic
        results = self._classify_batch([folder])
        return results[0][1]

    def _classify_batch(
        self,
        folders: list[FolderRecord],
    ) -> list[tuple[FolderRecord, FolderClassification]]:
        if not folders:
            return []
        payload = {
            "folders": [
                {
                    "path": folder.path,
                    "parent": folder.parent_path,
                    "depth": folder.depth,
                    "file_count": folder.file_count,
                    "child_folder_count": folder.child_folder_count,
                    "sample_filenames": folder.sample_filenames,
                    "root_category": folder.path.split("/")[0] if folder.path != "." else ".",
                }
                for folder in folders
            ],
            "constitution": self.rules,
            "instructions": {
                "note": (
                    "Classify every folder in `folders`. Return one entry per "
                    "folder with its `path` echoed back. If a folder matches the "
                    "constitution, use that role instead of generic folder-name "
                    "assumptions."
                ),
            },
        }
        response = self.client.json_completion(self.prompt, payload, BatchClassificationResponse)
        by_path = {item.path: item for item in response.classifications}

        results: list[tuple[FolderRecord, FolderClassification]] = []
        for folder in folders:
            item = by_path.get(folder.path)
            if item is None:
                classification = FolderClassification(
                    folder_type="unknown",
                    confidence=0.2,
                    reasoning="Model did not return a classification for this folder.",
                )
            else:
                try:
                    classification = FolderClassification(
                        **item.model_dump(exclude={"path"})
                    )
                except ValidationError:
                    # An out-of-range value (e.g. an unknown folder_type) for a
                    # single item must not sink the run; degrade to unknown.
                    classification = FolderClassification(
                        folder_type="unknown",
                        confidence=0.2,
                        reasoning="Model returned an invalid classification; treated as unknown.",
                    )
            results.append((folder, classification))
        return results
