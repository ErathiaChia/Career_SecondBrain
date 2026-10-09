"""Document Intelligence Cards (brief §6 Layer 4, §7): one compact, searchable
record per document, built from

  * deterministic inputs (no LLM): the file's typed facts, entity mentions,
    project assignment and version family;
  * the ``card`` object the extraction call returns in the SAME pass as the
    facts (summary, keywords, topics, doc_type, outcomes, dates, references).

Documents extracted before cards existed get ONE cheap card-only LLM call
(``backfill_cards``); afterwards a card is re-assembled without any LLM call
whenever its deterministic inputs move (``refresh_cards``). Related documents
come from the version family, project siblings sharing entities, and card
embedding neighbours.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from rich.console import Console

from career_history import cards_db, config, db

console = Console()

INTELLIGENCE_VERSION = "card-v1"
CARD_PROMPT_VERSION = "card-only-v1"

_CUSTOMER_TYPES = {"client", "company", "organization"}
_FACT_KIND_FIELD = {"decision": "decisions", "risk": "risks", "action_item": "actions", "commitment": "actions",
                    "outcome": "outcomes", "milestone": "milestones"}


# --- pure assembly ----------------------------------------------------------------

def inputs_hash(facts: list[dict[str, Any]], mentions: list[dict[str, Any]], projects: list[dict[str, Any]],
                versions: list[dict[str, Any]]) -> str:
    key = {"f": sorted((f["id"], f.get("status")) for f in facts),
           "m": sorted((m["id"], int(m.get("mention_count") or 0)) for m in mentions),
           "p": sorted(p["id"] for p in projects),
           "v": sorted((v["file_id"], bool(v.get("is_latest"))) for v in versions)}
    return hashlib.sha256(json.dumps(key, default=str, sort_keys=True).encode()).hexdigest()


def _iso_date(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    s = str(value or "")[:10]
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def assemble(file_row: dict[str, Any], llm_card: dict[str, Any] | None, facts: list[dict[str, Any]],
             mentions: list[dict[str, Any]], projects: list[dict[str, Any]], versions: list[dict[str, Any]],
             filename_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pure: the card row (minus embedding/relations) from its inputs."""
    llm_card = llm_card or {}
    ents = [{"id": m["id"], "name": m["name"], "type": m["type"]} for m in mentions]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for e in ents:
        by_type.setdefault(e["type"], []).append({"id": e["id"], "name": e["name"]})
    decisions = [{"fact_id": f["id"], "statement": f["statement"], "status": f.get("status")}
                 for f in facts if f["kind"] == "decision"][:15]
    risks = [{"fact_id": f["id"], "statement": f["statement"], "status": f.get("status"), "priority": f.get("priority")}
             for f in facts if f["kind"] == "risk"][:15]
    actions = [{"fact_id": f["id"], "statement": f["statement"], "status": f.get("status"),
                "due": (f.get("attributes") or {}).get("due_at")}
               for f in facts if f["kind"] in ("action_item", "commitment")][:20]
    outcomes: list[dict[str, Any]] = [{"fact_id": f["id"], "statement": f["statement"],
                                       "metric": (f.get("attributes") or {}).get("metric")}
                                      for f in facts if f["kind"] == "outcome"]
    seen = {o["statement"].casefold() for o in outcomes}
    for o in llm_card.get("outcomes") or []:
        stmt = str((o.get("statement") if isinstance(o, dict) else o) or "").strip()
        if stmt and stmt.casefold() not in seen:
            seen.add(stmt.casefold())
            outcomes.append({"fact_id": None, "statement": stmt, "metric": (o.get("metric") if isinstance(o, dict) else None)})
    dates: list[dict[str, Any]] = []
    seen_d: set[tuple[str, str]] = set()
    for f in facts:
        for raw, label in ((f.get("occurred_at"), f["kind"]), ((f.get("attributes") or {}).get("due_at"), f"{f['kind']} due")):
            iso = _iso_date(raw)
            if iso and (iso, label) not in seen_d:
                seen_d.add((iso, label))
                dates.append({"date": iso, "label": label, "source": "fact", "fact_id": f["id"]})
    for d in llm_card.get("dates") or []:
        iso = _iso_date(d.get("date") if isinstance(d, dict) else d)
        label = str((d.get("label") if isinstance(d, dict) else "") or "")[:80]
        if iso and (iso, label) not in seen_d:
            seen_d.add((iso, label))
            dates.append({"date": iso, "label": label, "source": "llm"})
    ff = filename_fields or {}
    if ff.get("date") and _iso_date(ff["date"]):
        dates.append({"date": _iso_date(ff["date"]), "label": "filename", "source": "filename"})
    dates.sort(key=lambda x: x["date"])
    doc_date = next((d["date"] for d in dates if d["source"] == "filename"), None) \
        or (dates[0]["date"] if dates else None) or _iso_date(file_row.get("last_modified_at"))
    title = file_row.get("title") or llm_card.get("title") or file_row.get("file_name")
    doc_type = (llm_card.get("doc_type") or ff.get("doc_type") or _doc_type_from_ext(file_row.get("file_type")))
    topics = [str(t).lower() for t in (llm_card.get("topics") or [])][:6]
    keywords = [str(k) for k in (llm_card.get("keywords") or [])][:8]
    card = {
        "file_id": file_row["file_id"],
        "source_hash": file_row["file_hash"],
        "intelligence_version": INTELLIGENCE_VERSION,
        "inputs_hash": inputs_hash(facts, mentions, projects, versions),
        "title": title,
        "doc_type": doc_type,
        "summary": str(llm_card.get("summary") or "")[:900],
        "keywords": keywords,
        "topics": topics,
        "entities": ents[:40],
        "projects": [{"id": p["id"], "name": p["name"], "project_key": p.get("project_key")} for p in projects],
        "people": by_type.get("person", [])[:20],
        "customers": [x for t in _CUSTOMER_TYPES for x in by_type.get(t, [])][:10],
        "products": by_type.get("product", [])[:10],
        "technologies": by_type.get("technology", [])[:15],
        "dates": dates[:12],
        "doc_date": doc_date,
        "decisions": decisions,
        "risks": risks,
        "actions": actions,
        "outcomes": outcomes[:12],
        "references": [{"text": str(r), "file_id": None} for r in (llm_card.get("references") or [])][:8],
        "related_file_ids": [],
        "llm_card": llm_card,
    }
    card["card_text"] = card_text(card, file_row)
    return card


def _doc_type_from_ext(file_type: Any) -> str:
    ft = str(file_type or "").lower().lstrip(".")
    return {"pptx": "presentation", "ppt": "presentation", "xlsx": "spreadsheet", "xls": "spreadsheet",
            "csv": "spreadsheet", "eml": "email", "srt": "transcript", "vtt": "transcript",
            "mp3": "transcript", "m4a": "transcript", "mp4": "transcript"}.get(ft, "other")


def card_text(card: dict[str, Any], file_row: dict[str, Any] | None = None) -> str:
    """The text that is embedded and full-text indexed for card-first retrieval."""
    parts = [str(card.get("title") or ""), str(card.get("doc_type") or ""),
             (file_row or {}).get("file_name") or "", (file_row or {}).get("folder") or "",
             str(card.get("summary") or ""),
             "Keywords: " + ", ".join(card.get("keywords") or []),
             "Topics: " + ", ".join(card.get("topics") or []),
             "Projects: " + ", ".join(p["name"] for p in card.get("projects") or []),
             "Entities: " + ", ".join(e["name"] for e in (card.get("entities") or [])[:25]),
             "Decisions: " + " | ".join(d["statement"] for d in (card.get("decisions") or [])[:6]),
             "Outcomes: " + " | ".join(o["statement"] for o in (card.get("outcomes") or [])[:6])]
    return "\n".join(p for p in parts if p and not p.endswith(": "))[:6000]


def related_documents(version_rows: list[dict[str, Any]], siblings: list[dict[str, Any]],
                      neighbours: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    """Pure ranking: version family (1.0) > project siblings by shared entities
    (0.5-0.9) > embedding neighbours (cosine). One row per file, best wins."""
    best: dict[int, dict[str, Any]] = {}

    def put(fid: int, relation: str, score: float) -> None:
        if fid not in best or score > best[fid]["score"]:
            best[fid] = {"file_id": fid, "relation": relation, "score": round(score, 3)}
    for v in version_rows:
        put(int(v["file_id"]), "version", 1.0)
    top = max((int(s.get("shared") or 0) for s in siblings), default=0)
    for s in siblings:
        shared = int(s.get("shared") or 0)
        if shared > 0:
            put(int(s["file_id"]), "project", 0.5 + 0.4 * shared / top)
    for n in neighbours:
        put(int(n["file_id"]), "similar", float(n.get("cosine") or 0.0))
    return sorted(best.values(), key=lambda r: (-r["score"], r["file_id"]))[:limit]


# --- build / refresh ----------------------------------------------------------------

def build_card(file_id: int, llm_card: dict[str, Any] | None = None, model: str | None = None,
               embed_text: bool = True) -> dict[str, Any] | None:
    """Assemble + store the card for one file. ``llm_card`` from the extraction
    call (or backfill); when None the previously stored llm_card is reused so a
    deterministic re-assembly never needs the model."""
    if not cards_db.table_exists("document_cards"):
        return None
    inputs = cards_db.card_inputs(file_id)
    if inputs is None:
        return None
    llm_card = llm_card if llm_card is not None else (inputs.get("existing_llm_card") or {})
    model = model or (inputs.get("existing_model") if not llm_card else model)
    try:
        from career_history import filename
        ff = filename.parse_filename(inputs["file"]["file_name"])
    except Exception:  # noqa: BLE001
        ff = {}
    card = assemble(inputs["file"], llm_card, inputs["facts"], inputs["mentions"], inputs["projects"],
                    inputs["versions"], ff)
    card["model"] = model
    embedding = None
    if embed_text and card["card_text"] != cards_db.existing_card_text(file_id):
        try:
            from career_history import embed
            embedding = embed.embed([card["card_text"]])[0]
        except Exception as e:  # noqa: BLE001 — keep the card, embed next pass
            console.log(f"[yellow]card embedding skipped for file {file_id}:[/yellow] {e}")
    cards_db.upsert_card(card, embedding)
    cards_db.mark_card_version(file_id, INTELLIGENCE_VERSION)
    return card


def refresh_relations(file_ids: list[int] | None = None, limit: int | None = None) -> int:
    """Second pass: document -> document edges once neighbours have embeddings."""
    if not cards_db.table_exists("document_relations"):
        return 0
    ids = file_ids
    if ids is None:
        ids = cards_db.stale_input_cards(limit) if limit else [r for r in _all_card_ids()]
    n = 0
    for fid in ids:
        inputs = cards_db.card_inputs(fid)
        if inputs is None:
            continue
        rows = related_documents(inputs["versions"], cards_db.project_siblings(fid), cards_db.card_neighbors(fid))
        cards_db.replace_relations(fid, rows)
        n += 1
    return n


def _all_card_ids() -> list[int]:
    from sqlalchemy import text
    with db.conn() as c:
        return [r[0] for r in c.execute(text("SELECT file_id FROM document_cards ORDER BY built_at DESC")).fetchall()]


def _card_only_prompt(text_first_window: str, file_name: str, folder: str, file_type: str) -> str:
    from career_history.graph import DOC_TYPES, doc_type_hint
    return f"""
Summarise this document into ONE compact intelligence card. Return only JSON.
Source hint: {doc_type_hint(file_type, file_name)}
File: {file_name} (folder: {folder})

{{
  "title": "string",
  "doc_type": "{"|".join(DOC_TYPES)}",
  "summary": "2-3 sentences: what the document is, for whom, and what it concludes or asks for",
  "keywords": ["<=8 short keywords"],
  "topics": ["<=6 lowercase topics"],
  "outcomes": [{{"statement": "a result achieved, as stated", "metric": "number/unit if stated"}}],
  "dates": [{{"date": "YYYY-MM-DD", "label": "what the date is"}}],
  "references": ["other documents this one cites or depends on"]
}}

Document:
\"\"\"{text_first_window}\"\"\"
""".strip()


def backfill_cards(folder: str | None = None, limit: int | None = 500, use_llm: bool = True,
                   deadline: datetime | None = None) -> dict[str, Any]:
    """One cheap card-only LLM call per already-extracted document without a
    current card (the only cost of adding cards to existing files)."""
    if not cards_db.table_exists("document_cards"):
        return {"skipped": "migration 0017 not applied"}
    from career_history import graph, llm
    rows = cards_db.backfill_candidates(INTELLIGENCE_VERSION, folder=folder, limit=limit)
    done = failed = 0
    stopped = False
    for r in rows:
        if deadline is not None and datetime.now() >= deadline:
            stopped = True
            break
        try:
            llm_card = {}
            if use_llm:
                raw = llm.generate_json(_card_only_prompt(r["content"] or "", r["file_name"], r["folder"], r["file_type"]),
                                        timeout=graph._extraction_timeout())
                llm_card = graph.merge_cards([raw]) if isinstance(raw, dict) else {}
            build_card(r["file_id"], llm_card=llm_card, model=llm._model() if use_llm else None)
            done += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            console.log(f"[red]card backfill failed[/red] {r['file_name']}: {e}")
    console.log(f"[green]cards backfill:[/green] {done} built, {failed} failed, {len(rows) - done - failed} left")
    return {"candidates": len(rows), "built": done, "failed": failed, "stopped_early": stopped}


def refresh_cards(folder: str | None = None, limit: int | None = None, use_llm: bool = True,
                  backfill_limit: int | None = 500, deadline: datetime | None = None) -> dict[str, Any]:
    """Weekly stage: backfill missing cards (LLM, capped) -> re-assemble cards
    whose inputs changed (no LLM) -> refresh relations for touched files."""
    if not cards_db.table_exists("document_cards"):
        return {"skipped": "migration 0017 not applied"}
    out: dict[str, Any] = {}
    out["backfill"] = backfill_cards(folder=folder, limit=backfill_limit, use_llm=use_llm, deadline=deadline)
    stale = cards_db.stale_input_cards(limit)
    rebuilt = 0
    for fid in stale:
        if build_card(fid) is not None:
            rebuilt += 1
    out["reassembled"] = rebuilt
    touched = list(dict.fromkeys(stale + [0]))[:-1]
    out["relations"] = refresh_relations(file_ids=touched) if touched else 0
    out.update(cards_db.card_count())
    console.log(f"[green]cards:[/green] {out}")
    return out
