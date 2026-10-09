"""Weekly evaluation stage: run era_mcp's scorecard suites against the serving
API with the private question sets under local/eval, store the result as
local/eval/runs/<date>.json, and return a summary for pipeline_runs / the
weekly report's EVAL TREND. Never aborts the pipeline."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from career_history import config

console = Console()

SUITES = ("retrieval", "project", "career", "agent", "freshness")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def paths() -> dict[str, Path]:
    cfg = config.get().get("eval") or {}
    root = _repo_root()
    sets_dir = Path(os.path.expanduser(cfg.get("sets_dir") or root / "local" / "eval"))
    runs_dir = Path(os.path.expanduser(cfg.get("runs_dir") or sets_dir / "runs"))
    return {"sets": sets_dir, "runs": runs_dir, "scorecard": root / "era_mcp", "thresholds": root / "eval" / "thresholds.json"}


def available_suites(sets_dir: Path) -> list[str]:
    return [s for s in SUITES if (sets_dir / f"{s}.json").exists()]


def run_weekly_eval(run_id: str | None = None, base_url: str | None = None, timeout_s: int = 3600) -> dict[str, Any]:
    cfg = config.get().get("eval") or {}
    base_url = base_url or os.environ.get("ERA_EVAL_BASE_URL") or cfg.get("base_url") or "http://localhost:8808"
    p = paths()
    suites = available_suites(p["sets"])
    if not suites:
        console.log(f"[yellow]eval: no question sets under {p['sets']} (retrieval.json, career.json, ...); skipping[/yellow]")
        return {"skipped": "no question sets", "sets_dir": str(p["sets"])}
    p["runs"].mkdir(parents=True, exist_ok=True)
    out_path = p["runs"] / f"{datetime.now():%Y-%m-%d_%H%M}.json"
    cmd = [sys.executable, "-m", "tools.scorecard", "--suite", ",".join(suites), "--sets-dir", str(p["sets"]),
           "--base-url", base_url, "--out", str(out_path)]
    if p["thresholds"].exists():
        cmd += ["--thresholds", str(p["thresholds"])]
    if run_id:
        cmd += ["--run-id", run_id]
    env = {**os.environ, "PYTHONPATH": str(p["scorecard"])}
    try:
        proc = subprocess.run(cmd, cwd=p["scorecard"], capture_output=True, text=True, timeout=timeout_s, env=env)
    except subprocess.TimeoutExpired:
        return {"error": f"scorecard timed out after {timeout_s}s", "suites": suites}
    tail = (proc.stdout or "")[-2000:]
    if proc.returncode not in (0, 1):  # 1 = a hard gate failed (recorded, not fatal)
        console.log(f"[red]eval failed rc={proc.returncode}[/red] {proc.stderr[-800:]}")
        return {"error": f"scorecard rc={proc.returncode}", "stderr": proc.stderr[-800:], "suites": suites}
    summary: dict[str, Any] = {"suites": suites, "out": str(out_path), "hard_gates_passed": proc.returncode == 0}
    if out_path.exists():
        try:
            data = json.loads(out_path.read_text())
            summary["scores"] = {k: v.get("score") for k, v in (data.get("suites") or {}).items()}
            summary["hard_gates"] = {k: v.get("hard_gate_passed") for k, v in (data.get("suites") or {}).items()}
        except ValueError:
            pass
    console.log(f"[green]eval:[/green] {summary.get('scores')} (gates ok: {summary['hard_gates_passed']})")
    summary["stdout_tail"] = tail
    return summary
