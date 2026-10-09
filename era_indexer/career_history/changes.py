"""Change detection: what changed in a project, and why it matters.

Two sources feed ``project_changes``:
  - vault_events (file added / modified / deleted / restored, version_added),
    consumed by ``detect_changes``;
  - fact diffs recorded during re-extraction (``record_fact_diff``): facts that
    appeared, disappeared, or changed status/date/statement on the same topic.

``detect_changes`` then groups unprocessed changes per project and writes one
impact card per batch (LLM, or a deterministic summary with ``use_llm=False``).
The card says plainly when the documents do not explain *why* something changed.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from typing import Any

from rich.console import Console

from career_history import intel_db, llm

console = Console()

SEVERITY_ORDER = ["info", "notice", "warning", "critical"]
_KEY_KINDS = {"decision", "milestone", "risk", "requirement", "dependency", "commitment"}
NO_RATIONALE = "Change detected; rationale not found in the documents."


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _fact_sig(f: dict[str, Any]) -> tuple[str, str]:
    return f["kind"], _norm(f["statement"])


def _when(f: dict[str, Any]) -> str | None:
    value = f.get("occurred_at") or f.get("due_at")
    return str(value)[:10] if value else None


def diff_facts(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare a file's facts before and after re-extraction.

    Same (kind, statement): a status/priority/date change is ``fact_changed``.
    Same (kind, topic) with a different statement: ``fact_changed`` (revised).
    Otherwise ``fact_added`` / ``fact_removed``.
    """
    old_by_sig = {_fact_sig(f): f for f in old}
    new_by_sig = {_fact_sig(f): f for f in new}
    out: list[dict[str, Any]] = []
    for sig, nf in new_by_sig.items():
        of = old_by_sig.get(sig)
        if of is None:
            continue
        deltas = {k: (of.get(k), nf.get(k)) for k in ("status", "priority")
                  if (of.get(k) or None) != (nf.get(k) or None)}
        if _when(of) != _when(nf):
            deltas["date"] = (_when(of), _when(nf))
        if deltas:
            out.append({"change_type": "fact_changed", "kind": nf["kind"], "statement": nf["statement"],
                        "fact_id": nf.get("id"), "deltas": deltas})
    added = [f for s, f in new_by_sig.items() if s not in old_by_sig]
    removed = [f for s, f in old_by_sig.items() if s not in new_by_sig]
    removed_by_topic = {(f["kind"], f.get("topic")): f for f in removed if f.get("topic")}
    matched_removed: set[int] = set()
    for f in added:
        prev = removed_by_topic.get((f["kind"], f.get("topic"))) if f.get("topic") else None
        if prev is not None and id(prev) not in matched_removed:
            matched_removed.add(id(prev))
            out.append({"change_type": "fact_changed", "kind": f["kind"], "statement": f["statement"],
                        "fact_id": f.get("id"), "previous": prev["statement"], "topic": f.get("topic"),
                        "deltas": {"statement": (prev["statement"], f["statement"])}})
        else:
            out.append({"change_type": "fact_added", "kind": f["kind"], "statement": f["statement"],
                        "fact_id": f.get("id")})
    for f in removed:
        if id(f) not in matched_removed:
            out.append({"change_type": "fact_removed", "kind": f["kind"], "statement": f["statement"]})
    return out


def _fact_summary(d: dict[str, Any]) -> str:
    kind = d["kind"].replace("_", " ")
    if d["change_type"] == "fact_added":
        return f"New {kind}: {d['statement']}"
    if d["change_type"] == "fact_removed":
        return f"{kind.capitalize()} no longer stated: {d['statement']}"
    parts = []
    for field, (a, b) in d["deltas"].items():
        if field == "statement":
            parts.append(f'was "{a}"')
        else:
            parts.append(f"{field} {a or '-'} -> {b or '-'}")
    return f"{kind.capitalize()} changed: {d['statement']} ({'; '.join(parts)})"


def _fact_severity(d: dict[str, Any]) -> str:
    if d["change_type"] == "fact_changed" and ("date" in d["deltas"] or "statement" in d["deltas"]) \
            and d["kind"] in _KEY_KINDS:
        return "warning"
    if d["kind"] in _KEY_KINDS:
        return "notice"
    return "info"


def record_fact_diff(file_id: int, old: list[dict[str, Any]], new: list[dict[str, Any]],
                     extractor_version: str) -> int:
    """Write fact-level changes for one re-extracted file. Skipped on a file's
    first extraction or after an extractor upgrade, where every fact would look new."""
    comparable = [f for f in old if f.get("extractor_version") == extractor_version]
    if not comparable:
        return 0
    project_id = intel_db.project_ids_for_files([file_id]).get(file_id)
    diffs = diff_facts(comparable, new)
    for d in diffs:
        intel_db.insert_change(project_id, file_id, d["change_type"], _fact_summary(d),
                               payload=d, severity=_fact_severity(d))
    return len(diffs)


_EVENT_SEVERITY = {"deleted": "notice", "version_added": "notice", "restored": "info",
                   "added": "info", "modified": "info"}


def event_change(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") or {}
    name = event.get("file_name") or (event.get("file_path") or "").rsplit("/", 1)[-1]
    kind = event["kind"]
    project_id = event.get("current_project_id") or payload.get("project_id")
    if kind == "version_added":
        summary = f"New version {payload.get('version_label') or ''} of {payload.get('family_key') or name}".strip()
        change_type = "version_added"
    else:
        verb = {"added": "added", "modified": "modified", "deleted": "deleted", "restored": "restored"}[kind]
        summary = f"Document {verb}: {name}"
        change_type = f"file_{kind}"
    severity = _EVENT_SEVERITY.get(kind, "info")
    if kind == "deleted" and payload.get("facts"):
        severity = "warning"
        summary += f" ({len(payload['facts'])} extracted fact(s) went with it)"
    return {"project_id": project_id, "file_id": event.get("file_id"), "change_type": change_type,
            "summary": summary, "severity": severity,
            "payload": {"event_id": event["id"], "file_path": event.get("file_path"), **payload}}


def _max_severity(levels: list[str]) -> str:
    return max(levels or ["info"], key=lambda s: SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else 0)


def deterministic_impact(changes: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = defaultdict(int)
    for c in changes:
        by_type[c["change_type"]] += 1
    key = [c["summary"] for c in changes if c["severity"] in {"warning", "critical"}][:5]
    return {
        "summary": ", ".join(f"{n} {t.replace('_', ' ')}" for t, n in sorted(by_type.items())),
        "impact": key or [c["summary"] for c in changes[:3]],
        "affected_areas": sorted({(c.get("payload") or {}).get("kind") for c in changes
                                  if (c.get("payload") or {}).get("kind")}),
        "rationale": NO_RATIONALE,
        "rationale_found": False,
        "method": "deterministic",
    }


def _impact_prompt(project: dict[str, Any], changes: list[dict[str, Any]], state: dict[str, Any] | None) -> str:
    lines = [f"- [{c['severity']}] {c['summary']}" for c in changes[:60]]
    context = ""
    if state:
        s = state.get("state") or {}
        phase = (s.get("phase") or {}).get("value")
        blockers = [b["statement"] for b in (s.get("blockers") or {}).get("value", [])][:5]
        context = f"Current phase: {phase}. Known blockers: {blockers}."
    return f"""
You review changes detected in a work project's documents and explain what they mean.
Return JSON:
{{
  "summary": "one sentence: what changed",
  "impact": ["up to 4 short bullets: why it matters (scope, timeline, budget, risk, ownership)"],
  "affected_areas": ["timeline|scope|budget|risk|requirements|decisions|stakeholders|delivery"],
  "severity": "info|notice|warning|critical",
  "rationale": "why the change was made, ONLY if the changes themselves state it",
  "rationale_found": true
}}
If no reason is stated, set rationale_found to false and rationale to "{NO_RATIONALE}".
Do not invent consequences that are not implied by the changes.

Project: {project.get('name')} (client: {project.get('client') or 'unknown'}). {context}
Changes:
{chr(10).join(lines)}
""".strip()


def detect_changes(use_llm: bool = True) -> dict[str, Any]:
    events = intel_db.unprocessed_events()
    seen: set[int] = set()
    created = 0
    for event in events:
        if event["id"] in seen:
            continue
        seen.add(event["id"])
        c = event_change(event)
        if c["change_type"] == "file_modified" and not c["project_id"]:
            continue
        intel_db.insert_change(c["project_id"], c["file_id"], c["change_type"], c["summary"],
                               payload=c["payload"], severity=c["severity"])
        created += 1
    intel_db.mark_events_processed(seen)

    pending = intel_db.changes_without_impact()
    by_project: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for c in pending:
        by_project[c["project_id"]].append(c)
    cards = llm_cards = 0
    for project_id, changes in by_project.items():
        project = intel_db.get_project(project_id) or {"name": str(project_id)}
        impact = deterministic_impact(changes)
        severity = _max_severity([c["severity"] for c in changes])
        meaningful = [c for c in changes if c["change_type"] != "file_modified"]
        if use_llm and meaningful:
            try:
                raw = llm.generate_json(_impact_prompt(project, meaningful,
                                                       intel_db.current_project_state(project_id)))
                impact = {
                    "summary": str(raw.get("summary") or impact["summary"]),
                    "impact": [str(x) for x in (raw.get("impact") or [])][:4] or impact["impact"],
                    "affected_areas": [str(x) for x in (raw.get("affected_areas") or [])][:6],
                    "rationale": str(raw.get("rationale") or NO_RATIONALE) if raw.get("rationale_found")
                    else NO_RATIONALE,
                    "rationale_found": bool(raw.get("rationale_found")),
                    "method": "llm",
                }
                if raw.get("severity") in SEVERITY_ORDER:
                    severity = _max_severity([severity, raw["severity"]])
                llm_cards += 1
            except llm.LLMError as e:
                console.log(f"[yellow]Impact note fell back to deterministic for {project.get('name')}:[/yellow] {e}")
        intel_db.set_change_impact([c["id"] for c in changes], uuid.uuid4().hex[:12], impact, severity)
        cards += 1
    console.log(f"[green]detect-changes:[/green] {created} change(s) from {len(seen)} event(s), "
                f"{cards} impact card(s) ({llm_cards} LLM)")
    return {"events": len(seen), "changes_created": created, "impact_cards": cards, "llm_cards": llm_cards}
