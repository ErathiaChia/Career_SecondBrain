"""The unit of evidence (brief §10): every tool result is a list of Sources,
each carrying the metadata a citation needs — file, path, section/page, date,
relevance — so answers stay traceable regardless of which tool found them."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from era_mcp import config
from era_mcp.budget import estimate_tokens

SourceKind = Literal["passage", "card", "section", "fact", "project", "document", "diff", "achievement", "role"]


@dataclass
class Source:
    kind: str
    text: str
    file_id: int | None = None
    file_name: str | None = None
    file_path: str | None = None
    folder: str | None = None
    section: str | None = None
    page: int | None = None
    date: str | None = None
    relevance: float | None = None
    fact_id: int | None = None
    version_label: str | None = None
    is_latest: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    token_estimate: int = 0

    def __post_init__(self) -> None:
        self.text = (self.text or "").strip()
        self.token_estimate = estimate_tokens(self.text)
        if self.relevance is not None:
            self.relevance = round(max(0.0, min(1.0, float(self.relevance))), 3)

    def key(self) -> tuple:
        return (self.kind, self.file_id, self.fact_id, self.section, self.text[:80])

    def citation(self, n: int) -> dict[str, Any]:
        return {
            "n": n, "kind": self.kind, "file_id": self.file_id, "file_name": self.file_name,
            "file_path": self.file_path, "folder": self.folder, "section": self.section, "page": self.page,
            "date": self.date, "version_label": self.version_label, "is_latest": self.is_latest,
            "relevance": self.relevance, "fact_id": self.fact_id,
        }


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value or "")[:10]
    return s if len(s) == 10 and s[4] == "-" else (str(value) if value else None)


def relevance_from_hit(hit: dict[str, Any]) -> float | None:
    """Normalise retrieval scores to 0-1: rerank score (infinity 0-1, llm_score
    0-10) when present, else cosine similarity, else None."""
    rs = hit.get("rerank_score")
    if rs is not None:
        try:
            v = float(rs)
        except (TypeError, ValueError):
            return None
        return v / 10.0 if config.rerank_kind() == "llm_score" else v
    sim = hit.get("similarity")
    return float(sim) if sim is not None else None


def from_chunk(hit: dict[str, Any]) -> Source:
    section = hit.get("heading_path") or (hit.get("metadata") or {}).get("section_path")
    return Source(
        kind="passage", text=hit.get("content") or "",
        file_id=hit.get("file_id"), file_name=hit.get("file_name"), file_path=hit.get("file_path"),
        folder=hit.get("folder"), section=section, page=hit.get("page_number"),
        date=_iso(hit.get("last_modified_at")), relevance=relevance_from_hit(hit),
        version_label=hit.get("version_label"), is_latest=hit.get("is_latest"),
        extra={"matched_chunk_index": hit.get("matched_chunk_index"), "parent_chunk_id": hit.get("parent_chunk_id"),
               "doc_rank": hit.get("doc_rank"), "rrf_score": hit.get("rrf_score"), "speaker": hit.get("speaker")},
    )


def from_card(card: dict[str, Any], relevance: float | None = None) -> Source:
    bits = [f"{card.get('title') or card.get('file_name')} ({card.get('doc_type') or 'document'})"]
    if card.get("summary"):
        bits.append(str(card["summary"]))
    if card.get("topics"):
        bits.append("Topics: " + ", ".join(map(str, card["topics"])))
    if card.get("decisions"):
        bits.append("Decisions: " + " | ".join(str(d.get("statement")) for d in card["decisions"][:4] if isinstance(d, dict)))
    if card.get("outcomes"):
        bits.append("Outcomes: " + " | ".join(str(o.get("statement")) for o in card["outcomes"][:4] if isinstance(o, dict)))
    return Source(
        kind="card", text="\n".join(bits), file_id=card.get("file_id"), file_name=card.get("file_name"),
        file_path=card.get("file_path"), folder=card.get("folder"), date=_iso(card.get("doc_date")),
        relevance=relevance if relevance is not None else card.get("card_score"),
        version_label=card.get("version_label"), is_latest=card.get("is_latest"),
        extra={"doc_type": card.get("doc_type"), "projects": card.get("projects"), "topics": card.get("topics")},
    )


def from_fact(f: dict[str, Any], relevance: float = 1.0) -> Source:
    attrs = f.get("attributes") or {}
    bits = [f"[{f.get('kind')}] {f.get('statement')}"]
    extras = [x for x in (f.get("status") and f"status {f['status']}", attrs.get("due_at") and f"due {attrs['due_at']}",
                          f.get("owner") and f"owner {f['owner']}", f.get("project") and f"project {f['project']}") if x]
    if extras:
        bits.append("(" + "; ".join(extras) + ")")
    if f.get("source_quote"):
        bits.append(f'"{str(f["source_quote"])[:200]}"')
    return Source(
        kind="fact", text=" ".join(bits), file_id=f.get("file_id"), file_name=f.get("file_name"),
        file_path=f.get("file_path"), folder=f.get("folder"), date=_iso(f.get("occurred_at") or f.get("last_verified_at")),
        relevance=relevance, fact_id=f.get("id"), is_latest=f.get("from_latest_version"),
        extra={"kind": f.get("kind"), "status": f.get("status"), "stale": f.get("stale_reasons") or f.get("stale"),
               "conflict_ids": f.get("conflict_ids")},
    )


def from_project(p: dict[str, Any], text: str, relevance: float = 1.0) -> Source:
    return Source(kind="project", text=text, relevance=relevance,
                  extra={"project_id": p.get("id"), "project_key": p.get("project_key"), "name": p.get("name")})


def from_document(file_id: int | None, file_name: str | None, text: str, kind: str = "document",
                  relevance: float = 1.0, **meta: Any) -> Source:
    return Source(kind=kind, text=text, file_id=file_id, file_name=file_name, relevance=relevance,
                  file_path=meta.pop("file_path", None), folder=meta.pop("folder", None),
                  section=meta.pop("section", None), page=meta.pop("page", None), date=meta.pop("date", None),
                  version_label=meta.pop("version_label", None), is_latest=meta.pop("is_latest", None), extra=meta)
