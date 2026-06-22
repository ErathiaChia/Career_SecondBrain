"""Configuration from environment variables.

On the NAS everything is injected via Docker env vars — no YAML, no .env file.
"""
from __future__ import annotations

import os


def _require(var: str) -> str:
    val = os.environ.get(var, "").strip()
    if not val:
        raise RuntimeError(f"Required environment variable {var} is not set")
    return val


def database_url() -> str:
    host = os.environ.get("ERA_VAULT_DB_HOST", "postgres")
    port = os.environ.get("ERA_VAULT_DB_PORT", "5432")
    name = os.environ.get("ERA_VAULT_DB_NAME", "era_vault")
    user = os.environ.get("ERA_VAULT_DB_USER", "era")
    password = _require("ERA_VAULT_DB_PASSWORD")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")


def embedding_model() -> str:
    """Query embedding model. MUST match the model the indexer embedded with
    (bge-m3, 1024-dim). Override via EMBEDDING_MODEL in docker-compose."""
    return os.environ.get("EMBEDDING_MODEL", "bge-m3")


def parent_context_enabled() -> bool:
    """When true, /search returns the larger parent chunk as context for each
    matched child ("small-to-big"). Falls back automatically if parent_chunks
    is absent. Disable with PARENT_CONTEXT_ENABLED=0."""
    return os.environ.get("PARENT_CONTEXT_ENABLED", "1") not in ("0", "false", "False")


def rrf_k() -> int:
    """RRF constant k. Higher values dampen the impact of high ranks.
    Typical range 30-100; 60 is a well-studied default."""
    return int(os.environ.get("RRF_K", "60"))


def candidate_pool() -> int:
    """Number of candidates fetched from each retrieval channel (vector + FTS)
    before RRF fusion. Must be >= top_k."""
    return int(os.environ.get("CANDIDATE_POOL", "50"))


def default_top_k() -> int:
    """Default number of results returned by /search when the caller
    does not specify top_k."""
    return int(os.environ.get("DEFAULT_TOP_K", "20"))


def rrf_vector_weight() -> float:
    """Weight applied to the dense-vector channel in RRF fusion. Higher than
    the FTS weight so semantically-similar chunks dominate and lexical-only
    matches only help when the vector signal is weak."""
    return float(os.environ.get("RRF_VECTOR_WEIGHT", "1.0"))


def rrf_fts_weight() -> float:
    """Weight applied to the full-text channel in RRF fusion. Kept below the
    vector weight to stop generic keyword matches from dominating
    natural-language queries."""
    return float(os.environ.get("RRF_FTS_WEIGHT", "0.5"))
