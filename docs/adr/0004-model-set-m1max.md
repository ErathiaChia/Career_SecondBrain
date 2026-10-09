# ADR 0004 — Model set for the M1 Max

**Status:** accepted (2026-10-09)

See `docs/models.md` for the table. Decisions:
- Extraction stays on `qwen3.5:9b-mlx` (validated at ~85 s/file); the output
  budget rises to 6144 tokens to fit the document card.
- Query-time rewrite/Judge/synthesis use one model (`qwen3.5:35b` MoE) so only
  one large model stays loaded; the Judge defaults to the primary.
- Reranking uses a real cross-encoder (Infinity `bge-reranker-v2-m3`) by default;
  `llm_score` is a batched fallback (it previously overflowed `num_ctx` and
  silently disabled the fast path).
- `LLM_NUM_CTX=32768` so a 20k-token evidence context plus answer fits.
- Model tags are declared in exactly two places — `era_indexer/config.yaml`
  (Mac/indexer) and `.env` (era_mcp) — and verified by `make check-models`.
