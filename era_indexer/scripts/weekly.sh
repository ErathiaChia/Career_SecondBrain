#!/usr/bin/env bash
# Weekend knowledge pipeline (brief §4): sync -> extract (capped, deadline-bound)
# -> cards/career -> projects/changes/conflicts/state -> eval -> weekly report.
# Launched by launchd (era_indexer/launchd/com.era.weekly.plist) on Saturday
# 01:00, or by hand:
#
#   bash era_indexer/scripts/weekly.sh --manual            # run now (deadline +12h)
#   bash era_indexer/scripts/weekly.sh --dry-run           # print the plan only
#   bash era_indexer/scripts/weekly.sh --catchup           # finish a partial run
#
# Environment (all optional):
#   ERA_REPO       repo root (default: this script's grandparent)
#   ERA_PYTHON     python with era_indexer deps (default: conda env, else python3)
#   ERA_MAX_DOCS   max documents to extract this run (default 1200 ≈ 28h @ 85s)
#   ERA_DEADLINE   hard stop, e.g. "Mon 05:00" (default) or ISO or "+12h"
#   ERA_LOG_DIR    log directory (default ~/Library/Logs/era)
set -uo pipefail

ERA_REPO="${ERA_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ERA_REPO/era_indexer"
if [ -z "${ERA_PYTHON:-}" ]; then
  if [ -x "$HOME/miniconda3/envs/Career_SecondBrain/bin/python" ]; then
    ERA_PYTHON="$HOME/miniconda3/envs/Career_SecondBrain/bin/python"
  else
    ERA_PYTHON="python3"
  fi
fi
[ -f "$ERA_REPO/.env" ] && set -a && . "$ERA_REPO/.env" && set +a

LOG_DIR="${ERA_LOG_DIR:-$HOME/Library/Logs/era}"; mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/weekly-$(date '+%Y%m%d-%H%M').log"
LOCK="${TMPDIR:-/tmp}/era_weekly.lock"

ARGS=()
MODE="weekly"
for a in "$@"; do
  case "$a" in
    --manual)  MODE="manual" ;;
    --catchup) MODE="catchup"; ARGS+=("--catchup") ;;
    --dry-run) ARGS+=("--dry-run") ;;
    *)         ARGS+=("$a") ;;
  esac
done
[ "$MODE" = "manual" ] && ARGS+=("--kind" "manual")
[ -n "${ERA_MAX_DOCS:-}" ] && ARGS+=("--max-docs" "$ERA_MAX_DOCS")
if [ "$MODE" = "manual" ]; then
  ARGS+=("--deadline" "${ERA_DEADLINE:-+12h}")
else
  ARGS+=("--deadline" "${ERA_DEADLINE:-Mon 05:00}")
fi

if ! mkdir "$LOCK" 2>/dev/null; then
  echo "$(date '+%F %T') weekly already running (lock $LOCK); exiting" | tee -a "$LOG"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# Keep the Mac awake for the whole run (idle + display + disk + system sleep).
caffeinate -dims -w $$ &

{
  echo "$(date '+%F %T') weekly start mode=$MODE python=$ERA_PYTHON args=${ARGS[*]}"
  "$ERA_PYTHON" -m career_history.cli weekly "${ARGS[@]}"
  rc=$?
  echo "$(date '+%F %T') weekly exit rc=$rc"
  exit $rc
} 2>&1 | tee -a "$LOG"
