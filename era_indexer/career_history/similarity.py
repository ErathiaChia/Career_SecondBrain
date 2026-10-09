"""Cross-project similarity.

Each project gets a content vector (mean of its chunk embeddings, same space as
retrieval). Vector neighbours are re-scored with the overlap of the clients,
vendors, technologies, products and people the projects share:

    score = 0.7 * cosine + 0.3 * entity Jaccard

and the shared entities are stored so "why is this similar?" has an answer.
Reuse candidates come from the auditor's ``vault_reusable_assets`` export and
are served by era_mcp.
"""
from __future__ import annotations

from typing import Any

from rich.console import Console

from career_history import intel_db

console = Console()

SHARED_TYPES = ("client", "company", "organization", "vendor", "technology", "product", "person")
COSINE_WEIGHT = 0.7
ENTITY_WEIGHT = 0.3


def combine(neighbors: list[dict[str, Any]], entity_sets: dict[int, set[int]],
            top_k: int, names: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """Blend vector neighbours with entity overlap; keep the top_k per project."""
    names = names or {}
    by_project: dict[int, list[dict[str, Any]]] = {}
    for n in neighbors:
        a, b = n["project_id"], n["other_project_id"]
        ea, eb = entity_sets.get(a, set()), entity_sets.get(b, set())
        shared = ea & eb
        overlap = len(shared) / len(ea | eb) if (ea or eb) else 0.0
        cosine = float(n["cosine"] or 0.0)
        by_project.setdefault(a, []).append({
            "project_id": a,
            "other_project_id": b,
            "cosine": round(cosine, 4),
            "entity_overlap": round(overlap, 4),
            "score": round(COSINE_WEIGHT * cosine + ENTITY_WEIGHT * overlap, 4),
            "shared_entities": sorted(names.get(e, str(e)) for e in shared)[:15],
        })
    out: list[dict[str, Any]] = []
    for rows in by_project.values():
        rows.sort(key=lambda r: -r["score"])
        out.extend(rows[:top_k])
    return out


def refresh_similarity(top_k: int = 5) -> dict[str, Any]:
    embedded = intel_db.refresh_project_embeddings()
    neighbors = intel_db.project_vector_neighbors(top_k * 3)
    entity_sets = intel_db.project_entity_sets(SHARED_TYPES)
    shared_ids = {e for n in neighbors
                  for e in entity_sets.get(n["project_id"], set()) & entity_sets.get(n["other_project_id"], set())}
    rows = combine(neighbors, entity_sets, top_k, intel_db.entity_names(shared_ids))
    intel_db.replace_project_similarity(rows)
    console.log(f"[green]project-similarity:[/green] {embedded} project vector(s), {len(rows)} neighbour row(s)")
    return {"projects_embedded": embedded, "similarity_rows": len(rows)}
