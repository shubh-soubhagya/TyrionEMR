SHELL := bash
PG_CONTAINER ?= graphgpt-postgres
PG_SUPERUSER ?= postgres
NET ?= nephro-net
SERVICES := auth-svc patient-svc lab-svc ai-svc gateway
# one-off container of a service on nephro-net, entrypoint replaced (no dependencies started)
RUN = MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps --entrypoint

.PHONY: network init-dbs keys migrate seed up rebuild restart web start down logs ps smoke test docs docs-check schema-dump

# `up`, `rebuild`, `restart` and `logs` accept service names, so one service can be handled alone:
#   make rebuild                      every service         make rebuild ai-svc patient-svc   only those two
#   make logs ai-svc                  one service's logs    make restart gateway
# Services: auth-svc patient-svc lab-svc ai-svc gateway. Make would treat the extra words as targets, so they are turned into
# do-nothing targets here and handed to docker compose through SVC.
ifneq ($(filter $(firstword $(MAKECMDGOALS)),up rebuild restart logs),)
SVC := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
.PHONY: $(SVC)
$(eval $(SVC):;@:)
endif

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

# Starts the backend (gateway, auth, patient, lab, AI). Docker builds an image only when it does not exist yet, so a second
# `make up` is fast and rebuilds nothing. It then waits until every container is healthy and prints the URLs.
up: network
	docker compose up -d $(SVC)
	@make --no-print-directory ps
	@echo ""
	@echo "Backend is running."
	@echo "  API (gateway):  http://localhost:8080/api"
	@echo "  API docs:       http://localhost:8080/docs"
	@echo "Next: make seed (first time only), then make web to start the website."

# After changing code, rebuild the images and restart the changed services, then wait until healthy.
# `make rebuild` rebuilds all of them; `make rebuild ai-svc` or `make rebuild ai-svc patient-svc` rebuilds only those.
rebuild: network
	docker compose up --build -d $(SVC)
	@make --no-print-directory ps

# Restarts containers without rebuilding (for example after a settings change that needs no new image).
restart:
	docker compose restart $(SVC)
	@make --no-print-directory ps

# Starts the website (the Angular dev server in frontend/). The first compile takes up to a minute or two; this waits
# until the page answers, then prints the address.
web:
	cd frontend && docker compose up -d web
	@echo "Waiting for the website to compile (the first start can take a minute or two)..."
	@ok=1; for i in $$(seq 1 90); do \
	  if curl -s -o /dev/null --max-time 3 http://localhost:4200/; then ok=0; break; fi; sleep 3; done; \
	if [ "$$ok" = "0" ]; then \
	  echo ""; echo "Website is ready."; echo "  Open:     http://localhost:4200  (type localhost, not an IP address)"; \
	  echo "  Sign in:  dr.rao@nephrocare.demo  /  Nephro#2026"; \
	else echo "The website did not answer in time. See: cd frontend && docker compose logs web"; exit 1; fi

# Everything: backend, then the website.
start: up web

# Stops the backend containers and the website (the website container is stopped, not removed, so it restarts quickly).
down:
	docker compose down
	cd frontend && docker compose stop web
logs:
	docker compose logs -f --tail=100 $(SVC)

# Waits until every backend container is healthy (up to 3 minutes), then shows only the image and its health.
ps:
	@echo "Waiting for the containers to become healthy (up to 3 minutes)..."
	@n=0; for i in $$(seq 1 60); do \
	  total=$$(docker compose ps --format '{{.Health}}' | grep -c .); \
	  bad=$$(docker compose ps --format '{{.Health}}' | grep -vc '^healthy$$'); \
	  if [ "$$total" -gt 0 ] && [ "$$bad" = "0" ]; then n=1; break; fi; sleep 3; done; \
	printf '%-22s %s\n' IMAGE HEALTH; docker compose ps --format '{{.Image}} {{.Health}}' | sort | awk '{printf "%-22s %s\n", $$1, $$2}'; \
	if [ "$$n" = "1" ]; then echo "All containers are healthy."; else echo "Not everything is healthy yet. Run: make logs"; exit 1; fi

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
