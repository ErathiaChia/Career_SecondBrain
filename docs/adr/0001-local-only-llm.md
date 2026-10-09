# ADR 0001 — Local-only LLMs; cloud is an explicit, off-by-default opt-in

**Status:** accepted (2026-10-09)

## Context
`era_mcp` shipped with `LLM_FALLBACK_ENABLED=1`: when the Mac was unreachable,
`/ask` sent the question *and retrieved vault chunks* to OpenAI. The auditor's
`classify`/`run` always used OpenAI. The organisation's policy forbids sending
sensitive, IP or PII data to cloud services, and the target brief is local-first.

## Decision
- `era_mcp`: the fallback exists only when **both** `CLOUD_LLM_OPTIN=1` and
  `LLM_FALLBACK_ENABLED=1`. Default off. An unreachable Mac makes `/ask` return
  **HTTP 503** (`error=llm_unavailable`) when an answer was requested;
  `synthesize=false` still returns sources. `provider.fallback` reports
  `disabled (policy)`.
- `era_auditor`: the OpenAI-compatible client points at local Ollama
  (`AUDITOR_LLM_BASE_URL`, default `http://localhost:11434/v1`); a non-private
  `base_url` is refused unless `AUDITOR_CLOUD_OPTIN=1`.
- Private data never enters git: registries, reports, logs and the brief live in
  the git-ignored `local/` tree; docs and tests use synthetic names.

## Consequences
- No silent degradation to the cloud; outages are visible.
- Git history before this ADR still contains client names and the repo lives on
  GitHub; that, and any prior cloud use, is raised with Management (user action).
