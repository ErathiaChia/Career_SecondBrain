# Evaluation

Question sets are private (they name clients) and live in `local/eval/`
(git-ignored). Scrubbed templates are here under `examples/`; pass criteria in
`thresholds.json` (brief §23).

| Suite | File | Measures |
|---|---|---|
| retrieval | `local/eval/retrieval.json` | hit@5 / hit@10 / MRR of the expected document |
| project | `local/eval/project.json` | project fields, entities, facts, conflicts, latest version, stale, state, attribution |
| career | `local/eval/career.json` | the 7 brief questions + yours: project hit, fact recall, evidence (min citations), **traceability** (every FACT cited, every citation resolves to a file), **boundedness** |
| agent | `local/eval/agent.json` | fast-path p50 latency and LLM calls, investigate within budget, digest with 0 LLM calls, honest `sufficient=false`, **local-first** (`provider.fallback` disabled) |
| freshness | `local/eval/freshness.json` | the probe file written before the run is retrievable after it |

Run by hand (server must be up):

```bash
cd era_mcp && python -m tools.scorecard --suite all --sets-dir ../local/eval --base-url http://nas:8808 \
    --thresholds ../eval/thresholds.json --out ../local/eval/runs/$(date +%F).json --baseline ../local/eval/runs/latest.json
```

The weekly pipeline runs the same command as its `eval` stage and puts the
per-suite scores into `pipeline_runs.counts.eval` and the weekly report's
EVAL TREND section. Hard-gate failures make the scorecard exit 1; the pipeline
records that and continues.
