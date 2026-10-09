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
    port = os.environ.get("ERA_VAULT_DB_PORT", "15432")
    name = os.environ.get("ERA_VAULT_DB_NAME", "era_vault")
    user = os.environ.get("ERA_VAULT_DB_USER", "era")
    password = _require("ERA_VAULT_DB_PASSWORD")
    # Explicit driver: SQLAlchemy 2.1+ maps bare postgresql:// to psycopg (v3),
    # but requirements.txt ships psycopg2-binary.
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


def ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")


def embedding_model() -> str:
    """Query embedding model. MUST match the model the indexer embedded with
    (qwen3-embedding:0.6b, 1024-dim). Override via EMBEDDING_MODEL in docker-compose."""
    return os.environ.get("EMBEDDING_MODEL", "qwen3-embedding:0.6b")


# --- Query embedding instruction (qwen3-embedding is instruction-tuned) ---
# qwen3-embedding expects the QUERY to be wrapped with a task instruction while
# DOCUMENTS are embedded raw (the indexer embeds raw). This asymmetry is how the
# model was trained and materially affects retrieval quality. Toggle off to A/B
# or when using a non-instruction model (e.g. bge-m3, which does not need it).

def query_instruction_enabled() -> bool:
    return _flag("QUERY_INSTRUCTION_ENABLED", True)


def query_instruction() -> str:
    return os.environ.get(
        "QUERY_INSTRUCTION",
        "Given a search query, retrieve relevant passages from a personal work "
        "knowledge base that answer the query",
    )


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


def per_file_candidate_cap() -> int:
    """Max chunks one file may contribute to each retrieval channel's candidate
    pool. Stops a giant spreadsheet from crowding out every other document."""
    return int(os.environ.get("PER_FILE_CANDIDATE_CAP", "3"))


def vector_exact_search() -> bool:
    """Exact (sequential) cosine search instead of the approximate HNSW index.
    Set VECTOR_EXACT_SEARCH=0 once the index is rebuilt and recall is verified."""
    return _flag("VECTOR_EXACT_SEARCH", True)


def candidate_overfetch() -> int:
    """Each channel fetches candidate_pool * this before the per-file cap trims it."""
    return int(os.environ.get("CANDIDATE_OVERFETCH", "20"))


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


def filename_search_enabled() -> bool:
    """Also match the lexical channel against file_name + folder + file_path (not
    just chunk body), so short queries -- acronyms ("CL89"), customer names, RFP
    numbers -- hit the path they were filed under even when the body never spells
    them out. Disable with FILENAME_SEARCH_ENABLED=0 (e.g. if it costs too much on
    a very large corpus)."""
    return _flag("FILENAME_SEARCH_ENABLED", True)


def short_query_terms() -> int:
    """Queries with at most this many content words (acronyms, customer names)
    weight the lexical channel equal to the vector channel in RRF."""
    return int(os.environ.get("SHORT_QUERY_TERMS", "2"))


def lexical_path_weight() -> float:
    """ts_rank multiplier for a filename/folder/path match relative to a body
    match in the FTS channel. Used only when FILENAME_SEARCH_ENABLED."""
    return float(os.environ.get("LEXICAL_PATH_WEIGHT", "0.5"))


def _flag(var: str, default: bool) -> bool:
    raw = os.environ.get(var, "1" if default else "0").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


# --- LLM provider (Mac M1 Max primary, OpenAI fallback) ---
# The synthesis/query-rewrite LLM runs on the Mac (Ollama or an OpenAI-compatible
# MLX server). era_mcp runs on the NAS and reaches the Mac over the LAN. OpenAI is
# only used as a fallback when the Mac is unreachable AND a key is configured.

def llm_primary_base_url() -> str:
    return os.environ.get("LLM_PRIMARY_BASE_URL", "http://host.docker.internal:11434").rstrip("/")


def llm_primary_kind() -> str:
    """'ollama' (Ollama /api/chat) or 'openai_compat' (/v1/chat/completions,
    e.g. mlx_lm.server / llama.cpp)."""
    return os.environ.get("LLM_PRIMARY_KIND", "ollama").strip().lower()


def llm_primary_model() -> str:
    return os.environ.get("LLM_PRIMARY_MODEL", "qwen3.5:9b-mlx")


def llm_primary_timeout() -> float:
    return float(os.environ.get("LLM_PRIMARY_TIMEOUT", "30"))


def llm_think() -> bool:
    """Ollama ``think`` flag. Off by default: rewrite/rerank/synthesis need direct
    answers, and reasoning tokens eat the num_predict budget."""
    return _flag("LLM_THINK", False)


def llm_num_ctx() -> int:
    """Ollama context window. The default (often 4k) silently truncates the
    llm_score rerank batch and multi-document synthesis prompts."""
    return int(os.environ.get("LLM_NUM_CTX", "16384"))


def llm_keep_alive() -> str:
    """How long Ollama keeps the model loaded after a call (avoids cold reloads)."""
    return os.environ.get("LLM_KEEP_ALIVE", "30m")


def cloud_llm_optin() -> bool:
    """Organisation policy: vault content never leaves the local network unless
    this is explicitly switched on. Off by default; both this and
    LLM_FALLBACK_ENABLED must be set for the OpenAI fallback to exist."""
    return _flag("CLOUD_LLM_OPTIN", False)


def llm_fallback_enabled() -> bool:
    return cloud_llm_optin() and _flag("LLM_FALLBACK_ENABLED", False)


def openai_api_key() -> str:
    # Plain get (never required): unset means the OpenAI fallback is disabled.
    return os.environ.get("OPENAI_API_KEY", "").strip()


def openai_base_url() -> str:
    return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def openai_model() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")


def llm_max_tokens() -> int:
    return int(os.environ.get("LLM_MAX_TOKENS", "1024"))


def llm_temperature() -> float:
    return float(os.environ.get("LLM_TEMPERATURE", "0.1"))


# --- Reranker (cross-encoder over the fused candidate pool) ---

def rerank_enabled() -> bool:
    return _flag("RERANK_ENABLED", True)


def rerank_kind() -> str:
    """'infinity' (Infinity/TEI /rerank server), 'llm_score' (LLM-batched
    scoring, no extra server), or 'none'."""
    return os.environ.get("RERANK_KIND", "llm_score").strip().lower()


def rerank_max_candidates() -> int:
    """How many RRF-ordered candidates get a rerank score (brief §9: 20-50)."""
    return int(os.environ.get("RERANK_MAX_CANDIDATES", "40"))


def llm_rerank_batch() -> int:
    """Candidates per llm_score prompt; small so each call fits num_ctx/max_tokens."""
    return int(os.environ.get("LLM_RERANK_BATCH", "12"))


def llm_rerank_doc_chars() -> int:
    return int(os.environ.get("LLM_RERANK_DOC_CHARS", "400"))


def rerank_base_url() -> str:
    return os.environ.get("RERANK_BASE_URL", "http://host.docker.internal:7997").rstrip("/")


def rerank_model() -> str:
    return os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")


def rerank_timeout() -> float:
    return float(os.environ.get("RERANK_TIMEOUT", "15"))


# --- Query understanding ---

def query_rewrite_enabled() -> bool:
    return _flag("QUERY_REWRITE_ENABLED", True)


def hyde_enabled() -> bool:
    return _flag("HYDE_ENABLED", False)


def query_rewrite_timeout() -> float:
    return float(os.environ.get("QUERY_REWRITE_TIMEOUT", "12"))


def multi_query_enabled() -> bool:
    """Run retrieval for the rewritten query AND each generated sub-query, then
    fuse the candidate pools before reranking. Without this the sub-queries the
    rewriter already produces are discarded. Disable with MULTI_QUERY_ENABLED=0."""
    return _flag("MULTI_QUERY_ENABLED", True)


# --- Adaptive retrieval breadth (simple / moderate / complex) ---
# The rewriter classifies each question's complexity; /ask then sizes how many
# chunks to retrieve+cite to it. Sized for a local ~9B synthesis model -- a
# lookup needs a handful, "everything about X" needs more, but not so many that
# the model loses the thread. Tune the bands via env; disable to use req.top_k.

def adaptive_topk_enabled() -> bool:
    return _flag("ADAPTIVE_TOPK_ENABLED", True)


def topk_for_complexity(complexity: str) -> int:
    bands = {
        "simple": int(os.environ.get("TOPK_SIMPLE", "8")),
        "moderate": int(os.environ.get("TOPK_MODERATE", "20")),
        "complex": int(os.environ.get("TOPK_COMPLEX", "40")),
    }
    return bands.get((complexity or "").strip().lower(), bands["moderate"])


# --- Document-first assembly (Phase C / Step 6) ---
# Instead of returning the top reranked passages scattered across many files,
# group them by document, order documents by their best passage, and emit each
# document's matched passages together in reading order -- so the synthesis model
# sees coherent documents, not isolated paragraphs. Bounded (not "send every
# chunk") to stay sane for a ~9B synthesis model. /ask only; /search is
# unchanged. Toggle DOC_FIRST_ASSEMBLY_ENABLED=0 to A/B against flat ordering.

def doc_first_enabled() -> bool:
    return _flag("DOC_FIRST_ASSEMBLY_ENABLED", True)


def doc_first_max_docs() -> int:
    """Max distinct documents represented in the assembled context."""
    return int(os.environ.get("DOC_FIRST_MAX_DOCS", "8"))


def doc_first_max_parents_per_doc() -> int:
    """Max matched passages kept per document (keeps one big file from eating
    the whole budget)."""
    return int(os.environ.get("DOC_FIRST_MAX_PARENTS_PER_DOC", "3"))


# --- Agentic /ask (router + ReAct Judge loop) ---
# /ask becomes an intelligent agent: a confidence gate decides single-pass vs a
# bounded ReAct Judge loop that drives re-search/re-write and can route to the
# structural-inventory tool. See era_mcp/docs/agentic_mcp_design.md.

def agentic_ask_enabled() -> bool:
    """Master switch for the agentic /ask path. 0 = legacy single-pass /ask."""
    return _flag("AGENTIC_ASK_ENABLED", True)


def llm_judge_model() -> str:
    """Reasoning model for the Judge (and reused for synthesis). Runs on the Mac
    (same endpoint/kind as the primary). Defaults to the primary model so a
    one-model deployment needs no extra setting; override with LLM_JUDGE_MODEL."""
    return os.environ.get("LLM_JUDGE_MODEL", "").strip() or llm_primary_model()


def agent_max_iters() -> int:
    """Max Judge searches before the agent returns a best-effort partial answer."""
    return int(os.environ.get("AGENT_MAX_ITERS", "3"))


def agent_time_budget() -> float:
    """Wall-clock budget (seconds) for a whole agentic /ask run."""
    return float(os.environ.get("AGENT_TIME_BUDGET", "60"))


def strong_rerank_threshold() -> float:
    """Confidence gate (0-1): if the normalized top rerank score is >= this, the
    first pass answers directly; below it, escalate to the Judge loop. Calibrate
    against the scorecard once the cross-encoder reranker is live."""
    return float(os.environ.get("STRONG_RERANK_THRESHOLD", "0.8"))
