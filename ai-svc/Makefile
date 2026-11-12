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
