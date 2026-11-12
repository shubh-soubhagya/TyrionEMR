SHELL := bash
PG_CONTAINER ?= graphgpt-postgres
PG_SUPERUSER ?= postgres
PY := .venv/Scripts/python
ifeq ($(wildcard .venv/bin/python),.venv/bin/python)
PY := .venv/bin/python
endif
# load local settings (gitignored) when present
-include .env
export

PYTHON_IMAGE := $(shell sed -n 's/^ARG PYTHON_IMAGE=//p' Dockerfile)

.PHONY: lock venv install init-db init-test-db migrate revision seed seed-reset openapi explain run test test-unit test-api lint fmt build up down logs

# Regenerate the hash-locked requirements inside the SAME pinned Linux image the Dockerfile uses, so
# platform-specific packages (uvloop, ...) resolve for production, not for the developer's OS.
lock:
	MSYS_NO_PATHCONV=1 docker run --rm -e PIP_DEFAULT_TIMEOUT=120 -e PIP_RETRIES=10 -v "$$(pwd -W 2>/dev/null || pwd):/w" -w /w $(PYTHON_IMAGE) sh -c ' \
	  pip install -q pip-tools && \
	  pip-compile -q --generate-hashes --strip-extras --no-header --allow-unsafe -o requirements.lock pyproject.toml && \
	  pip-compile -q --generate-hashes --strip-extras --no-header --allow-unsafe --extra dev -o requirements-dev.lock pyproject.toml && \
	  pip-compile -q --generate-hashes --strip-extras --no-header --allow-unsafe -o requirements-build.lock requirements-build.in'

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
# Plans at the LLD 26 scale: fill the TEST database (PATIENT_DATABASE_URL=$$PATIENT_TEST_DATABASE_URL), then explain
explain:
	$(PY) -m app.cli.seed_patients --reset --scale 10000 && $(PY) -m app.cli.explain

run:
	$(PY) -m uvicorn app.main:app --reload --port 8002

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
