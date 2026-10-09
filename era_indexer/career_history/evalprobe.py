"""Freshness probe (brief §23 "Freshness"): before a pipeline run, write a small
file into the vault carrying the run id; after the run, the scorecard checks
that the probe shows up in vault_events and in /search. Off unless
``eval.freshness_probe_enabled`` is set in config.yaml.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from career_history import config

PROBE_RELATIVE = os.path.join("Z. AI_Notebook", "_eval", "freshness_probe.md")


def enabled() -> bool:
    try:
        return bool((config.get().get("eval") or {}).get("freshness_probe_enabled"))
    except Exception:  # noqa: BLE001
        return False


def probe_path() -> Path | None:
    roots = [r for r in config.get_source_directories() if os.path.isdir(r)]
    return Path(roots[0]) / PROBE_RELATIVE if roots else None


def render(run_id: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    return (f"# Freshness probe\n\n"
            f"Pipeline run token: `{run_id}`\n\n"
            f"Written {now:%Y-%m-%d %H:%M} by the weekly pipeline. If a search for the token "
            f"above finds this file, new documents are reaching the index.\n")


def arm(run_id: str) -> str | None:
    """Write the probe for ``run_id``; returns the path or None when disabled."""
    if not enabled():
        return None
    path = probe_path()
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(run_id), encoding="utf-8")
    return str(path)
