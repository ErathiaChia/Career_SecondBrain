# ADR 0003 — Evaluation sets and private registries live under untracked `local/`

**Status:** accepted (2026-10-09)

## Context
Real retrieval/career questions and the auditor registries name clients and
projects. The repo is on GitHub.

## Decision
- `local/` is git-ignored and holds: `local/auditor/rules/*` (registries),
  `local/auditor/reports/*`, `local/eval/*.json` (question sets) and
  `local/eval/runs/<date>.json` (scorecard outputs), `local/V4_Agent.md`.
- Committed: scrubbed `*.example.*` templates and `era_auditor/tests/fixtures/`
  (synthetic names) so unit tests never touch real data.
- `local/tools/scrub_names.py` + `local/scrub_map.json` keep the real→synthetic
  mapping stable; it is itself private.

## Consequences
- Tests pass on any machine without the vault; eval needs the runtime Mac/NAS.
