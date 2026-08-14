.PHONY: install lock lock-check format format-check lint typecheck test integration corpus-check corpus-ready storage-audit check release-check import-check db-init run compose-up compose-down

install:
	uv sync --frozen --extra dev

lock:
	uv lock

lock-check:
	uv lock --check

test:
	uv run --frozen pytest

integration:
	uv run --frozen pytest -m integration

corpus-check:
	uv run --frozen stratweb corpus validate --manifest corpus/golden-corpus-v1.json --pretty

corpus-ready:
	uv run --frozen stratweb corpus validate --manifest corpus/golden-corpus-v1.json --require-ready --pretty

storage-audit:
	uv run --frozen stratweb storage audit --pretty

format:
	uv run --frozen ruff format src tests scripts

format-check:
	uv run --frozen ruff format --check src tests scripts

lint:
	uv run --frozen ruff check src tests scripts

typecheck:
	uv run --frozen mypy src

check: lock-check format-check lint typecheck test

release-check:
	powershell -ExecutionPolicy Bypass -File scripts/release_check.ps1

import-check:
	uv run --frozen python -c "from stratweb.main import app; print(app.title)"

db-init:
	uv run --frozen python -m stratweb.cli db init --pretty

run:
	uv run --frozen python -m uvicorn stratweb.main:app --reload --host 127.0.0.1 --port 8000

compose-up:
	docker compose up --build

compose-down:
	docker compose down
