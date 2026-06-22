from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


class DatabaseConfig(BaseModel):
    connection_string: str

    @field_validator("connection_string")
    @classmethod
    def connection_string_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "database.connection_string is empty. Set AUDITOR_DATABASE_URL, "
                "or set ERA_VAULT_DB_HOST, ERA_VAULT_DB_PORT, ERA_VAULT_DB_NAME, "
                "ERA_VAULT_DB_USER, and ERA_VAULT_DB_PASSWORD."
            )
        return value


class OpenAIConfig(BaseModel):
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4.1-mini"
    temperature: float = 0.1
    max_retries: int = 3


class PathsConfig(BaseModel):
    source_directories: list[str]
    report_directory: str = "reports"


class ScannerConfig(BaseModel):
    sample_file_limit: int = 12
    max_depth: int | None = None
    ignore_names: list[str] = Field(default_factory=list)
    ignore_suffixes: list[str] = Field(default_factory=list)
    # Relative-path globs (from each scan root) whose entire subtree is skipped.
    ignore_subtrees: list[str] = Field(default_factory=list)
    # Filenames that mark a folder as a code repository. Code repos are
    # recorded as a single opaque leaf folder and never descended into.
    code_repo_markers: list[str] = Field(
        default_factory=lambda: [
            ".git",
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "Cargo.toml",
            "go.mod",
        ]
    )


class AuditorConfig(BaseModel):
    default_limit: int = 50
    high_confidence_threshold: float = 0.85
    medium_confidence_threshold: float = 0.65
    changed_context_depth: int = 1


class SemanticConfig(BaseModel):
    """Semantic duplicate detection via era_indexer's pgvector embeddings."""

    enabled: bool = True
    # Cosine similarity above which two files are flagged as semantic dupes.
    similarity_threshold: float = 0.92
    # Minimum embedded chunks per file for a stable mean embedding.
    min_chunks: int = 2
    # Raw similar pairs fetched per scan root before clustering collapses them.
    max_pairs: int = 200
    # Defaults to the auditor's own database when unset (indexer shares it).
    indexer_database_url: str | None = None


class AppConfig(BaseModel):
    database: DatabaseConfig
    openai: OpenAIConfig
    paths: PathsConfig
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    auditor: AuditorConfig = Field(default_factory=AuditorConfig)
    semantic: SemanticConfig = Field(default_factory=SemanticConfig)
    config_path: Path
    base_dir: Path


def expand_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        return os.getenv(name, default or "")

    return ENV_PATTERN.sub(replace, value)


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    path = Path(config_path).expanduser().resolve()
    base_dir = path.parent
    workspace_dir = base_dir.parent
    # Keep secrets centralized at the workspace root. Shell environment values
    # still win because python-dotenv does not override existing variables.
    load_dotenv(workspace_dir / ".env")
    ensure_auditor_database_url()

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    expanded = expand_env(raw)
    expanded["config_path"] = path
    expanded["base_dir"] = base_dir
    return AppConfig.model_validate(expanded)


def ensure_auditor_database_url() -> None:
    if os.getenv("AUDITOR_DATABASE_URL"):
        return

    required = {
        "host": os.getenv("ERA_VAULT_DB_HOST"),
        "port": os.getenv("ERA_VAULT_DB_PORT"),
        "name": os.getenv("ERA_VAULT_DB_NAME"),
        "user": os.getenv("ERA_VAULT_DB_USER"),
        "password": os.getenv("ERA_VAULT_DB_PASSWORD"),
    }
    if not all(required.values()):
        return

    user = quote_plus(required["user"] or "")
    password = quote_plus(required["password"] or "")
    host = required["host"]
    port = required["port"]
    name = required["name"]
    os.environ["AUDITOR_DATABASE_URL"] = f"postgresql://{user}:{password}@{host}:{port}/{name}"


def resolve_report_directory(config: AppConfig) -> Path:
    report_dir = Path(config.paths.report_directory)
    if not report_dir.is_absolute():
        report_dir = config.base_dir / report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir
