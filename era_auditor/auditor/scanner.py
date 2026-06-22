from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

from .config import AppConfig, resolve_report_directory
from .models import FileSnapshot, FolderSnapshot, ScanResult


def should_ignore(path: Path, ignore_names: set[str], ignore_suffixes: tuple[str, ...]) -> bool:
    if path.name in ignore_names:
        return True
    return any(path.name.endswith(suffix) for suffix in ignore_suffixes)


def to_utc_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def relative_path(root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    return "." if str(rel) == "." else rel.as_posix()


def build_signature(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_category(extension: str) -> str:
    ext = extension.lower()
    if ext in {".pdf", ".doc", ".docx", ".md", ".txt", ".rtf"}:
        return "document"
    if ext in {".ppt", ".pptx", ".key"}:
        return "presentation"
    if ext in {".xls", ".xlsx", ".csv"}:
        return "spreadsheet"
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        return "image"
    if ext in {".mp3", ".wav", ".m4a", ".mp4", ".mov", ".avi", ".mkv"}:
        return "media"
    if ext in {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".sql", ".sh"}:
        return "code"
    if ext in {".zip", ".tar", ".gz", ".7z", ".rar"}:
        return "archive"
    return "other"


def matches_subtree(rel_path: str, patterns: list[str]) -> bool:
    """True when rel_path matches an ignore_subtrees glob or sits beneath one."""
    for pattern in patterns:
        base = pattern.rstrip("/*")
        if rel_path == base or rel_path.startswith(f"{base}/"):
            return True
        if fnmatch(rel_path, pattern):
            return True
    return False


class FolderScanner:
    def __init__(self, config: AppConfig):
        self.config = config
        self.ignore_names = set(config.scanner.ignore_names)
        self.ignore_suffixes = tuple(config.scanner.ignore_suffixes)
        self.ignore_subtrees = list(config.scanner.ignore_subtrees)
        self.code_repo_markers = set(config.scanner.code_repo_markers)

    def is_code_repo(self, path: Path, file_names: list[str], dir_names: list[str]) -> bool:
        names = set(file_names) | set(dir_names)
        if names & self.code_repo_markers:
            return True
        if (path / ".git").exists():
            return True
        code_files = sum(1 for name in file_names if file_category(Path(name).suffix) == "code")
        if code_files >= 3 and code_files >= max(1, len(file_names)) * 0.5:
            structural = {"scripts", "models", "src", "lib", "docs", "data", "tests"}
            if structural & {name.lower() for name in dir_names}:
                return True
        return False

    def scan(self, limit: int | None = None) -> ScanResult:
        folders: list[FolderSnapshot] = []
        files: list[FileSnapshot] = []

        for root_value in self.config.paths.source_directories:
            root = Path(root_value).expanduser().resolve()
            if not root.exists():
                continue
            root_folders, root_files = self._scan_root(root, limit)
            folders.extend(root_folders)
            files.extend(root_files)
            if limit is not None and len(folders) >= limit:
                folders = folders[:limit]
                break

        allowed_folder_paths = {(folder.root_path, folder.path) for folder in folders}
        files = [file for file in files if (file.root_path, file.folder_path) in allowed_folder_paths]
        self._hash_duplicate_candidates(files)
        return ScanResult(scanned_at=datetime.now(timezone.utc), folders=folders, files=files)

    def _hash_duplicate_candidates(self, files: list[FileSnapshot]) -> None:
        """Size fast-path: only SHA-256 files whose size matches another file.

        Unique sizes cannot be duplicates, so the expensive content read is
        skipped for them.
        """
        by_size: dict[int, list[FileSnapshot]] = {}
        for file in files:
            if file.size_bytes > 0:
                by_size.setdefault(file.size_bytes, []).append(file)

        for size_group in by_size.values():
            if len(size_group) < 2:
                continue
            for file in size_group:
                try:
                    digest = hashlib.sha256()
                    with open(file.absolute_path, "rb") as handle:
                        for chunk in iter(lambda: handle.read(1 << 20), b""):
                            digest.update(chunk)
                    file.content_hash = digest.hexdigest()
                except OSError:
                    continue

    def _scan_root(
        self,
        root: Path,
        limit: int | None,
    ) -> tuple[list[FolderSnapshot], list[FileSnapshot]]:
        folder_records: list[FolderSnapshot] = []
        file_records: list[FileSnapshot] = []
        root_path = root.as_posix()

        for current, dir_names, file_names in self._walk(root):
            if limit is not None and len(folder_records) >= limit:
                break

            depth = 0 if current == root else len(current.relative_to(root).parts)
            if self.config.scanner.max_depth is not None and depth > self.config.scanner.max_depth:
                dir_names[:] = []
                continue

            folder_path = relative_path(root, current)
            if folder_path != "." and matches_subtree(folder_path, self.ignore_subtrees):
                dir_names[:] = []
                continue

            is_code_repo = folder_path != "." and self.is_code_repo(current, file_names, dir_names)
            if is_code_repo:
                # Treat the repository as one opaque leaf: do not descend or
                # inventory its internals.
                dir_names[:] = []

            child_dirs = [name for name in dir_names if not should_ignore(current / name, self.ignore_names, self.ignore_suffixes)]
            visible_files = [name for name in file_names if not should_ignore(current / name, self.ignore_names, self.ignore_suffixes)]
            parent_path = None if current == root else relative_path(root, current.parent)

            total_size = 0
            latest_modified: datetime | None = None
            sample_filenames: list[str] = []
            file_payloads: list[dict] = []
            extension_counts: Counter[str] = Counter()
            category_counts: Counter[str] = Counter()
            largest_file: dict | None = None

            for name in sorted(visible_files):
                file_path = current / name
                try:
                    stat = file_path.stat()
                except OSError:
                    continue

                modified_at = to_utc_datetime(stat.st_mtime)
                total_size += stat.st_size
                if latest_modified is None or modified_at > latest_modified:
                    latest_modified = modified_at
                if len(sample_filenames) < self.config.scanner.sample_file_limit:
                    sample_filenames.append(name)

                file_rel = relative_path(root, file_path)
                extension = file_path.suffix.lower()
                category = file_category(extension)
                extension_counts[extension or "[no_extension]"] += 1
                category_counts[category] += 1
                if largest_file is None or stat.st_size > largest_file["size_bytes"]:
                    largest_file = {"path": file_rel, "size_bytes": stat.st_size, "category": category}
                file_payloads.append(
                    {
                        "path": file_rel,
                        "size_bytes": stat.st_size,
                        "modified_at": modified_at.isoformat(),
                    }
                )
                if not is_code_repo:
                    file_records.append(
                        FileSnapshot(
                            root_path=root_path,
                            folder_path=folder_path,
                            path=file_rel,
                            absolute_path=file_path.as_posix(),
                            extension=extension,
                            size_bytes=stat.st_size,
                            modified_at=modified_at,
                        )
                    )

            signature = build_signature(
                {
                    "path": folder_path,
                    "children": sorted(child_dirs),
                    "files": file_payloads,
                    "file_count": len(visible_files),
                    "child_folder_count": len(child_dirs),
                    "total_size_bytes": total_size,
                    "file_extension_counts": dict(extension_counts),
                    "file_category_counts": dict(category_counts),
                }
            )
            metadata_signals = {
                "has_documents": category_counts["document"] > 0,
                "has_presentations": category_counts["presentation"] > 0,
                "has_media": category_counts["media"] > 0,
                "has_code": category_counts["code"] > 0,
                "is_code_repo": is_code_repo,
                "largest_file": largest_file,
            }
            folder_records.append(
                FolderSnapshot(
                    root_path=root_path,
                    path=folder_path,
                    absolute_path=current.as_posix(),
                    parent_path=parent_path,
                    depth=depth,
                    file_count=len(visible_files),
                    child_folder_count=len(child_dirs),
                    total_size_bytes=total_size,
                    latest_modified_at=latest_modified,
                    sample_filenames=sample_filenames,
                    file_extension_counts=dict(extension_counts),
                    file_category_counts=dict(category_counts),
                    metadata_signals=metadata_signals,
                    content_signature=signature,
                )
            )

        return folder_records, file_records

    def _walk(self, root: Path):
        for current_str, dir_names, file_names in os.walk(root, topdown=True):
            current = Path(current_str)
            dir_names[:] = [
                name
                for name in dir_names
                if not should_ignore(current / name, self.ignore_names, self.ignore_suffixes)
            ]
            yield current, dir_names, file_names


def write_scan_json(config: AppConfig, scan_result: ScanResult) -> Path:
    report_dir = resolve_report_directory(config)
    timestamp = scan_result.scanned_at.strftime("%Y%m%d_%H%M%S")
    path = report_dir / f"scan_{timestamp}.json"
    path.write_text(scan_result.model_dump_json(indent=2), encoding="utf-8")
    return path
