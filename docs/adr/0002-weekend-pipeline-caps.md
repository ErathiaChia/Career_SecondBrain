# ADR 0002 — Weekend knowledge pipeline with hard caps

**Status:** accepted (2026-10-09)

## Context
Full typed extraction costs ~85 s/file on the Mac (~1,700 files ≈ 4 days). The
brief wants expensive work on weekends, incremental processing, and answers that
are fresh by Monday.

## Decision
- One scheduled run, Saturday 01:00 → deadline Monday 05:00 (launchd), via
  `career_history.cli weekly` with `--max-docs` (default 1200 ≈ 28 h) and
  `--deadline` as the hard guard; stages are failure-isolated and resumable.
- Extraction order is **most recently modified first**, so a capped run always
  covers this week's changes before any backlog.
- Never re-extract on extractor-version mismatch during scheduled runs; opt in
  with `extract-documents --upgrade`. New per-document intelligence (cards) is
  backfilled with one cheap call per legacy document.
- Every document gets full typed extraction (no folder tiering) — user decision.
- Weekday runs are retrieval only (optional 02:00 light sync, no LLM).

## Consequences
- Steady state (~300 changed docs) finishes Saturday; bulk imports roll over to
  a second weekend via catch-up mode.
- `pipeline_runs` records every run; `/pipeline/status` tells clients how
  current the knowledge is.
