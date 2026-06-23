"""Configuration loading. Single source of truth; lazy-loaded once per process."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, TypedDict

import yaml

from career_history import envfile


FileKind = Literal["all", "documents", "audio"]


class RunSettings(TypedDict):
    """Normalized selection for which file kinds a run should include."""

    file_kind: FileKind
    label: str


_config: dict[str, Any] | None = None


def load(path: str | Path = "config.yaml") -> dict[str, Any]:
    """Load YAML config; cache result. HF_TOKEN env var overrides file value."""
    global _config
    if _config is not None:
        return _config

    envfile.load()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Config not found at {p.resolve()}. "
            f"Copy config.yaml.example to config.yaml first."
        )
    with open(p) as f:
        _config = yaml.safe_load(f) or {}

    env_token = os.environ.get("HF_TOKEN", "").strip()
    if env_token:
        _config.setdefault("huggingface", {})["token"] = env_token

    return _config


def get() -> dict[str, Any]:
    if _config is None:
        raise RuntimeError("Config not loaded. Call career_history.config.load() first.")
    return _config


def run_everything() -> RunSettings:
    return {"file_kind": "all", "label": "everything"}


def run_documents() -> RunSettings:
    return {"file_kind": "documents", "label": "documents"}


def run_meetings_audio() -> RunSettings:
    return {"file_kind": "audio", "label": "meetings/audio"}


def normalize_run_settings(run_settings: RunSettings | None = None) -> RunSettings:
    return run_settings or run_everything()


def v2() -> dict[str, Any]:
    return get().get("v2", {})


def v2_enabled(flag: str, default: bool = False) -> bool:
    return bool(v2().get(flag, default))


def v3() -> dict[str, Any]:
    return get().get("v3", {})


def v3_enabled(flag: str, default: bool = False) -> bool:
    return bool(v3().get(flag, default))


def document_images() -> dict[str, Any]:
    return get().get("document_images", {})


def document_image_descriptions_enabled(default: bool = False) -> bool:
    return bool(document_images().get("descriptions_enabled", default))


def document_image_ocr_enabled(default: bool = True) -> bool:
    """Whether Docling should run OCR on document pages. Defaults to True to
    preserve behavior; set false in config to skip OCR on digital documents,
    where it dominates conversion time and the vision captioner already covers
    text inside images."""
    return bool(document_images().get("ocr_enabled", default))


def processing() -> dict[str, Any]:
    return get().get("processing", {})


def sync_interval_seconds(default: int = 300) -> int:
    return int(v2().get("sync_interval_seconds", default))


def get_source_directories() -> list[str]:
    cfg = get()
    paths = cfg.get("paths", {})

    dirs = paths.get("source_directories")
    if dirs:
        return dirs if isinstance(dirs, list) else [dirs]

    single = paths.get("source_directory")
    if single:
        return [single]

    raise ValueError(
        "No source_directory or source_directories configured in paths."
    )


def allows_documents(run_settings: RunSettings | None = None) -> bool:
    return normalize_run_settings(run_settings)["file_kind"] in {"all", "documents"}


def allows_audio(run_settings: RunSettings | None = None) -> bool:
    return normalize_run_settings(run_settings)["file_kind"] in {"all", "audio"}
