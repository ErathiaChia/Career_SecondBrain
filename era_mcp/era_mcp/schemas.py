"""Request models shared by the HTTP surface (server.py) and the MCP surface
(mcp_server.py) so both call the same agent with the same contract."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from era_mcp import config

# Resolved once at import so the value appears as a concrete default in the
# generated OpenAPI schema (Open WebUI reads that default).
_DEFAULT_TOP_K = config.default_top_k()

AskMode = Literal["auto", "fast", "investigate"]


class SearchRequest(BaseModel):
    query: str = Field(description="Natural-language search query.")
    top_k: int = Field(default=_DEFAULT_TOP_K, description="Number of results to return.")
    folder: Optional[str] = Field(default=None, description="Folder name to restrict search to.")
    kind: Optional[str] = Field(default=None, description='Filter by "document" or "audio".')
    context_window: int = Field(
        default=3,
        description="Number of surrounding chunks (before and after) to include for broader context. 0 = matched chunk only.",
    )


class KnowledgeSearchRequest(SearchRequest):
    """Knowledge-first search request."""


class AskRequest(BaseModel):
    query: str = Field(description="Natural-language question to answer.")
    mode: AskMode = Field(
        default="auto",
        description=('"auto" lets the agent decide between a fast single-pass answer and a bounded '
                     'investigation (max 3 tool rounds); "fast" forces one retrieval + one answer; '
                     '"investigate" forces the investigation loop (compare versions, trace decisions, '
                     'gather career evidence).'),
    )
    project: Optional[str] = Field(default=None, description="Project name/key/alias to scope the question to.")
    top_k: int = Field(default=_DEFAULT_TOP_K, description="Chunks to retrieve and cite (used when adaptive_k is false).")
    adaptive_k: bool = Field(
        default=True,
        description="Size retrieval breadth to question complexity (simple/moderate/complex). Overrides top_k when on.",
    )
    folder: Optional[str] = Field(default=None, description="Restrict to a folder.")
    use_graph: bool = Field(default=True, description="Augment with graph entities/relationships.")
    rewrite: bool = Field(default=True, description="LLM query rewriting before retrieval.")
    rerank: bool = Field(default=True, description="Cross-encoder rerank of candidates.")
    synthesize: bool = Field(
        default=True,
        description="Return an LLM-synthesized answer. False = sources only (no LLM answer call).",
    )
