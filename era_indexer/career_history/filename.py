"""Parse dense, convention-bearing file names into structured fields.

Career file names encode a lot of retrievable signal, e.g.::

    260003-250024 VTJ_Accrete_AIS_Voice Authentication_Proposal_v1.0.docx

which carries document IDs, an originator code, a client, a product, a topic,
a document type, and a version. This module extracts those fields so they can
be folded into the embedded text and the keyword index.

Parsing is best-effort: names that do not follow the convention still yield a
usable ``clean_name`` and ``tokens`` list so retrieval degrades gracefully.
"""
from __future__ import annotations

import os
import re
from typing import Any


# Leading numeric / dash group, e.g. "260003-250024" or "260003".
_ID_GROUP_RE = re.compile(r"^(\d[\d]*(?:-\d[\d]*)*)\b\s*")
# Version token, e.g. "v1", "v1.0", "v2.3.1" (case-insensitive).
_VERSION_RE = re.compile(r"^v\d+(?:\.\d+)*$", re.IGNORECASE)
# Separators between fields: underscores, plus runs of whitespace / dashes.
_SPLIT_RE = re.compile(r"[_]+")
_CLEAN_RE = re.compile(r"[_\-]+")

# Small, extensible vocabulary of document types. Matched case-insensitively
# against whole tokens.
_DOC_TYPES = {
    "proposal": "Proposal",
    "report": "Report",
    "minutes": "Minutes",
    "mom": "Minutes",
    "contract": "Contract",
    "agreement": "Agreement",
    "sow": "SOW",
    "spec": "Specification",
    "specification": "Specification",
    "presentation": "Presentation",
    "deck": "Presentation",
    "slides": "Presentation",
    "quote": "Quotation",
    "quotation": "Quotation",
    "invoice": "Invoice",
    "po": "Purchase Order",
    "rfp": "RFP",
    "rfq": "RFQ",
    "nda": "NDA",
    "memo": "Memo",
    "brief": "Brief",
    "summary": "Summary",
    "plan": "Plan",
    "roadmap": "Roadmap",
    "review": "Review",
    "notes": "Notes",
    "draft": "Draft",
}


def parse_filename(file_name: str) -> dict[str, Any]:
    """Return best-effort structured fields parsed from ``file_name``.

    Always populates ``clean_name`` and ``tokens``. Other keys
    (``doc_ids``, ``version``, ``doc_type``, ``originator``, ``client``,
    ``product``, ``topic``, ``terms``) appear only when detected.
    """
    stem = os.path.splitext(file_name or "")[0].strip()
    out: dict[str, Any] = {}

    # 1. Leading document IDs (kept out of the term tokens).
    remainder = stem
    id_match = _ID_GROUP_RE.match(stem)
    if id_match:
        out["doc_ids"] = id_match.group(1)
        remainder = stem[id_match.end():].strip()

    # 2. Field tokens split on underscores, with surrounding whitespace
    #    preserved inside a field (e.g. "Voice Authentication").
    raw_fields = [f.strip() for f in _SPLIT_RE.split(remainder) if f.strip()]

    version: str | None = None
    doc_type: str | None = None
    terms: list[str] = []
    for field in raw_fields:
        if version is None and _VERSION_RE.match(field):
            version = field.lower()
            continue
        mapped = _DOC_TYPES.get(field.lower())
        if mapped and doc_type is None:
            doc_type = mapped
            continue
        terms.append(field)

    if version:
        out["version"] = version
    if doc_type:
        out["doc_type"] = doc_type

    # 3. Positional heuristics for the leading term fields. The convention is
    #    originator code, then client, then product, then topic. Only assign
    #    when tokens are present; never invent values.
    if terms:
        first = terms[0]
        if first.isupper() and len(first) <= 5 and len(terms) > 1:
            out["originator"] = first
            terms = terms[1:]
    if terms:
        out["client"] = terms[0]
    if len(terms) > 1:
        out["product"] = terms[1]
    if len(terms) > 2:
        out["topic"] = " ".join(terms[2:])
    if terms:
        out["terms"] = terms

    # 4. Always-available fallbacks.
    out["clean_name"] = _CLEAN_RE.sub(" ", stem).strip()
    out["tokens"] = [t for t in re.split(r"[\s_\-]+", stem) if t]
    return out
