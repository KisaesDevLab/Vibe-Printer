# Vibe Print — developer task runner (Phase 26)
# All targets run with the virtual backend so NO hardware is required.

export VIBE_PRINT_SECRET ?= dev-secret-change-me
export VIBE_PRINT_DATA_DIR ?= ./data

.PHONY: dev test lint typecheck build seed e2e fmt web-build clean

dev: ## Run the full stack against virtual printers
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

seed: ## Load sample printers/formats/templates/data fixtures
	python -m app.seed

test: ## Unit + integration tests
	pytest -q

lint: ## ruff + frontend tsc
	ruff check app tests

fmt: ## Auto-format / fix
	ruff check --fix app tests
	ruff format app tests

typecheck: ## mypy
	mypy app

gen-api: ## Regenerate the TS client types from the backend OpenAPI (P26.4)
	python -m app.openapi_dump > web/openapi.json
	cd web && npm run gen:api

web-build: gen-api ## Build the admin UI into app/static
	cd web && npm install && npm run build

build: web-build ## Multi-arch image (see Dockerfile)
	docker build -t vibe-print:dev .

e2e: ## Playwright UI flows (deferred — see STATUS.md)
	cd web && npm run e2e

clean:
	rm -rf data .pytest_cache .mypy_cache .ruff_cache app/static
