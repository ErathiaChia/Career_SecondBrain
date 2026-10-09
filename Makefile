# Career_SecondBrain — developer entry points. Override PY to use another env,
# e.g. `make test PY=~/miniconda3/envs/Career_SecondBrain/bin/python`.
PY ?= $(if $(wildcard local/.venv/bin/python),local/.venv/bin/python,python3)

.PHONY: test test-mcp test-indexer test-auditor test-integration eval check-models weekly-dry

test:            ## unit tests for all three packages (no DB, no LLM)
	$(PY) -m pytest

test-mcp:
	cd era_mcp && $(abspath $(PY)) -m pytest tests

test-indexer:
	cd era_indexer && $(abspath $(PY)) -m pytest tests

test-auditor:
	cd era_auditor && $(abspath $(PY)) -m pytest tests

test-integration: ## era_mcp against a throwaway docker Postgres (+ stubbed LLM)
	bash era_mcp/tests/integration/run.sh

eval:            ## scorecard against a running era_mcp (BASE_URL=http://host:8808)
	cd era_mcp && $(abspath $(PY)) -m tools.scorecard --base-url $(BASE_URL) $(EVAL_ARGS)

check-models:    ## verify the configured model tags exist on the runtime Mac
	bash era_indexer/scripts/check_models.sh

weekly-dry:      ## print what the weekly pipeline would do (Phase 1+)
	cd era_indexer && $(abspath $(PY)) -m career_history.cli weekly --dry-run
