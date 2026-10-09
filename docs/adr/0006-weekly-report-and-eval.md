# ADR 0006 — Weekly change-intelligence report and evaluation gates

**Status:** accepted (2026-10-09)

## Decision
- The weekly run ends with `monitor.build_weekly_report`: the brief's fixed
  sections (NEW FILES / MODIFIED / NEW PROJECT INFORMATION / NEW DECISIONS /
  NEW ACHIEVEMENTS / CHANGED INFORMATION / CONFLICTS / STALE INFORMATION)
  scoped to the window since the previous completed run, plus extended
  sections (deleted files, pipeline counts, eval trend, the scored attention
  digest). Saved as `digests.kind='weekly'` (served by `/digest/latest` and the
  `/ask` digest route with zero LLM calls) and as a markdown file under
  `reports.weekly_dir`; optionally copied into the vault under a subtree the
  indexer ignores.
- Evaluation sets live in git-ignored `local/eval/` (they name clients);
  scrubbed templates in `eval/examples/`; thresholds in `eval/thresholds.json`.
  Suites: retrieval, project, career (the 7 brief questions + more), agent,
  freshness (a probe file written before each run). Hard gates: traceability,
  boundedness, local-first, freshness — a failure is recorded in
  `pipeline_runs.counts.eval` and shown in the report, never silently passed.
