#!/usr/bin/env bash
# Verify every model tag the system is configured to use actually exists on the
# runtime Mac (Ollama) and that the Infinity reranker answers. Run before a
# weekly pipeline run and after editing config.yaml / .env.
#
#   bash era_indexer/scripts/check_models.sh            # uses ../.env + config.yaml
#   OLLAMA_URL=http://mac:11434 RERANK_URL=http://mac:7997 bash .../check_models.sh
set -uo pipefail
cd "$(dirname "$0")/../.."
[ -f .env ] && set -a && . ./.env && set +a
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
RERANK_URL="${RERANK_URL:-http://localhost:7997}"
CFG="era_indexer/config.yaml"; [ -f "$CFG" ] || CFG="era_indexer/config.yaml.example"

yaml_get() { grep -E "^\s*$1:" "$CFG" | head -1 | sed -E 's/^[^:]+:\s*"?([^"#]+)"?.*$/\1/' | xargs; }
want=()
want+=("$(yaml_get graph_extraction_model)")
want+=("${LLM_PRIMARY_MODEL:-qwen3.5:35b}")
[ -n "${LLM_JUDGE_MODEL:-}" ] && want+=("$LLM_JUDGE_MODEL")
blurb="$(yaml_get contextual_blurb_model)"; [ -n "$blurb" ] && want+=("$blurb")

have="$(curl -sf "$OLLAMA_URL/api/tags" | python3 -c 'import json,sys; print("\n".join(m["name"] for m in json.load(sys.stdin).get("models",[])))' 2>/dev/null)"
if [ -z "$have" ]; then echo "FAIL: Ollama not reachable at $OLLAMA_URL"; exit 1; fi
rc=0
for m in "${want[@]}"; do
  [ -z "$m" ] && continue
  if echo "$have" | grep -qx "$m" || echo "$have" | grep -qx "$m:latest"; then echo "ok   $m"; else echo "MISSING $m  (ollama pull $m)"; rc=1; fi
done
# Embedding model lives on the NAS Ollama (optional check).
if [ -n "${NAS_HOST:-}" ]; then
  emb="${EMBEDDING_MODEL:-qwen3-embedding:0.6b}"
  if curl -sf "http://$NAS_HOST:11434/api/tags" | grep -q "\"$emb" ; then echo "ok   $emb (NAS)"; else echo "WARN $emb not found on NAS Ollama ($NAS_HOST)"; fi
fi
if [ "${RERANK_KIND:-infinity}" = "infinity" ]; then
  if curl -sf "$RERANK_URL/health" >/dev/null || curl -sf "$RERANK_URL/models" >/dev/null; then echo "ok   infinity reranker at $RERANK_URL"; else echo "MISSING infinity reranker at $RERANK_URL (era_mcp/tools/run_reranker.sh)"; rc=1; fi
fi
exit $rc
