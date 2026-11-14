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

.PHONY: venv install init-db init-test-db migrate revision seed seed-reset openapi explain run test test-unit test-api lint fmt build up down logs

venv:
	python -m venv .venv
install: venv
	$(PY) -m pip install -q -e ".[dev]"

init-db:
	bash setup/init-patient-db.sh $(PG_CONTAINER) $(PG_SUPERUSER)
init-test-db:
	bash setup/init-patient-db-test.sh $(PG_CONTAINER) $(PG_SUPERUSER)

migrate:
	$(PY) -m alembic upgrade head
revision:
	$(PY) -m alembic revision -m "$(m)"

seed:
	$(PY) -m app.cli.seed_patients
seed-reset:
	$(PY) -m app.cli.seed_patients --reset
openapi:
	$(PY) -m app.cli.export_openapi
# Plans at the LLD 26 scale. ALWAYS against the TEST database: `--reset` truncates every table, and the `-include .env`
# above would otherwise win over a PATIENT_DATABASE_URL set in the shell and point this at the development database.
explain:
	@test -n "$(PATIENT_TEST_DATABASE_URL)" || (echo "PATIENT_TEST_DATABASE_URL is not set"; exit 1)
	@PATIENT_DATABASE_URL="$(PATIENT_TEST_DATABASE_URL)" $(PY) -m app.cli.seed_patients --reset --scale 10000
	@PATIENT_DATABASE_URL="$(PATIENT_TEST_DATABASE_URL)" $(PY) -m app.cli.explain

run:
	$(PY) -m uvicorn app.main:app --reload --port 8002 --h11-max-incomplete-event-size 32768

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
	docker build -t nephro/patient-svc .
up:
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f patient-svc
