"""Test configuration: never depends on the private registries or a real DB.
Uses config.yaml if present (else config.yaml.example) and points the registry
dir at the scrubbed fixtures under tests/fixtures/registries."""
from __future__ import annotations

import os
from pathlib import Path

from auditor.config import AppConfig, load_config

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent


def auditor_config() -> AppConfig:
    os.environ["AUDITOR_REGISTRY_DIR"] = str(_HERE / "fixtures" / "registries")
    os.environ.setdefault("AUDITOR_DATABASE_URL", "postgresql://test:test@localhost:1/none")
    path = _PKG / "config.yaml"
    if not path.exists():
        path = _PKG / "config.yaml.example"
    return load_config(path)
