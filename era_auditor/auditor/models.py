from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


FolderType = Literal[
    "root",
    "inbox",
    "temporal",
    "customer",
    "initiative",
    "stage",
    "project_artifact",
    "project",
    "resource",
    "product",
    "administration",
    "operations",
    "template",
    "knowledge_asset",
    "archive",
    "code_repo",
    "unknown",
]
Severity = Literal["low", "medium", "high"]
SuggestedAction = Literal[
    "review",
    "move",
    "rename",
    "renumber",
    "split",
    "archive",
    "leave_as_is",
    "enrich_registry",
    "standardize",
    "document_decision",
]


class FolderSnapshot(BaseModel):
    root_path: str
    path: str
    absolute_path: str
    parent_path: str | None = None
    depth: int
    file_count: int = 0
    child_folder_count: int = 0
    total_size_bytes: int = 0
    latest_modified_at: datetime | None = None
    sample_filenames: list[str] = Field(default_factory=list)
    file_extension_counts: dict[str, int] = Field(default_factory=dict)
    file_category_counts: dict[str, int] = Field(default_factory=dict)
    metadata_signals: dict[str, object] = Field(default_factory=dict)
    content_signature: str


class FileSnapshot(BaseModel):
    root_path: str
    folder_path: str
    path: str
    absolute_path: str
    extension: str = ""
    size_bytes: int = 0
    modified_at: datetime | None = None
    content_hash: str | None = None


class ScanResult(BaseModel):
    scanned_at: datetime
    folders: list[FolderSnapshot]
    files: list[FileSnapshot]


InitiativeType = Literal[
    "sales_opportunity",
    "delivery_project",
    "workshop",
    "strategic_initiative",
    "architecture_artifact",
    "research_activity",
    "support_activity",
    "training_engagement",
]


class FolderClassification(BaseModel):
    folder_type: FolderType
    customer: str | None = None
    initiative: str | None = None
    initiative_type: str | None = None
    root_category: str | None = None
    customer_code: str | None = None
    customer_name: str | None = None
    stage: str | None = None
    is_intentional_empty: bool = False
    template_status: str | None = None
    matched_rule: str | None = None
    registry_project_id: str | None = None
    registry_customer_id: str | None = None
    classification_source: str | None = None
    classification_role: str | None = None
    confidence_reason: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class KnowledgeAsset(BaseModel):
    """A distinct knowledge asset (deck, document, spreadsheet, media file).

    Identity is the content hash when available, otherwise the normalized
    file name. The registry tracks WHERE the asset lives and HOW OFTEN it is
    reused across projects and customers - the auditor's unit of reasoning.
    """

    asset_key: str
    asset_name: str
    file_hash: str | None = None
    file_type: str = "other"
    size_bytes: int = 0
    copy_count: int = 1
    paths: list[str] = Field(default_factory=list)
    customer_count: int = 0
    customers: list[str] = Field(default_factory=list)
    project_count: int = 0
    projects: list[str] = Field(default_factory=list)
    root_count: int = 1
    reuse_score: int = Field(default=0, ge=0, le=100)
    canonical_location: str | None = None
    in_resources: bool = False
    # Asset family: stemmed name shared by working-set derivations (Page6/V3/...)
    # so the Librarian reasons about the logical asset, not each variant.
    family_key: str | None = None


class AuditFinding(BaseModel):
    folder_path: str
    issue_type: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_action: SuggestedAction
    suggested_destination: str | None = None
    reasoning: str


class FolderScore(BaseModel):
    folder_id: int
    folder_path: str
    naming_consistency: int = Field(ge=0, le=100)
    duplicate_risk: int = Field(ge=0, le=100)
    placement_confidence: int = Field(ge=0, le=100)
    structure_clarity: int = Field(ge=0, le=100)
    rules_compliance: int = Field(ge=0, le=100)
    total_score: int = Field(ge=0, le=100)
    explanation: str


class FolderRecord(BaseModel):
    id: int
    root_path: str
    path: str
    absolute_path: str
    parent_path: str | None
    depth: int
    file_count: int
    child_folder_count: int
    total_size_bytes: int
    latest_modified_at: datetime | None
    sample_filenames: list[str]
    file_extension_counts: dict[str, int] = Field(default_factory=dict)
    file_category_counts: dict[str, int] = Field(default_factory=dict)
    metadata_signals: dict[str, object] = Field(default_factory=dict)
    content_signature: str

    @property
    def name(self) -> str:
        return Path(self.path).name or self.path
