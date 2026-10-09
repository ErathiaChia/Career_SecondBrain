#!/usr/bin/env bash
# Install the launchd jobs on the runtime Mac.
#   bash era_indexer/launchd/install.sh                 # weekly + catchup + reranker
#   bash era_indexer/launchd/install.sh --with-weekday-sync
#   bash era_indexer/launchd/install.sh --uninstall
#   bash era_indexer/launchd/install.sh --rotate        # truncate launchd logs
# Optional, so the Mac is awake for the Saturday run (needs sudo):
#   sudo pmset repeat wakeorpoweron S 00:55
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ERA_REPO="${ERA_REPO:-$(cd "$HERE/../.." && pwd)}"
ERA_PYTHON="${ERA_PYTHON:-$HOME/miniconda3/envs/Career_SecondBrain/bin/python}"
AGENTS="$HOME/Library/LaunchAgents"; mkdir -p "$AGENTS" "$HOME/Library/Logs/era"
JOBS=(com.era.weekly com.era.catchup com.era.reranker)
case "${1:-}" in
  --with-weekday-sync) JOBS+=(com.era.weekday-sync) ;;
  --uninstall)
    for j in "${JOBS[@]}" com.era.weekday-sync; do
      launchctl bootout "gui/$(id -u)/$j" 2>/dev/null || true; rm -f "$AGENTS/$j.plist"; done
    echo "uninstalled"; exit 0 ;;
  --rotate) : > "$HOME/Library/Logs/era/launchd-weekly.log"; : > "$HOME/Library/Logs/era/launchd-catchup.log"; echo rotated; exit 0 ;;
esac
for j in "${JOBS[@]}"; do
  sed -e "s#__ERA_REPO__#$ERA_REPO#g" -e "s#__ERA_PYTHON__#$ERA_PYTHON#g" -e "s#__HOME__#$HOME#g" \
      "$HERE/$j.plist" > "$AGENTS/$j.plist"
  launchctl bootout "gui/$(id -u)/$j" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$j.plist"
  echo "installed $j"
done
launchctl list | grep com.era || true
