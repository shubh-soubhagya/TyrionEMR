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

.PHONY: retire-legacy-role retire-legacy-role-plan migrate-local lock venv install keys init-db init-test-db migrate revision seed run test test-unit test-api lint fmt openapi build up down logs

# Regenerate the hash-locked requirements inside the SAME pinned Linux image the Dockerfile uses, so
# platform-specific packages (uvloop, ...) resolve for production, not for the developer's OS.
lock:
	MSYS_NO_PATHCONV=1 docker run --rm -v "$$(pwd -W 2>/dev/null || pwd):/w" -w /w $(PYTHON_IMAGE) sh -c ' \
	  pip install -q pip-tools && \
	  pip-compile -q --generate-hashes --strip-extras --no-header --allow-unsafe -o requirements.lock pyproject.toml && \
	  pip-compile -q --generate-hashes --strip-extras --no-header --allow-unsafe --extra dev -o requirements-dev.lock pyproject.toml && \
	  pip-compile -q --generate-hashes --strip-extras --no-header --allow-unsafe -o requirements-build.lock requirements-build.in'

venv:
	python -m venv .venv
install: venv
	$(PY) -m pip install -q -e ".[dev]"

keys:
	bash setup/generate-keys.sh
init-db:
	bash setup/init-auth-db.sh $(PG_CONTAINER) $(PG_SUPERUSER)
init-test-db:
	bash setup/init-auth-db-test.sh $(PG_CONTAINER) $(PG_SUPERUSER)
# Retires ONLY the legacy role auth_svc (NOLOGIN, no CONNECT; never dropped). Refuses if it still owns anything.
retire-legacy-role-plan:
	bash setup/retire-legacy-role.sh $(PG_CONTAINER) $(PG_SUPERUSER) --plan
retire-legacy-role:
	bash setup/retire-legacy-role.sh $(PG_CONTAINER) $(PG_SUPERUSER)

# Migrations run as the schema-owner role (AUTH_MIGRATION_DATABASE_URL), in a one-off container.
migrate:
	docker compose run --rm migrate
migrate-local:
	$(PY) -m alembic upgrade head
revision:
	$(PY) -m alembic revision -m "$(m)"
seed:
	$(PY) -m app.cli.seed_users --force

run:
	$(PY) -m uvicorn app.main:app --reload --port 8001

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

openapi:
	$(PY) -m app.cli.export_openapi

build:
	docker build -t nephro/auth-svc .
up:
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f auth-svc
