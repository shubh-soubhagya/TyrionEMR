SHELL := bash
PG_CONTAINER ?= graphgpt-postgres
PG_SUPERUSER ?= postgres
PY := .venv/Scripts/python
ifeq ($(wildcard .venv/bin/python),.venv/bin/python)
PY := .venv/bin/python
endif
-include .env
export

venv:
	python -m venv .venv
install: venv
	$(PY) -m pip install -q -e ".[dev]"
init-db:
	bash setup/init-ai-db.sh $(PG_CONTAINER) $(PG_SUPERUSER)
init-test-db:
	bash setup/init-ai-db-test.sh $(PG_CONTAINER) $(PG_SUPERUSER)
migrate:
	$(PY) -m alembic upgrade head
run:
	$(PY) -m uvicorn app.main:app --reload --port 8004
test:
	$(PY) -m pytest -q
lint:
	$(PY) -m ruff check app tests migrations

openapi:
	$(PY) -m app.cli.export_openapi
check-openapi:
	$(PY) -m app.cli.export_openapi --check
# Needs the whole stack up (`make up` at the repo root) and the databases seeded. Logs in as the demo user through the
# gateway, then reads the /internal routes from a one-off container on nephro-net (they are not routed by the
# gateway). Writes tests/fixtures/captured/. See app/cli/capture_fixtures.py.
capture-fixtures:
	MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps --build \
	  -v "$$(pwd -W 2>/dev/null || pwd)/tests/fixtures/captured:/out" \
	  --entrypoint python ai-svc -m app.cli.capture_fixtures --out /out
reap:
	$(PY) -m app.cli.reap_once
test-unit:
	$(PY) -m pytest -q tests/unit
test-api:
	$(PY) -m pytest -q tests/api tests/db
live-llm:
	RUN_LIVE_LLM=1 $(PY) -m pytest -q -s tests/live

build:
	docker build -t nephro/ai-svc .
up:
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f ai-svc
