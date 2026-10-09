#!/usr/bin/env bash
# Live view of extract_all.sh progress: files still waiting per folder, refreshed every minute.
#   scripts/extract_progress.sh        (Ctrl+C to stop watching; extraction keeps running)
cd "$(dirname "$0")/.."
PYTHON="${ERA_PYTHON:-$HOME/miniconda3/envs/Career_SecondBrain/bin/python}"
while true; do
  clear
  echo "Extraction progress  $(date '+%F %T')"
  if screen -ls 2>/dev/null | grep -q era_extract; then echo "Status: RUNNING"; else echo "Status: NOT RUNNING"; fi
  echo
  "$PYTHON" - <<'EOF'
import collections
from career_history import envfile, config, db, graph
envfile.load(); config.load("config.yaml")
skip = {".venv", "01 Ops", "03 Presales PrepWork", "06 Administrative", "04 Product", "05 Project"}
docs = db.documents_for_extraction(folder=None, limit=None, extractor_version=graph.DOC_EXTRACTOR_VERSION, force=False, max_chars=100)
left = collections.Counter(d["folder"] for d in docs if d["folder"] not in skip)
for folder, n in left.most_common():
    print(f"  {folder:<20} {n:>5} files left")
print(f"\n  Total left: {sum(left.values())} files (~{sum(left.values()) * 85 / 3600:.0f}h at the current pace)")
EOF
  echo
  echo "Last log lines:"
  tail -3 ~/Library/Logs/era_extract_all.log
  sleep 60
done
