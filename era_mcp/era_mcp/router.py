"""Mechanical routing (brief §17/§18): everything that can be decided without
an LLM is decided here — structural census questions, "what changed this week"
digest questions, project resolution, intent hints that seed investigation
tools, and the fast-vs-investigate gate from retrieval confidence."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from era_mcp import config

_STRUCTURAL_RE = re.compile(
    r"\b(how many|list (all|the)|all (the )?(projects?|folders?)|"
    r"what(?:'s| is) (in|under)|folder structure|which folders?|enumerate)\b",
    re.IGNORECASE,
)
_DIGEST_RE = re.compile(
    r"\b(what (has )?changed (this|last) week|weekly (update|report|digest)|what'?s new( this week)?|"
    r"anything new|what happened (this|last) week|latest digest)\b",
    re.IGNORECASE,
)

# intent -> (seed tools, reasons). Order matters: first match wins for the
# primary hint but all hints are recorded.
_INTENTS: list[tuple[str, re.Pattern[str], list[str]]] = [
    ("compare_projects", re.compile(r"\bcompare\b.{0,40}\bprojects?\b|\bprojects?\b.{0,30}\b(versus|vs\.?|compared)\b", re.I),
     ["compare_projects"]),
    ("star", re.compile(r"\b(star (example|stor|format)\w*|interview (example|prep|question)\w*|situation.{0,10}task.{0,10}action)\b", re.I),
     ["build_star_examples", "get_achievement"]),
    ("compare", re.compile(r"\b(compare|diff(erence)?s?|changed between|v\d+ vs|versus|vs\.?|what changed in)\b", re.I),
     ["find_latest_version", "compare_documents"]),
    ("conflict", re.compile(r"\b(conflict|contradict|inconsisten|stale|still valid|out of date|superseded)\b", re.I),
     ["find_conflicts"]),
    ("timeline", re.compile(r"\b(timeline|history|chronolog|how did .* evolve|over time|sequence of events)\b", re.I),
     ["get_project_history", "build_timeline"]),
    ("career_timeline", re.compile(r"\b(my career|career (timeline|history|path)|role history|roles over time)\b", re.I),
     ["get_role_history", "career_timeline"]),
    ("career", re.compile(r"\b(evidence (do|does|did|that|of|for)\b.{0,20}\b(i|my|me)\b|evidence (that|of) (i|my)|"
                          r"star (example|stor)\w*|interview\w*|achievement\w*|kpis?|demonstrat\w*|strongest example\w*|"
                          r"my (role|contribution|experience|track record)|what did i|have i (led|built|delivered)|"
                          r"capabilit\w*|competenc\w*|skills?)\b", re.I),
     ["find_career_evidence", "get_achievement"]),
    ("decision", re.compile(r"\b(decision|decided|why did we|rationale|trade-?off|chose|chosen)\b", re.I),
     ["trace_decision"]),
    ("latest", re.compile(r"\b(latest version|most recent version|current version|newest)\b", re.I),
     ["find_latest_version"]),
    ("status", re.compile(r"\b(status|where are we|what'?s (the )?(latest|state)|brief me|update on|progress on)\b", re.I),
     ["get_project_history"]),
]
_MULTI_RE = re.compile(r"\b(and also|as well as|versus|compared to|both .* and)\b|\?.+\?", re.I)
_CAP_NGRAM_RE = re.compile(r"\b([A-Z][A-Za-z0-9&'-]+(?:\s+[A-Z][A-Za-z0-9&'-]+){0,3})\b")
_ACRONYM_RE = re.compile(r"\b([A-Z]{2,6}\d{0,3})\b")
_STOP = {"what", "which", "when", "where", "who", "why", "how", "the", "and", "for", "did", "does", "are", "was",
         "were", "with", "from", "that", "this", "our", "my", "me", "i", "we", "of", "to", "in", "on", "a", "an", "is",
         "it", "be", "do", "have", "has", "had", "vs", "versus"}


@dataclass
class RouteDecision:
    route: str                                  # structural | digest | retrieval
    reasons: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    seed_tools: list[str] = field(default_factory=list)
    project: dict[str, Any] | None = None
    project_candidates: list[str] = field(default_factory=list)
    force: str | None = None                    # fast | investigate (from mode or strong hints)
    skip_rewrite: bool = False


def content_terms(question: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]+", question or "") if t.lower() not in _STOP]


def project_candidates(question: str) -> list[str]:
    """Strings worth trying against projects.resolve_project: acronyms, capitalised
    n-grams (longest first), quoted phrases."""
    q = question or ""
    cands: list[str] = []
    cands += re.findall(r'"([^"]{2,60})"', q)
    cands += [m for m in _ACRONYM_RE.findall(q)]
    grams = [g.strip() for g in _CAP_NGRAM_RE.findall(q)]
    grams = [g for g in grams if g.lower() not in _STOP and len(g) > 1]
    grams.sort(key=len, reverse=True)
    cands += grams
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        k = c.lower()
        if k not in seen and len(k) >= 2:
            seen.add(k)
            out.append(c)
    return out[:8]


def decide(question: str, mode: str = "auto", understanding: dict[str, Any] | None = None,
           project_hint: str | None = None, resolve=None) -> RouteDecision:
    """``resolve`` is projects.resolve_project (injected for tests). Pure apart
    from that call."""
    understanding = understanding or {}
    d = RouteDecision(route="retrieval")
    if mode == "fast":
        d.force = "fast"; d.reasons.append("mode=fast")
    elif mode == "investigate":
        d.force = "investigate"; d.reasons.append("mode=investigate")

    if _STRUCTURAL_RE.search(question or ""):
        d.route = "structural"; d.reasons.append("structural regex")
        return d
    if _DIGEST_RE.search(question or ""):
        d.route = "digest"; d.reasons.append("digest regex")
        return d

    # Project resolution: explicit hint first, then candidates from the text.
    d.project_candidates = ([project_hint] if project_hint else []) + project_candidates(question)
    if resolve is not None:
        for cand in d.project_candidates:
            try:
                p = resolve(cand)
            except Exception:  # noqa: BLE001
                p = None
            if p:
                d.project = p
                d.reasons.append(f"project resolved from {cand!r}")
                break

    for name, rx, tools in _INTENTS:
        if rx.search(question or ""):
            if name == "compare" and "compare_projects" in d.intents:
                continue  # two projects, not two document versions
            d.intents.append(name)
            for t in tools:
                if t not in d.seed_tools:
                    d.seed_tools.append(t)
    if d.intents:
        d.reasons.append("intent hints: " + ", ".join(d.intents))
    if _MULTI_RE.search(question or "") or understanding.get("complexity") == "complex":
        d.intents.append("multi_part")
        d.reasons.append("multi-part / complex question")

    # Short lookups with a resolved project do not need the LLM rewrite.
    if d.project is not None and len(content_terms(question)) <= config.rewrite_min_terms():
        d.skip_rewrite = True
        d.reasons.append("short lookup, rewrite skipped")
    return d


def gate(decision: RouteDecision, rerank_conf: float, card_conf: float | None, agreement: bool) -> tuple[str, str]:
    """fast | investigate, with the reason. Mechanical: no LLM involved."""
    if decision.force:
        return decision.force, f"forced by {decision.force}"
    strong = config.strong_rerank_threshold()
    weak = config.weak_rerank_threshold()
    card_strong = config.card_strong_threshold()
    hints = [i for i in decision.intents if i not in ("status",)]  # status alone is fine for fast
    if not hints and rerank_conf >= strong:
        return "fast", f"rerank confidence {rerank_conf:.2f} >= {strong}"
    if not hints and card_conf is not None and card_conf >= card_strong and agreement:
        return "fast", f"card confidence {card_conf:.2f} >= {card_strong} and agrees with passages"
    if hints:
        return "investigate", "investigation hints: " + ", ".join(hints)
    if rerank_conf < weak:
        return "investigate", f"rerank confidence {rerank_conf:.2f} < {weak}"
    return "investigate", f"ambiguous confidence {rerank_conf:.2f}; judge may answer at once"
