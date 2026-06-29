#!/usr/bin/env bash
# Start the cross-encoder reranker (Fix 4) on the Mac via Infinity.
#
# era_mcp's /ask reranks the fused candidate pool with this server when
# RERANK_KIND=infinity. Infinity exposes an OpenAI-style POST /rerank that
# era_mcp/era_mcp/rerank.py::_rerank_infinity already targets. Running a real
# cross-encoder (bge-reranker-v2-m3) is the single biggest retrieval-quality
# lever — far better than the default llm_score backend.
#
# One-time install (in any venv on the Mac):
#     pip install "infinity-emb[all]"
#
# Then:
#     ./tools/run_reranker.sh           # serves on 0.0.0.0:7997
#     PORT=7997 MODEL=BAAI/bge-reranker-v2-m3 DEVICE=auto ./tools/run_reranker.sh
#
# Leave it running (or daemonize it). Keep the Mac awake: caffeinate -di.
#
# Wire era_mcp to it (env on the NAS container / .env), pointing at the Mac:
#     RERANK_KIND=infinity
#     RERANK_BASE_URL=http://<mac-lan-ip>:7997      # e.g. http://192.168.50.x:7997
#     RERANK_MODEL=BAAI/bge-reranker-v2-m3
#
# Verify it is actually being used: POST /ask and check the response's
# "reranked": true and "rerank_backend": {"kind": "infinity", ...}, and that
# chunks carry a "rerank_score".
set -euo pipefail

MODEL="${MODEL:-BAAI/bge-reranker-v2-m3}"
PORT="${PORT:-7997}"
DEVICE="${DEVICE:-auto}"   # auto | mps | cpu  (Apple Silicon: mps if supported, else cpu)

if ! command -v infinity_emb >/dev/null 2>&1; then
  echo "infinity_emb not found. Install it first:" >&2
  echo "    pip install \"infinity-emb[all]\"" >&2
  exit 1
fi

echo "Starting Infinity reranker: model=$MODEL port=$PORT device=$DEVICE"
echo "Set on era_mcp:  RERANK_KIND=infinity  RERANK_BASE_URL=http://<mac-lan-ip>:$PORT"
exec infinity_emb v2 \
  --model-id "$MODEL" \
  --port "$PORT" \
  --device "$DEVICE"
