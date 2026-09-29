# lingo-agent common commands. `make help` lists them.
#
# Two ways to run:
#   Full stack in Docker:  make env && make up        -> http://localhost:3000
#   Hot-reload dev:        make dev-db, then make dev-backend and make dev-frontend
#                          in two terminals            -> http://localhost:3000

SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV_FILE ?= .env
PNPM ?= pnpm
COMPOSE ?= docker compose

# Same format as `python -m app.credentials.crypto gen-key` ("id:" + urlsafe base64 of
# 32 random bytes), via openssl so it works on a deploy host without Python tooling.
define gen_key
k$$(openssl rand -hex 3):$$(openssl rand -base64 32 | tr '+/' '-_')
endef

##@ Setup

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^##@/ {printf "\n%s\n", substr($$0, 5)} /^[a-z0-9-]+:.*##/ {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: env
env: ## Create .env from .env.example with a fresh encryption key and JWT secret (never overwrites)
	@if [ -e "$(ENV_FILE)" ]; then echo "$(ENV_FILE) already exists; not touching it"; exit 0; fi; \
	umask 077; \
	sed -e "s|^CREDENTIALS_ENCRYPTION_KEYS=.*|CREDENTIALS_ENCRYPTION_KEYS=$(gen_key)|" \
	    -e "s|^JWT_SECRET=.*|JWT_SECRET=$$(openssl rand -hex 32)|" \
	    .env.example > "$(ENV_FILE)"; \
	echo "created $(ENV_FILE) (encryption key and JWT secret generated; keep this file private)"

.PHONY: gen-key
gen-key: ## Print a new credential encryption key entry (for rotation, see rotate-credentials)
	@echo "$(gen_key)"

##@ Docker (full stack)

.PHONY: up
up: ## Build and start postgres + backend + frontend (migrations run on backend start)
	$(COMPOSE) up -d --build

.PHONY: down
down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

.PHONY: build
build: ## Build the backend and frontend images
	$(COMPOSE) build

.PHONY: asr-up
asr-up: ## Start local speech-to-text (speaches, dev only; first start downloads the model)
	$(COMPOSE) --profile asr up -d asr

.PHONY: asr-down
asr-down: ## Stop local speech-to-text (the downloaded model is kept)
	$(COMPOSE) --profile asr stop asr

.PHONY: logs
logs: ## Follow logs of all services
	$(COMPOSE) logs -f

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

.PHONY: rotate-credentials
rotate-credentials: ## Re-encrypt stored API keys with the newest key (runs in the backend container)
	@# 1. make gen-key, put the new entry FIRST in CREDENTIALS_ENCRYPTION_KEYS (keep the old one)
	@# 2. make up (restarts the backend with the new keyring)   3. make rotate-credentials
	@# 4. remove the old entry, make up again. See ADR 0004 §3.
	$(COMPOSE) exec backend python -m app.credentials.rotate

##@ Local development

.PHONY: dev-db
dev-db: ## Start only postgres (host port 5433)
	$(COMPOSE) up -d postgres

.PHONY: migrate
migrate: ## Apply database migrations to DATABASE_URL (from .env)
	cd backend && uv run python -m app.db.migrate

.PHONY: dev-backend
dev-backend: ## Run the API with auto-reload on :8000
	cd backend && uv run uvicorn app.main:app --reload --port 8000

.PHONY: dev-frontend
dev-frontend: ## Run Next.js dev server on :3000 (proxies /api to BACKEND_URL, default :8000)
	@# Next only reads env files inside frontend/, so pass BACKEND_URL from the root .env.
	url=$$(sed -n 's/^BACKEND_URL=//p' "$(ENV_FILE)" 2>/dev/null); \
	cd frontend && BACKEND_URL=$${BACKEND_URL:-$${url:-http://localhost:8000}} $(PNPM) dev

.PHONY: install
install: ## Install backend and frontend dependencies from the lockfiles
	cd backend && uv sync --locked
	cd frontend && $(PNPM) install --frozen-lockfile

##@ Quality

.PHONY: test
test: test-backend test-frontend ## Run backend tests (needs dev-db) and frontend unit tests

.PHONY: test-backend
test-backend: ## pytest against the lingo_test database (needs dev-db)
	cd backend && uv run pytest

.PHONY: test-frontend
test-frontend: ## Vitest
	cd frontend && $(PNPM) test

.PHONY: e2e
e2e: ## Playwright end-to-end tests (needs dev-db; starts its own backend, fake model and frontend)
	cd frontend && $(PNPM) e2e

.PHONY: lint
lint: ## ruff + mypy (backend), eslint + typecheck (frontend)
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app
	cd frontend && $(PNPM) lint && $(PNPM) typecheck

.PHONY: fmt
fmt: ## Format and autofix backend code
	cd backend && uv run ruff format . && uv run ruff check --fix .
