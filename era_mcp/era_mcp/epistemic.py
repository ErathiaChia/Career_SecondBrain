"""Parse FACT / INFERENCE / UNKNOWN labels out of a synthesized answer so the
response can report how much of it is evidence, reasoning, or a known gap."""
from __future__ import annotations

import re
from typing import Any

_LABEL = re.compile(r"(?:^|\n|[-*•]\s*|\.\s+)\**\s*(FACT|INFERENCE|UNKNOWN)\s*\**\s*:\s*\**\s*(.+?)(?=\n|$)")
_CITE = re.compile(r"\[(\d+)\]")


def parse(answer: str | None) -> dict[str, Any]:
    """Return counts per label, the UNKNOWN items, and whether every FACT is cited."""
    counts = {"FACT": 0, "INFERENCE": 0, "UNKNOWN": 0}
    unknowns: list[str] = []
    uncited_facts: list[str] = []
    for label, text in _LABEL.findall(answer or ""):
        counts[label] += 1
        text = text.strip().strip("*").strip()
        if label == "UNKNOWN":
            unknowns.append(text)
        elif label == "FACT" and not _CITE.search(text):
            uncited_facts.append(text)
    return {
        "labelled": any(counts.values()),
        "counts": {k.lower(): v for k, v in counts.items()},
        "unknowns": unknowns,
        "uncited_facts": uncited_facts,
    }
