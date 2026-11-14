SHELL := bash
PG_CONTAINER ?= graphgpt-postgres
PG_SUPERUSER ?= postgres
NET ?= nephro-net
SERVICES := auth-svc patient-svc lab-svc ai-svc gateway
# one-off container of a service on nephro-net, entrypoint replaced (no dependencies started)
RUN = MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps --entrypoint

.PHONY: network init-dbs keys migrate seed up down logs ps smoke test docs docs-check schema-dump

# 1. The external network every container shares, with the shared Postgres attached under the alias "postgres".
#    Idempotent: creates the network only if missing, attaches the container only if it is not attached.
network:
	@docker network inspect $(NET) >/dev/null 2>&1 || docker network create $(NET)
	@if docker network inspect $(NET) --format '{{range .Containers}}{{.Name}} {{end}}' | tr ' ' '\n' | grep -qx '$(PG_CONTAINER)'; then \
	  echo "$(PG_CONTAINER) is already attached to $(NET)"; \
	else \
	  docker network connect --alias postgres $(NET) $(PG_CONTAINER) && echo "attached $(PG_CONTAINER) to $(NET) as 'postgres'"; \
	fi

# 2. Database roles and databases. These change the shared Postgres container, so they are printed first and run only
#    after you type "yes". They are idempotent. Never runs unattended.
init-dbs:
	@echo "These commands create roles and databases on the shared container $(PG_CONTAINER):"
	@echo "  make -C auth-svc    init-db init-test-db"
	@echo "  make -C patient-svc init-db init-test-db"
	@echo "  make -C lab-svc     init-db init-test-db"
	@echo "  make -C ai-svc      init-db init-test-db"
	@read -r -p "Run them now? Type yes to continue: " a; \
	if [ "$$a" = "yes" ]; then \
	  for s in auth-svc patient-svc lab-svc ai-svc; do make -C $$s init-db init-test-db PG_CONTAINER=$(PG_CONTAINER) PG_SUPERUSER=$(PG_SUPERUSER) || exit 1; done; \
	else echo "Nothing run."; fi

# 3. JWT signing keys of auth-svc (a no-op message if they already exist)
keys:
	@if [ -f auth-svc/setup/keys/jwt_private.pem ]; then echo "auth-svc keys already exist"; else bash auth-svc/setup/generate-keys.sh; fi

# 4. Schema migration. auth-svc migrates with its own schema-owner role in this job; patient-svc, lab-svc and ai-svc
#    run `alembic upgrade head` when they start.
migrate:
	docker compose --profile tools run --rm migrate

# 5. Demo data, in this order: auth demo users, patients, lab catalog and labs. All idempotent.
seed:
	$(RUN) python auth-svc -m app.cli.seed_users --force
	$(RUN) python patient-svc -m app.cli.seed_patients
	$(RUN) python lab-svc -m app.cli.seed_catalog
	$(RUN) python lab-svc -m app.cli.seed_labs

up: network
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f --tail=100
ps:
	docker compose ps

# End-to-end check of the running stack through the gateway (gateway/setup/smoke-test.sh)
smoke:
	make -C gateway smoke

# Every service's own suite, in turn; stops at the first failure. Needs each service's venv (make install) and its
# test database. The gateway needs neither a database nor Docker.
test:
	@for s in $(SERVICES); do echo "=== $$s"; REQUIRE_DB_TESTS=1 make -C $$s test || exit 1; done

# ---- documentation (scripts/docs, standard-library Python only) ----------------------------------------------------
# Re-export each service's OpenAPI file from its routes (no database needed), then rebuild the API index in docs/API.md.
docs:
	@for s in auth-svc patient-svc lab-svc ai-svc; do make -C $$s openapi || exit 1; done
	python scripts/docs/gen_api_docs.py

# Every relative link and anchor in the Markdown files resolves, and docs/API.md matches the OpenAPI files.
docs-check:
	python scripts/docs/check_links.py
	python scripts/docs/gen_api_docs.py --check

# Schema-only dumps of the four databases into docs/db/<service>.sql (needs the Postgres container running).
schema-dump:
	@bash scripts/docs/schema_dump.sh
