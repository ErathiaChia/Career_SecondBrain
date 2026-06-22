"""Small .env loader for local secrets."""
from __future__ import annotations

import os
from pathlib import Path


def load(path: str | Path = ".env", *, override: bool = False) -> None:
    """Load KEY=VALUE lines from .env if present."""
    env_path = _find_env(Path(path))
    if env_path is None:
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and (override or key not in os.environ):
            os.environ[key] = value


def _find_env(path: Path) -> Path | None:
    if path.is_absolute():
        return path if path.exists() else None

    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / path
        if candidate.exists():
            return candidate
    return None
