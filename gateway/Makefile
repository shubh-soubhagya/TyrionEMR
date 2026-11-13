SHELL := bash
PY := .venv/Scripts/python
ifeq ($(wildcard .venv/bin/python),.venv/bin/python)
PY := .venv/bin/python
endif
# load local settings (gitignored) when present
-include .env
export

# Same digest as auth-svc's Dockerfile. Refresh it deliberately in both places.
PYTHON_IMAGE ?= python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

.PHONY: lock venv install run test test-unit test-api lint fmt routes build up down logs smoke

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

# Host-run: gateway on 8080, no proxy headers (the gateway is the edge), room for 500 UUIDs in ?ids=
run:
	$(PY) -m uvicorn app.main:app --reload --port 8080 --no-proxy-headers --h11-max-incomplete-event-size 32768

test:
	$(PY) -m pytest -q
test-unit:
	$(PY) -m pytest -q tests/unit
test-api:
	$(PY) -m pytest -q tests/api

lint:
	$(PY) -m ruff check app tests && $(PY) -m mypy app
fmt:
	$(PY) -m ruff format app tests && $(PY) -m ruff check --fix app tests

routes:
	$(PY) -m app.cli.print_routes

# ---- container (needs Docker; the network is created by setup/network.sh) ---------------------------------------
build:
	docker build -t nephro/gateway .
up:
	bash setup/network.sh
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f gateway
# End-to-end check of the running gateway against the real services (see setup/smoke-test.sh)
smoke:
	PY=$(PY) bash setup/smoke-test.sh
