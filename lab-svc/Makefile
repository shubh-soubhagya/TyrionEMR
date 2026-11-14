SHELL := bash
PG_CONTAINER ?= graphgpt-postgres
PG_SUPERUSER ?= postgres
PY := .venv/Scripts/python
ifeq ($(wildcard .venv/bin/python),.venv/bin/python)
PY := .venv/bin/python
endif
# CI has no virtualenv: run `make <target> PY=python` (a command-line variable overrides the lines above)
# load local settings (gitignored) when present
-include .env
export

PYTHON_IMAGE := $(shell sed -n 's/^ARG PYTHON_IMAGE=//p' Dockerfile)


venv:
	python -m venv .venv
install: venv
	$(PY) -m pip install -q -e ".[dev]"

init-db:
	bash setup/init-lab-db.sh $(PG_CONTAINER) $(PG_SUPERUSER)
init-test-db:
	bash setup/init-lab-db-test.sh $(PG_CONTAINER) $(PG_SUPERUSER)

migrate:
	$(PY) -m alembic upgrade head
revision:
	$(PY) -m alembic revision -m "$(m)"

seed:
	$(PY) -m app.cli.seed_catalog
	$(PY) -m app.cli.seed_labs
seed-reset:
	$(PY) -m app.cli.seed_catalog
	SEED_ALLOW_RESET=true $(PY) -m app.cli.seed_labs --reset
rebuild-status:
	$(PY) -m app.cli.rebuild_status
check-status:
	$(PY) -m app.cli.rebuild_status --check
openapi:
	$(PY) -m app.cli.export_openapi
explain:
	$(PY) -m app.cli.explain

run:
	$(PY) -m uvicorn app.main:app --reload --port 8003

test:
	$(PY) -m pytest -q
test-unit:
	$(PY) -m pytest -q tests/unit
test-api:
	$(PY) -m pytest -q tests/api

lint:
	$(PY) -m ruff check app tests migrations && $(PY) -m mypy app
fmt:
	$(PY) -m ruff format app tests migrations && $(PY) -m ruff check --fix app tests migrations


build:
	docker build -t nephro/lab-svc .
up:
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f lab-svc
