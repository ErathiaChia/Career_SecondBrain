"""Root conftest: make the three packages importable under one pytest run.
Packages are `career_history` (era_indexer), `era_mcp` (era_mcp) and `auditor`
(era_auditor); each test tree expects its package directory on sys.path."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for pkg in ("era_indexer", "era_mcp", "era_auditor"):
    p = str(_ROOT / pkg)
    if p not in sys.path:
        sys.path.insert(0, p)
