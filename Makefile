SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend

.PHONY: install dev dev-backend dev-frontend test test-backend e2e lint lint-backend lint-frontend fmt check samples docker clean

install:
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && pnpm install
	cd $(FRONTEND) && pnpm exec playwright install chromium

dev:
	@trap 'kill 0' EXIT; \
	( cd $(BACKEND) && uv run uvicorn app.main:app --reload --port 8000 ) & \
	( cd $(FRONTEND) && PORT=3000 pnpm dev ) & \
	wait

dev-backend:
	cd $(BACKEND) && uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd $(FRONTEND) && PORT=3000 pnpm dev

test-backend:
	cd $(BACKEND) && uv run pytest -q

test: test-backend

e2e:
	cd $(FRONTEND) && pnpm e2e

lint-backend:
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check . && uv run mypy app

lint-frontend:
	cd $(FRONTEND) && pnpm lint && pnpm typecheck && pnpm format:check

lint: lint-backend lint-frontend

fmt:
	cd $(BACKEND) && uv run ruff check --fix . && uv run ruff format .
	cd $(FRONTEND) && pnpm format

check: lint test

samples:
	cd $(BACKEND) && uv run python ../samples/scripts/make_sample_zips.py

docker:
	docker compose up --build

clean:
	rm -rf data workspace $(BACKEND)/.e2e $(FRONTEND)/.e2e $(FRONTEND)/.next
