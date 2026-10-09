"""Contradiction detection and stale-knowledge flags.

Conflicts (``fact_conflicts``), per project, across different source files:
  - deterministic: the same planned milestone/commitment with different dates
    (``date_mismatch``), or the same statement with different statuses
    (``status_mismatch``). "Same" means near-identical wording once dates are
    removed, or a shared topic with substantial overlap. Historical events are
    not compared (many legitimately share wording), and a statement repeated
    with three or more dates is treated as a recurring series, not a conflict;
  - LLM-judged: candidate pairs of decisions/requirements/milestones/... that
    share a topic or most of their words. Pairs judged consistent are stored as
    ``no_conflict`` so they are not paid for again.
The newer, latest-version evidence is proposed as ``likely_latest``; a person
confirms or dismisses (that decision survives re-detection).

Stale flags (``stale_flags``) are rebuilt wholesale: superseded facts, the losing
side of a conflict, facts from non-latest document versions, and open items that
have not been re-asserted for ``max_age_days`` in projects that are still active
(project folder touched within ``active_days``).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache
from itertools import combinations
from typing import Any

from rich.console import Console

from career_history import intel_db, llm

console = Console()

JUDGED_KINDS = {"decision", "requirement", "milestone", "commitment", "dependency", "risk", "event"}
DATED_KINDS = {"milestone", "commitment"}
OPEN_KINDS = {"action_item", "open_question", "risk", "commitment", "dependency"}
CLOSED = {"done", "cancelled", "rejected", "mitigated"}
SAME_CLAIM_JACCARD = 0.85
SAME_TOPIC_JACCARD = 0.5
RECURRING_MIN_DATES = 3
RECURRING_GAP_TOLERANCE_DAYS = 4
ACTIVE_PROJECT_DAYS = 60
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MONTH = (r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
          r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?![a-z])")
_ANY_DATE = re.compile(
    r"\d{4}-\d{1,2}-\d{1,2}"                                       # 2025-11-20
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"                            # 20/11/2025, 5/4/23
    rf"|\d{{1,2}}(?:st|nd|rd|th)?[\s-]*{_MONTH}\.?(?:[\s,-]*\d{{2,4}})?"  # 20-Nov-2025, 1 Nov
    rf"|{_MONTH}\.?[\s-]*\d{{1,4}}(?:st|nd|rd|th)?(?:,?\s*\d{{4}})?"     # Nov 20, 2025, Mar17
    rf"|{_MONTH}"
    r"|\b(?:19|20)\d{2}\b"
    r"|\bq[1-4]\b"
)
_STOP = {"the", "a", "an", "to", "of", "and", "for", "on", "in", "by", "with", "is", "be", "will", "we", "at"}


@lru_cache(maxsize=50_000)
def _tokens(text: str) -> frozenset[str]:
    text = _ANY_DATE.sub(" ", (text or "").lower())
    return frozenset(t for t in re.split(r"[^a-z0-9]+", text)
                     if (len(t) > 2 or t.isdigit()) and t not in _STOP)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _date(f: dict[str, Any]) -> str | None:
    value = f.get("occurred_at") or (f.get("attributes") or {}).get("due_at")
    if not value:
        return None
    m = _DATE.search(str(value))
    return m.group(0) if m else None


def _evidence_key(f: dict[str, Any]) -> tuple:
    return (bool(f.get("from_latest_version", True)),
            str(f.get("last_verified_at") or f.get("last_modified_at") or ""), f["id"])


def _newer(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return a if _evidence_key(a) >= _evidence_key(b) else b


def _pair(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return (a, b) if a["id"] < b["id"] else (b, a)


def _related(a: dict[str, Any], b: dict[str, Any], min_jaccard: float) -> float:
    if a.get("topic") and a.get("topic") == b.get("topic"):
        return 1.0
    score = jaccard(_tokens(a["statement"]), _tokens(b["statement"]))
    return score if score >= min_jaccard else 0.0


def _eligible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (a["file_id"] != b["file_id"]
            and a.get("supersedes_fact_id") != b["id"]
            and b.get("supersedes_fact_id") != a["id"])


def _same_claim(a: dict[str, Any], b: dict[str, Any]) -> bool:
    score = jaccard(_tokens(a["statement"]), _tokens(b["statement"]))
    if score >= SAME_CLAIM_JACCARD:
        return True
    return bool(a.get("topic")) and a.get("topic") == b.get("topic") and score >= SAME_TOPIC_JACCARD


def _evenly_spaced(dates: set[str]) -> bool:
    days = sorted(datetime.strptime(d, "%Y-%m-%d").toordinal() for d in dates)
    gaps = [b - a for a, b in zip(days, days[1:])]
    return max(gaps) - min(gaps) <= RECURRING_GAP_TOLERANCE_DAYS


def _recurring_templates(dated: list[dict[str, Any]]) -> set[tuple[str, frozenset]]:
    """Statement templates (dates removed) seen with several evenly spaced dates,
    e.g. a monthly payment. A milestone that keeps slipping has irregular gaps."""
    dates: dict[tuple[str, frozenset], set[str]] = {}
    for f in dated:
        dates.setdefault((f["kind"], _tokens(f["statement"])), set()).add(_date(f))
    return {k for k, v in dates.items() if len(v) >= RECURRING_MIN_DATES and _evenly_spaced(v)}


def deterministic_conflicts(project_id: int, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dated = [f for f in facts if f["kind"] in DATED_KINDS and _date(f)]
    recurring = _recurring_templates(dated)
    seen: set[tuple] = set()
    for a, b in combinations(dated, 2):
        if a["kind"] != b["kind"] or not _eligible(a, b) or _date(a) == _date(b):
            continue
        if (a["kind"], _tokens(a["statement"])) in recurring or not _same_claim(a, b):
            continue
        a, b = _pair(a, b)
        dedupe = tuple(sorted([(a["statement"].strip().lower(), _date(a)),
                               (b["statement"].strip().lower(), _date(b))]))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        latest = _newer(a, b)
        out.append(_row(project_id, a, b, "date_mismatch",
                        f'"{a["statement"]}" says {_date(a)}; "{b["statement"]}" says {_date(b)}.',
                        latest["id"], 0.75, "deterministic"))
    by_statement: dict[tuple[str, frozenset], list[dict[str, Any]]] = {}
    for f in facts:
        if f.get("status"):
            by_statement.setdefault((f["kind"], _tokens(f["statement"])), []).append(f)
    for group in by_statement.values():
        for a, b in combinations(group, 2):
            if a["status"] != b["status"] and _eligible(a, b):
                a, b = _pair(a, b)
                dedupe = ("status", a["kind"], _tokens(a["statement"]), frozenset({a["status"], b["status"]}))
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                latest = _newer(a, b)
                out.append(_row(project_id, a, b, "status_mismatch",
                                f'"{a["statement"]}" is {a["status"]} in {a.get("file_name")} '
                                f'but {b["status"]} in {b.get("file_name")}.',
                                latest["id"], 0.7, "deterministic"))
    return out


def candidate_pairs(facts: list[dict[str, Any]], checked: set[tuple[int, int]],
                    max_pairs: int, min_jaccard: float = 0.3) -> list[tuple[dict, dict, float]]:
    """Related fact pairs worth an LLM judgement, most related first."""
    pool = [f for f in facts if f["kind"] in JUDGED_KINDS]
    scored: list[tuple[dict, dict, float]] = []
    for a, b in combinations(pool, 2):
        if a["kind"] != b["kind"] or not _eligible(a, b):
            continue
        a, b = _pair(a, b)
        if (a["id"], b["id"]) in checked:
            continue
        score = _related(a, b, min_jaccard)
        if score:
            scored.append((a, b, score))
    scored.sort(key=lambda t: -t[2])
    return scored[:max_pairs]


def _row(project_id: int, a: dict[str, Any], b: dict[str, Any], conflict_type: str, explanation: str,
         latest_id: int | None, confidence: float, method: str, status: str = "needs_confirmation") -> dict:
    return {"project_id": project_id, "fact_a_id": a["id"], "fact_b_id": b["id"],
            "conflict_type": conflict_type, "explanation": explanation,
            "likely_latest_fact_id": latest_id, "confidence": confidence,
            "status": status, "method": method}


def _judge_prompt(a: dict[str, Any], b: dict[str, Any]) -> str:
    def show(label: str, f: dict[str, Any]) -> str:
        return (f'{label}: ({f["kind"]}) "{f["statement"]}" | status={f.get("status")} '
                f'date={_date(f)} | source={f.get("file_name")} | asserted={f.get("last_verified_at")}')
    return f"""
Two facts from different documents of the same project. Do they contradict each
other (cannot both be true now)? Different levels of detail, or one being a
sub-step of the other, is NOT a contradiction.
Return JSON: {{"contradicts": true|false, "conflict_type": "date|scope|decision|requirement|status|owner|other",
"explanation": "one sentence", "likely_latest": "A|B|unknown", "confidence": 0.0}}

{show("A", a)}
{show("B", b)}
""".strip()


def judge_pair(project_id: int, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    raw = llm.generate_json(_judge_prompt(a, b))
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0.5)))
    except (TypeError, ValueError):
        confidence = 0.5
    if not raw.get("contradicts"):
        return _row(project_id, a, b, "none", str(raw.get("explanation") or ""), None,
                    confidence, "llm", status="no_conflict")
    pick = str(raw.get("likely_latest") or "").strip().upper()
    latest = a["id"] if pick == "A" else b["id"] if pick == "B" else _newer(a, b)["id"]
    return _row(project_id, a, b, str(raw.get("conflict_type") or "other")[:40],
                str(raw.get("explanation") or ""), latest, confidence, "llm")


def detect_conflicts(project_ref: str | None = None, use_llm: bool = True,
                     max_pairs: int = 200) -> dict[str, Any]:
    projects = [intel_db.get_project(project_ref)] if project_ref else intel_db.list_projects()
    found = judged = cleared = 0
    for project in [p for p in projects if p]:
        facts = intel_db.project_facts(project["id"], limit=2000)
        rows = deterministic_conflicts(project["id"], facts)
        cleared += intel_db.clear_open_deterministic_conflicts(project["id"])
        for row in rows:
            intel_db.upsert_conflict(row)
        found += len(rows)
        if not use_llm:
            continue
        checked = intel_db.checked_fact_pairs(project["id"])
        for a, b, _score in candidate_pairs(facts, checked, max_pairs):
            try:
                row = judge_pair(project["id"], a, b)
            except llm.LLMError as e:
                console.log(f"[yellow]Conflict judging stopped for {project['name']}:[/yellow] {e}")
                break
            intel_db.upsert_conflict(row)
            judged += 1
            found += row["status"] == "needs_confirmation"
    console.log(f"[green]detect-conflicts:[/green] {found} conflict(s); {judged} pair(s) LLM-judged; "
                f"{cleared} unconfirmed rule-based row(s) rebuilt")
    return {"projects": len(projects), "conflicts": found, "llm_judged": judged, "rebuilt": cleared}


def is_active_project(last_activity: Any, now: datetime, active_days: int = ACTIVE_PROJECT_DAYS) -> bool:
    return isinstance(last_activity, datetime) and last_activity >= now - timedelta(days=active_days)


def compute_stale_flags(facts: list[dict[str, Any]], conflicts: list[dict[str, Any]],
                        latest_by_family: dict[tuple[str, str], int], now: datetime,
                        max_age_days: int = 365,
                        active_days: int = ACTIVE_PROJECT_DAYS) -> list[dict[str, Any]]:
    """``not_reverified`` applies only to facts in active projects; finished or
    dormant projects keep their open items as historical record."""
    flags: list[dict[str, Any]] = []
    by_id = {f["id"]: f for f in facts}
    for f in facts:
        sup = f.get("supersedes_fact_id")
        if sup and sup in by_id:
            flags.append({"object_type": "fact", "object_id": sup, "reason": "superseded",
                          "detail": f"Superseded by fact {f['id']}.", "newer_evidence_id": f["id"]})
    for c in conflicts:
        latest = c.get("likely_latest_fact_id")
        if not latest:
            continue
        loser = c["fact_b_id"] if latest == c["fact_a_id"] else c["fact_a_id"]
        flags.append({"object_type": "fact", "object_id": loser, "reason": "contradicted_by_newer",
                      "detail": f"Conflicts with newer fact {latest}.", "newer_evidence_id": latest})
    cutoff = now - timedelta(days=max_age_days)
    for f in facts:
        if f.get("is_latest") is False:
            newer = latest_by_family.get((f.get("scope_key"), f.get("family_key")))
            flags.append({"object_type": "fact", "object_id": f["id"], "reason": "older_document_version",
                          "detail": "Comes from a document that has a newer version.",
                          "newer_evidence_id": newer})
        at = f.get("evidence_at")
        if (f["kind"] in OPEN_KINDS and (f.get("status") or "open") not in CLOSED
                and isinstance(at, datetime) and at < cutoff
                and is_active_project(f.get("project_last_activity"), now, active_days)):
            flags.append({"object_type": "fact", "object_id": f["id"], "reason": "not_reverified",
                          "detail": f"Open item last asserted {at.date().isoformat()}.",
                          "newer_evidence_id": None})
    seen: set[tuple] = set()
    unique = []
    for fl in flags:
        key = (fl["object_type"], fl["object_id"], fl["reason"])
        if key not in seen:
            seen.add(key)
            unique.append(fl)
    return unique


def detect_stale(max_age_days: int = 365, active_days: int = ACTIVE_PROJECT_DAYS) -> dict[str, Any]:
    facts = intel_db.all_facts_for_staleness()
    flags = compute_stale_flags(facts, intel_db.all_open_conflicts(), intel_db.latest_versions_by_family(),
                                datetime.now(), max_age_days, active_days)
    intel_db.replace_stale_flags(flags)
    by_reason: dict[str, int] = {}
    for f in flags:
        by_reason[f["reason"]] = by_reason.get(f["reason"], 0) + 1
    console.log(f"[green]detect-stale:[/green] {len(flags)} flag(s) {by_reason}")
    return {"flags": len(flags), "by_reason": by_reason}
