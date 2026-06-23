#!/usr/bin/env bash
# Spin up a disposable Postgres+pgvector, install era_mcp deps in a throwaway
# venv, and run the end-to-end agent harness against the real schema. Cleans up
# the container on exit. Requires Docker running.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
CONTAINER="era_test_pg"
VENV="/tmp/era_test_venv"

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> Starting pgvector container"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" \
  -e POSTGRES_USER=era -e POSTGRES_PASSWORD=test -e POSTGRES_DB=era_vault \
  -p 55432:5432 pgvector/pgvector:pg16 >/dev/null

echo "==> Preparing venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -r "$REPO_ROOT/era_mcp/requirements.txt"

echo "==> Running harness"
export ERA_VAULT_DB_HOST=127.0.0.1
export ERA_VAULT_DB_PORT=55432
export ERA_VAULT_DB_NAME=era_vault
export ERA_VAULT_DB_USER=era
export ERA_VAULT_DB_PASSWORD=test
export PYTHONPATH="$REPO_ROOT/era_mcp"
"$VENV/bin/python" "$HERE/harness.py"
