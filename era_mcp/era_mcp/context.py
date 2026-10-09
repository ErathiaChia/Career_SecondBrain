"""Context construction (brief §10): card -> section -> passage -> fact ->
metadata, inside a document cap and a token cap. The builder is the single
place evidence enters the answer, so the budget is enforced here, not in the
tools."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from era_mcp import config
from era_mcp.agent_tools.sources import Source
from era_mcp.budget import estimate_tokens

# Tier order and per-item caps (tokens). Tier caps are a share of the total.
TIERS = ("project", "card", "section", "passage", "fact", "document", "diff", "achievement", "role")
_PER_ITEM = {"project": 200, "card": 120, "section": 80, "passage": 330, "fact": 60, "document": 600,
             "diff": 500, "achievement": 80, "role": 60}
_PER_DOC_PASSAGES = 3


def _tier_caps(total: int) -> dict[str, int]:
    return {
        "project": min(400, int(total * 0.03)),
        "card": min(1500, int(total * 0.1)),
        "section": min(1200, int(total * 0.08)),
        "fact": min(800, int(total * 0.06)),
        "achievement": min(600, int(total * 0.04)),
        "role": min(200, int(total * 0.02)),
        "diff": min(1500, int(total * 0.1)),
        "document": min(2400, int(total * 0.15)),
        # passages take the remainder
    }


def _trim(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    return text[: int(max_tokens * 3.6)].rstrip() + " …"


@dataclass
class ContextBuilder:
    max_documents: int = 10
    max_tokens: int = 20000
    sources: list[Source] = field(default_factory=list)
    _keys: set[tuple] = field(default_factory=set)
    rejected_documents: int = 0
    rejected_tokens: int = 0

    @classmethod
    def from_config(cls, max_tokens: int) -> "ContextBuilder":
        return cls(max_documents=max(1, config.agent_max_documents()), max_tokens=max_tokens)

    # --- accounting -------------------------------------------------------------
    def documents(self) -> set[int]:
        return {s.file_id for s in self.sources if s.file_id is not None}

    def tokens(self) -> int:
        return sum(s.token_estimate for s in self.sources)

    def _tier_tokens(self, kind: str) -> int:
        return sum(s.token_estimate for s in self.sources if s.kind == kind)

    # --- adding -------------------------------------------------------------------
    def add(self, sources: list[Source]) -> int:
        """Add sources, enforcing the document cap, per-tier caps and the total
        token cap. Returns how many NEW sources were admitted (0 => the tool
        found nothing new, which the loop treats as a stop signal)."""
        caps = _tier_caps(self.max_tokens)
        added = 0
        for s in sorted(sources, key=lambda x: -(x.relevance or 0.0)):
            if s.key() in self._keys or not s.text:
                continue
            if s.file_id is not None and s.file_id not in self.documents() and len(self.documents()) >= self.max_documents:
                self.rejected_documents += 1
                continue
            if s.kind == "passage" and sum(1 for x in self.sources if x.kind == "passage" and x.file_id == s.file_id) >= _PER_DOC_PASSAGES:
                continue
            s.text = _trim(s.text, _PER_ITEM.get(s.kind, 300))
            s.token_estimate = estimate_tokens(s.text)
            tier_cap = caps.get(s.kind)
            if tier_cap is not None and self._tier_tokens(s.kind) + s.token_estimate > tier_cap:
                self.rejected_tokens += 1
                continue
            if self.tokens() + s.token_estimate > self.max_tokens:
                if not self._make_room(s.token_estimate):
                    self.rejected_tokens += 1
                    continue
            self.sources.append(s)
            self._keys.add(s.key())
            added += 1
        return added

    def _make_room(self, needed: int) -> bool:
        """Drop the lowest-relevance passages first; then reduce passages per
        document to 2. Never drops cards/facts/project record."""
        passages = sorted([s for s in self.sources if s.kind == "passage"], key=lambda x: (x.relevance or 0.0))
        freed = 0
        for p in passages:
            if self.tokens() - freed + needed <= self.max_tokens:
                break
            self.sources.remove(p)
            self._keys.discard(p.key())
            freed += p.token_estimate
        return self.tokens() + needed <= self.max_tokens

    # --- output ---------------------------------------------------------------------
    def ordered(self) -> list[Source]:
        """Tier order; within passages: by document (best doc first) then reading order."""
        out: list[Source] = []
        for kind in TIERS:
            items = [s for s in self.sources if s.kind == kind]
            if kind == "passage":
                doc_best: dict[int | None, float] = {}
                for s in items:
                    doc_best[s.file_id] = max(doc_best.get(s.file_id, 0.0), s.relevance or 0.0)
                items.sort(key=lambda s: (-doc_best.get(s.file_id, 0.0), s.file_id or 0,
                                          (s.extra or {}).get("matched_chunk_index") or 0))
            else:
                items.sort(key=lambda s: -(s.relevance or 0.0))
            out.extend(items)
        return out

    def render(self) -> tuple[str, list[dict[str, Any]]]:
        """The SOURCES block for synthesis and the matching citations list.
        Passages/cards/sections get [n]; facts get [F<id>] so the answer can cite
        either, and both resolve to a file."""
        lines: list[str] = []
        citations: list[dict[str, Any]] = []
        n = 0
        for s in self.ordered():
            if s.kind == "fact" and s.fact_id is not None:
                label = f"[F{s.fact_id}]"
                n += 1
                cit = s.citation(n)
                cit["label"] = label
            else:
                n += 1
                label = f"[{n}]"
                cit = s.citation(n)
                cit["label"] = label
            header = [s.kind.upper()]
            if s.file_name:
                header.append(s.file_name)
            if s.section:
                header.append(f"§ {s.section}")
            if s.page:
                header.append(f"p.{s.page}")
            if s.date:
                header.append(s.date)
            if s.version_label:
                header.append(f"{s.version_label}{'' if s.is_latest in (None, True) else ' (older version)'}")
            if s.relevance is not None:
                header.append(f"rel {s.relevance:.2f}")
            lines.append(f"{label} {' | '.join(header)}\n{s.text}")
            citations.append(cit)
        return "\n\n".join(lines), citations

    def digest(self, max_lines: int = 20) -> str:
        """Compact view for the Judge: one line per source, best first."""
        rows = []
        for s in self.ordered()[:max_lines]:
            label = f"F{s.fact_id}" if s.kind == "fact" and s.fact_id else s.kind
            snippet = s.text.replace("\n", " ")[:160]
            rows.append(f"- [{label}] {s.file_name or '-'} | {s.section or ''} | {s.date or ''} | "
                        f"rel {s.relevance if s.relevance is not None else '-'} | {snippet}")
        more = len(self.sources) - min(len(self.sources), max_lines)
        if more > 0:
            rows.append(f"- … {more} more source(s)")
        return "\n".join(rows) if rows else "(no evidence yet)"

    def stats(self) -> dict[str, Any]:
        return {"documents_used": len(self.documents()), "max_documents": self.max_documents,
                "context_tokens": self.tokens(), "max_context_tokens": self.max_tokens,
                "sources": len(self.sources), "rejected_documents": self.rejected_documents,
                "rejected_tokens": self.rejected_tokens}
