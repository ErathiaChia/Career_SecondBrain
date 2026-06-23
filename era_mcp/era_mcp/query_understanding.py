"""Query understanding: rewrite a natural-language question into a keyword-rich
search string, optional sub-queries, and an optional HyDE document.

Best-effort: if the LLM is unavailable or returns junk, callers get the identity
rewrite (the original query) so retrieval still runs.
"""
from __future__ import annotations

from typing import Any

from era_mcp import config, llm

_SYSTEM = (
    "You rewrite a user's question into inputs for a hybrid search engine over a "
    "personal knowledge base (work documents, meeting transcripts). Return ONLY a "
    "JSON object with keys:\n"
    '  "search_query": a concise keyword-rich version of the question (good for '
    "both lexical and semantic search),\n"
    '  "sub_queries": 0-3 focused sub-questions if the query is multi-part, else [],\n'
    '  "hyde_doc": a 1-2 sentence hypothetical answer passage (only if asked), else null.\n'
    "Keep proper nouns (clients, products, people, projects) verbatim."
)


def identity(query: str) -> dict[str, Any]:
    return {"search_query": query, "sub_queries": [], "hyde_doc": None}


async def rewrite_query(query: str) -> dict[str, Any]:
    """Return {search_query, sub_queries[], hyde_doc|None}. Identity on failure."""
    if not config.query_rewrite_enabled():
        return identity(query)
    want_hyde = "Include a hyde_doc." if config.hyde_enabled() else "Set hyde_doc to null."
    try:
        data = await llm.chat_json(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": f"{want_hyde}\n\nQuestion: {query}"}],
            timeout=config.query_rewrite_timeout(),
        )
    except Exception:
        return identity(query)
    if not isinstance(data, dict):
        return identity(query)
    search_query = (data.get("search_query") or "").strip() or query
    sub = data.get("sub_queries") or []
    sub = [str(s).strip() for s in sub if str(s).strip()][:3] if isinstance(sub, list) else []
    hyde = data.get("hyde_doc")
    hyde = str(hyde).strip() if (hyde and config.hyde_enabled()) else None
    return {"search_query": search_query, "sub_queries": sub, "hyde_doc": hyde}
