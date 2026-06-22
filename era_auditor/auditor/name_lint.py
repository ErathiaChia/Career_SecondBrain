"""Deterministic name-lint findings: known typos only. No LLM involved.

Numbering policy (repository constitution): numeric prefixes are ordering,
grouping, and navigation aids, NOT unique identifiers. Sibling folders may
intentionally share the same prefix ("01 Daily_Todo" next to
"01 Internal_Meeting_Notes"), so prefix collisions never generate findings.
Stage indices ("A.2.5.") remain identifiers and are validated by the
template differ instead.
"""

from __future__ import annotations

import re
from typing import Any

from .models import AuditFinding, FolderRecord


class NameLinter:
    def __init__(self, naming_standards: dict[str, Any]):
        self.known_typos: dict[str, str] = {
            str(key).lower(): str(value)
            for key, value in (naming_standards.get("known_typos") or {}).items()
        }

    def lint(self, folders: list[FolderRecord]) -> list[AuditFinding]:
        return self._typos(folders)

    def _typos(self, folders: list[FolderRecord]) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        if not self.known_typos:
            return findings
        for folder in folders:
            lowered = folder.name.lower()
            for typo, correction in self.known_typos.items():
                if typo in lowered:
                    pattern = re.compile(re.escape(typo), re.IGNORECASE)
                    corrected = pattern.sub(correction, folder.name)
                    findings.append(
                        AuditFinding(
                            folder_path=folder.path,
                            issue_type="naming_inconsistency",
                            severity="low",
                            confidence=0.85,
                            suggested_action="rename",
                            suggested_destination=corrected,
                            reasoning=(
                                f"Folder name contains the misspelling '{typo}'; "
                                f"suggested spelling: '{corrected}'."
                            ),
                        )
                    )
                    break
        return findings
