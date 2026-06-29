"""Filesystem scanning + queue population.

Walks the source directory, computes hashes, and registers/enqueues files
whose hash differs from what's in the database. Files that have been deleted
on disk are removed from the registry (cascading their chunks/segments).
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

from rich.console import Console

from career_history import config, db


console = Console()


def _hash_file(path: str, buf: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(buf):
            h.update(chunk)
    return h.hexdigest()


def _folder_of(file_path: str, root: str) -> str:
    """Return the top-level subdirectory under root. '.' if file is at root."""
    rel = os.path.relpath(file_path, root)
    parts = Path(rel).parts
    return parts[0] if len(parts) > 1 else "."


def discover(
    folder: str | None = None,
    run_settings: config.RunSettings | None = None,
) -> dict:
    """Scan filesystem; register new/changed files into the queue.

    Args:
        folder: subdirectory of source_directory to scan. None = full scan.
        run_settings: optional config profile selecting all, documents, or audio.

    Returns counters: {discovered, new_or_changed, unchanged, removed}.
    """
    cfg = config.get()
    settings = config.normalize_run_settings(run_settings)
    roots = config.get_source_directories()
    audio_exts = {e.lower() for e in cfg["extensions"]["audio"]}
    doc_exts = {e.lower() for e in cfg["extensions"]["documents"]}

    discovered = changed = unchanged = 0
    seen: set[str] = set()
    scanned_roots: list[tuple[str, str]] = []

    for root in roots:
        scan_root = os.path.join(root, folder) if folder else root
        if not os.path.isdir(scan_root):
            console.log(f"[yellow]Skipping (not found):[/yellow] {scan_root}")
            continue
        scanned_roots.append((root, scan_root))
        console.log(f"[bold]Scanning[/bold] {scan_root} ({settings['label']})")

        for dirpath, _, files in os.walk(scan_root):
            for name in files:
                if name.startswith("."):
                    continue
                ext = os.path.splitext(name)[1].lower()
                is_audio = ext in audio_exts and config.allows_audio(settings)
                is_doc = ext in doc_exts and config.allows_documents(settings)
                if not (is_audio or is_doc):
                    continue

                fpath = os.path.join(dirpath, name)
                seen.add(fpath)
                discovered += 1

                try:
                    fhash = _hash_file(fpath)
                    mod = datetime.fromtimestamp(os.path.getmtime(fpath))
                    file_id, was_changed = db.upsert_file(
                        file_path=fpath,
                        file_name=name,
                        file_type=ext.lstrip("."),
                        file_hash=fhash,
                        folder=_folder_of(fpath, root),
                        is_audio=is_audio,
                        mod_time=mod,
                    )
                    if was_changed:
                        db.enqueue(file_id)
                        changed += 1
                    else:
                        unchanged += 1
                except Exception as e:
                    console.log(f"[red]Hash failed[/red] {fpath}: {e}")

    if not scanned_roots:
        raise FileNotFoundError("No valid scan roots found in source_directories.")

    # Cleanup deleted files within the scanned scope.
    removed = 0
    abs_scan_roots = [os.path.abspath(sr) for _, sr in scanned_roots]
    for known in db.all_registered_paths():
        if folder and not any(
            os.path.abspath(known).startswith(asr) for asr in abs_scan_roots
        ):
            continue
        if known not in seen and not os.path.exists(known):
            db.delete_file(known)
            removed += 1
            console.log(f"[dim]removed[/dim] {os.path.basename(known)}")

    # Deterministic project-entity seeding (no LLM) so project entities track the
    # folder taxonomy as it changes. No-ops unless seed.project_roots is set.
    try:
        from career_history import seed_entities
        seed_entities.seed(folder=folder)
    except Exception as e:  # never let seeding break discovery
        console.log(f"[red]seed-entities failed[/red]: {e}")

    summary = {
        "discovered": discovered,
        "new_or_changed": changed,
        "unchanged": unchanged,
        "removed": removed,
    }
    console.log(f"[green]Discovery done.[/green] {summary}")
    return summary
