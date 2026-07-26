.PHONY: install format lint typecheck test integration check import-check db-init run compose-up compose-down

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

integration:
	python -m pytest -m integration

format:
	python -m ruff format .

lint:
	python -m ruff check .

typecheck:
	python -m mypy src

check: format lint typecheck test

import-check:
	python -c "from stratweb.main import app; print(app.title)"

db-init:
	python -m stratweb.cli db init --pretty

run:
	python -m uvicorn stratweb.main:app --reload --host 0.0.0.0 --port 8000

compose-up:
	docker compose up --build

compose-down:
	docker compose down
