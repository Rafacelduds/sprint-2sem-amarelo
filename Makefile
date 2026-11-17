.PHONY: install dev test lint typecheck openapi api-client migrate compose-up compose-down

install:
	uv sync --all-packages --all-groups
	npm install

dev:
	docker compose up --build

test:
	uv run pytest
	npm test

lint:
	uv run ruff check .
	npm run lint --workspace @amarelo/web

typecheck:
	uv run pyright

openapi:
	uv run python apps/api/scripts/export_openapi.py

api-client: openapi
	npm run generate:api

migrate:
	uv run --package amarelo-api alembic -c apps/api/alembic.ini upgrade head

compose-up:
	docker compose up --build

compose-down:
	docker compose down

