# Models — one source of truth per host

| Role | Tag | Host | Set in | Notes |
|---|---|---|---|---|
| Document extraction (facts + card JSON) | `qwen3.5:9b-mlx` | Mac Ollama | `era_indexer/config.yaml` `models.graph_extraction_model` | `think=false`, `num_ctx 16384`, `num_predict 6144`, ~85 s/file |
| Query rewrite, Judge, synthesis | `qwen3.5:35b` (MoE, ~3B active) | Mac Ollama | `.env` `LLM_PRIMARY_MODEL` (Judge defaults to it) | `LLM_NUM_CTX 32768`, `keep_alive 24h`. The brief's "Qwen 27B" maps here; a dense 27–31B is 2–3× slower on M1 Max |
| Embeddings | `qwen3-embedding:0.6b` (1024-d) | NAS Ollama | `.env` `EMBEDDING_MODEL` + indexer `models.embedding_model` | Changing it means re-embedding everything + a vector(N) migration |
| Reranker | `BAAI/bge-reranker-v2-m3` via Infinity | Mac :7997 | `.env` `RERANK_KIND=infinity` | `era_mcp/tools/run_reranker.sh`; fallback `llm_score` batches 12 docs/call |
| Transcription | `mlx-community/whisper-large-v3-mlx` | Mac | `era_indexer/config.yaml` | unchanged |
| Image captions (optional) | `qwen3-vl:8b` | Mac Ollama | `era_indexer/config.yaml` `document_images` | off by default |

Check that every configured tag exists: `make check-models` (runs
`era_indexer/scripts/check_models.sh`, also part of the weekly preflight).

Cloud models are **off by policy** (`CLOUD_LLM_OPTIN=0`, `AUDITOR_CLOUD_OPTIN=0`);
see `docs/adr/0001-local-only-llm.md`.
