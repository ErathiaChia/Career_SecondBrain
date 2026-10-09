"""Project discovery: one first-class ``projects`` row per project folder.

Sources, most specific wins for each file:
  1. ``vault_manifest`` rows with ``kind = 'project'`` (exported by era_auditor
     from its human-curated project registry: client, lifecycle, archetype).
  2. ``seed.project_roots`` path segments (the same taxonomy seed_entities uses).

Each file belongs to the project whose folder fragment is the longest match in
its path. Deterministic fields carry a confidence and a ``field_sources`` entry;
``enrich_with_llm`` fills only the fields still missing.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean
from typing import Any

from rich.console import Console

from career_history import config, db, filename, intel_db

console = Console()

_NUM_PREFIX = re.compile(r"^\s*\d+[.\s_)\-]*")
_ACTIVE_DAYS = 90
_DORMANT_DAYS = 365

_TYPE_HINTS = (
    ("rfp", "sales_opportunity"), ("rfq", "sales_opportunity"), ("tender", "sales_opportunity"),
    ("proposal", "sales_opportunity"), ("sow", "delivery_project"), ("uat", "delivery_project"),
    ("workshop", "workshop"), ("training", "training_engagement"), ("poc", "poc"),
    ("research", "research_activity"),
)


@dataclass
class Candidate:
    key: str
    name: str
    fragment: str
    source: str
    manifest: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)


def strip_prefix(name: str) -> str:
    return _NUM_PREFIX.sub("", name or "").strip() or (name or "").strip()


def candidates_from_manifest(rows: list[dict[str, Any]]) -> list[Candidate]:
    out = []
    for r in rows:
        path = str(r.get("path") or "").strip("/")
        if not path:
            continue
        last = path.rsplit("/", 1)[-1]
        name = r.get("name") or strip_prefix(last)
        aliases = sorted({a for a in (last, strip_prefix(last), r.get("project_key"), name) if a})
        out.append(Candidate(key=r.get("project_key") or path, name=name,
                             fragment=f"/{path}/", source="manifest", manifest=r, aliases=aliases))
    return out


def candidates_from_seed(file_paths: list[str], roots: list[str]) -> list[Candidate]:
    seen: dict[str, Candidate] = {}
    for path in file_paths:
        for root in roots:
            idx = path.find(root)
            if idx < 0:
                continue
            rest = path[idx + len(root):]
            if "/" not in rest:
                continue
            seg = rest.split("/", 1)[0].strip()
            if not seg:
                continue
            fragment = f"{root}{seg}/"
            if fragment not in seen:
                key = f"path:{root.strip('/')}/{seg}"
                seen[fragment] = Candidate(key=key, name=strip_prefix(seg), fragment=fragment,
                                           source="path-seed",
                                           aliases=sorted({seg, strip_prefix(seg)}))
            break
    return list(seen.values())


def assign_files(files: list[dict[str, Any]], candidates: list[Candidate]) -> dict[str, list[dict[str, Any]]]:
    """Map candidate key -> files, each file going to its longest matching fragment."""
    ordered = sorted(candidates, key=lambda c: len(c.fragment), reverse=True)
    out: dict[str, list[dict[str, Any]]] = {}
    for f in files:
        path = f["file_path"]
        for cand in ordered:
            if cand.fragment in path:
                out.setdefault(cand.key, []).append(f)
                break
    return out


def infer_status(last_activity: datetime | None, now: datetime) -> tuple[str | None, float]:
    if last_activity is None:
        return None, 0.0
    age = (now - last_activity).days
    if age <= _ACTIVE_DAYS:
        return "ACTIVE", 0.6
    if age <= _DORMANT_DAYS:
        return "DORMANT", 0.5
    return "ARCHIVED", 0.5


def manifest_status(row: dict[str, Any]) -> str | None:
    lifecycle = str(row.get("lifecycle") or "").lower()
    status = str(row.get("status") or "").lower()
    if lifecycle == "archived" or status in {"archived", "closed", "lost", "won_closed"}:
        return "ARCHIVED"
    if status in {"on_hold", "paused", "dormant"}:
        return "DORMANT"
    if lifecycle or status:
        return "ACTIVE"
    return None


def majority_client(files: list[dict[str, Any]]) -> tuple[str | None, float]:
    """Most common filename-convention client, if it dominates the project."""
    votes = Counter()
    for f in files:
        client = filename.parse_filename(f.get("file_name") or "").get("client")
        if client and len(client) >= 2 and not client.isdigit():
            votes[client] += 1
    if not votes:
        return None, 0.0
    client, n = votes.most_common(1)[0]
    share = n / max(1, len(files))
    if n >= 2 and share >= 0.4:
        return client, round(min(0.75, 0.4 + share / 2), 2)
    return None, 0.0


def infer_type(files: list[dict[str, Any]]) -> tuple[str | None, float]:
    names = re.sub(r"[^a-z0-9]+", " ", " ".join((f.get("file_name") or "").lower() for f in files))
    for hint, ptype in _TYPE_HINTS:
        if re.search(rf"\b{hint}\b", names):
            return ptype, 0.45
    return None, 0.0


def build_project(cand: Candidate, files: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    m = cand.manifest
    fields: dict[str, tuple[Any, float, str]] = {"name": (cand.name, 0.95 if m else 0.8, cand.source)}
    if m.get("customer_name") or m.get("customer_code"):
        fields["client"] = (m.get("customer_name") or m.get("customer_code"), 0.95, "manifest")
    else:
        client, conf = majority_client(files)
        if client:
            fields["client"] = (client, conf, "filenames")
    if m.get("initiative_type"):
        fields["project_type"] = (m["initiative_type"], 0.95, "manifest")
    else:
        ptype, conf = infer_type(files)
        if ptype:
            fields["project_type"] = (ptype, conf, "filenames")
    mtimes = [f["last_modified_at"] for f in files if f.get("last_modified_at")]
    last_activity = max(mtimes) if mtimes else None
    status = manifest_status(m) if m else None
    if status:
        fields["status"] = (status, 0.9, "manifest")
    else:
        inferred, conf = infer_status(last_activity, now)
        if inferred:
            fields["status"] = (inferred, conf, "recency")
    owner = (m.get("metadata") or {}).get("owner") if m else None
    if owner:
        fields["owner"] = (owner, 0.9, "manifest")
    return {
        "project_key": cand.key,
        "name": cand.name,
        "client": fields.get("client", (None,))[0],
        "project_type": fields.get("project_type", (None,))[0],
        "status": fields.get("status", (None,))[0],
        "lifecycle": m.get("lifecycle") if m else None,
        "owner": owner,
        "source_folder": cand.fragment.strip("/"),
        "first_activity": min(mtimes) if mtimes else None,
        "last_activity": last_activity,
        "file_count": len(files),
        "confidence": round(mean(v[1] for v in fields.values()), 3),
        "field_sources": {k: {"source": v[2], "confidence": v[1]} for k, v in fields.items()},
        "aliases": cand.aliases,
        "metadata": {"source": cand.source, "tags": m.get("tags") or [], "year": m.get("year")},
    }


def discover_projects() -> dict[str, Any]:
    """Rebuild projects + project_files from the manifest and path seed."""
    files = intel_db.live_files()
    roots = [str(r) for r in (config.get().get("seed", {}).get("project_roots") or []) if str(r).strip()]
    candidates = candidates_from_manifest(intel_db.manifest_projects())
    candidates += candidates_from_seed([f["file_path"] for f in files], roots)
    if not candidates:
        console.log("[yellow]discover-projects: no manifest projects and no seed.project_roots.[/yellow]")
        return {"projects": 0, "files": 0, "removed": 0}
    assigned = assign_files(files, candidates)
    now = datetime.now()
    keys: list[str] = []
    linked = 0
    for cand in candidates:
        members = assigned.get(cand.key, [])
        if not members:
            continue
        project = build_project(cand, members, now)
        # Path-seed projects reuse seed_entities' canonical name (the raw folder
        # segment) so both resolve to the same entity row.
        folder_segment = cand.fragment.strip("/").rsplit("/", 1)[-1]
        project["entity_id"] = db.upsert_entity(
            canonical_name=cand.name if cand.source == "manifest" else folder_segment,
            entity_type="project",
            aliases=cand.aliases,
            metadata={"source": cand.source, "project_key": cand.key},
        )
        project_id = intel_db.upsert_project(project)
        intel_db.replace_project_files(project_id, [f["file_id"] for f in members])
        keys.append(cand.key)
        linked += len(members)
    removed = intel_db.mark_missing_projects(keys)
    summary = {"projects": len(keys), "files": linked, "removed": removed}
    console.log(f"[green]discover-projects done.[/green] {summary}")
    return summary


_ENRICH_PROMPT = """You are filling in missing metadata for one work project in a
consultant's knowledge base. Use ONLY the evidence below. Leave a field null when
the evidence does not support it.

Project folder: {folder}
Known fields: {known}

Recent file names:
{files}

Extracted facts:
{facts}

Return JSON:
{{"client": "organisation the work is for, or null",
  "project_type": "sales_opportunity|delivery_project|poc|workshop|training_engagement|research_activity|strategic_initiative|support_activity or null",
  "owner": "person who leads the work, or null",
  "confidence": {{"client": 0.0, "project_type": 0.0, "owner": 0.0}}}}
"""


def enrich_with_llm(project_ref: str | None = None, min_confidence: float = 0.5) -> dict[str, Any]:
    from career_history import llm

    projects = [intel_db.get_project(project_ref)] if project_ref else intel_db.list_projects()
    enriched = failed = 0
    for p in [p for p in projects if p]:
        missing = [f for f in ("client", "project_type", "owner") if not p.get(f)]
        if not missing:
            continue
        prompt = _ENRICH_PROMPT.format(
            folder=p["source_folder"],
            known={k: p.get(k) for k in ("name", "client", "project_type", "status", "owner")},
            files="\n".join(f"- {n}" for n in intel_db.project_file_names(p["id"])) or "(none)",
            facts="\n".join(f"- [{f['kind']}] {f['statement']}"
                            for f in intel_db.project_fact_samples(p["id"])) or "(none)",
        )
        try:
            data = llm.generate_json(prompt)
        except llm.LLMError as e:
            failed += 1
            console.log(f"[red]enrich failed[/red] {p['name']}: {e}")
            continue
        confs = data.get("confidence") if isinstance(data.get("confidence"), dict) else {}
        fields, sources = {}, {}
        for key in missing:
            value = data.get(key)
            try:
                conf = float(confs.get(key) or 0)
            except (TypeError, ValueError):
                conf = 0.0
            if value and isinstance(value, str) and conf >= min_confidence:
                fields[key] = value.strip()
                sources[key] = {"source": "llm", "confidence": round(conf, 2)}
        if fields:
            intel_db.update_project_fields(p["id"], fields, sources, None)
            enriched += 1
    return {"enriched": enriched, "failed": failed}
