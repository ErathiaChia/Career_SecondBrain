#!/usr/bin/env bash
# One-off ST-Engg vault fact extraction (local Ollama on the Mac), folder by folder,
# rebuilding project state after the high-value folders so results land early.
# Resumable: extract-documents skips files already at the current extractor version,
# so re-running this script continues where it stopped.
#
#   nohup caffeinate -i scripts/extract_all.sh >> ~/Library/Logs/era_extract_all.log 2>&1 &
#
# Does not run discover/sync, so no audio gets queued.
set -uo pipefail

cd "$(dirname "$0")/.."
PYTHON="${ERA_PYTHON:-$HOME/miniconda3/envs/Career_SecondBrain/bin/python}"
LOCK="${TMPDIR:-/tmp}/era_extract_all.lock"

if ! mkdir "$LOCK" 2>/dev/null; then
  echo "$(date '+%F %T') extract_all already running; exiting"
  exit 0
fi
trap 'rmdir "$LOCK"' EXIT

cli() { echo "$(date '+%F %T') >> $*"; "$PYTHON" -m career_history.cli "$@" || echo "$(date '+%F %T') !! failed: $*"; }

rebuild() {
  cli project-state
  cli detect-changes
  cli detect-conflicts
  cli detect-stale
  cli project-similarity
}

cli extract-documents --folder "01 Project"
rebuild

for f in "02 Ops" "00 Agent Inbox" "03 Product" "04 Resources" "05 Admin" "."; do
  cli extract-documents --folder "$f"
done
rebuild

# VisionTech folders (01 Ops, 03 Presales PrepWork, 06 Administrative, 04 Product,
# 05 Project) are skipped: no registered project maps to them, so their facts
# would not reach the project tools. Register VisionTech projects before adding them.

echo "$(date '+%F %T') extract_all done"
