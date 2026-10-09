#!/usr/bin/env bash
# Scheduled project-intelligence run (sync -> extract -> state -> checks -> digest).
#
# Example crontab on the Mac (weekdays 07:30, log to ~/Library/Logs):
#   30 7 * * 1-5 /path/to/era_indexer/scripts/monitor.sh >> ~/Library/Logs/era_monitor.log 2>&1
#
# Environment:
#   ERA_PYTHON            python with era_indexer deps (default: python3)
#   ERA_MONITOR_THRESHOLD attention score for the digest (default: 40)
#   ERA_MONITOR_ARGS      extra args, e.g. "--skip-extract" or "--folder '14. ST-Engg'"
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${ERA_PYTHON:-python3}"
THRESHOLD="${ERA_MONITOR_THRESHOLD:-40}"
LOCK="${TMPDIR:-/tmp}/era_monitor.lock"

if ! mkdir "$LOCK" 2>/dev/null; then
  echo "$(date '+%F %T') monitor already running; skipping"
  exit 0
fi
trap 'rmdir "$LOCK"' EXIT

echo "$(date '+%F %T') monitor start"
# shellcheck disable=SC2086
"$PYTHON" -m career_history.cli monitor --threshold "$THRESHOLD" ${ERA_MONITOR_ARGS:-}
echo "$(date '+%F %T') monitor done"
