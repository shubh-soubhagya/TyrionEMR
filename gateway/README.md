# gateway

The custom API gateway of the NephroCare EMR: the only component with a published port. Design:
[docs/gateway-HLD-LLD.md](docs/gateway-HLD-LLD.md). Build plan: [PHASES.md](PHASES.md).

Self-contained like `auth-svc/` and `patient-svc/`: own `app/core`, no shared library.

## Network and ports

- Docker network `nephro-net` (external). Postgres alias `postgres` (the gateway has no database).
- Containers `auth-svc` and `patient-svc` listen on 8000 and publish nothing. Only the gateway publishes
  `${GATEWAY_PORT:-8080}`.
- Host-run ports: auth-svc 8001, patient-svc 8002, lab-svc 8003, ai-svc 8004, gateway 8080.
- LLD R10 (standardise on `nephro-net` / alias `postgres`) is already satisfied: auth-svc and patient-svc
  both use them.
- All four upstream URLs are set in `.env.example` and `docker-compose.yml` (`http://<svc>:8000`). A prefix whose URL
  is empty still answers `503 UPSTREAM_NOT_DEPLOYED`; the `Settings` defaults are empty.

## Development

```
make install   # venv + dev dependencies (host Python 3.12)
make test      # in-process tests, no Docker, no network
make lint      # ruff + mypy
make lock      # regenerate hash-locked requirements inside the pinned image (needs Docker)
make up        # setup/network.sh, then build and start the container on nephro-net (publishes :8080)
make smoke     # end-to-end check of the running gateway against the real services (setup/smoke-test.sh)
make down logs build
```

## Deviations from the design document

| # | Design | Here | Why |
|---|---|---|---|
| D1 | LLD §15/§29.1: unhashed `pip install`, wheels stage | **Not done yet:** `make lock` (hash-locked `requirements*.lock`, `--require-hashes`) was skipped by decision, so the image installs from `pyproject.toml` unhashed. Target: `requirements*.lock` with hashes (`make lock` in the pinned image), digest-pinned base image, `--require-hashes`, non-root uid 10001, CI workflow | Same supply-chain rules as auth-svc (D13) and patient-svc |
| D2 | `pydantic-settings>=2.3` | `>=2.7` | `NoDecode` (CSV settings) needs 2.7 |
| D3 | No environment concept | `ENVIRONMENT` (development / test / production) and `app/core/guard.py`; production refuses to start with localhost or `*` CORS, `DOCS_ENABLED`, `METRICS_ENABLED` without `METRICS_TOKEN`, `RATE_LIMIT_ENABLED=false`, `HSTS_ENABLED=false`. New `METRICS_ENABLED`. `docker-compose.prod.yml` | Same pattern as auth-svc D12 and D18 |
| D4 | Route label rebuilt from the path / scope | Label read from `scope["state"]["route"]`, set by the pipeline; literal labels for gateway-owned routes; `preflight` and `origin_rejected` from CORS; otherwise `unmatched`. `/health`, `/ready`, `/metrics` stay out of the histogram but are access-logged | A catch-all route cannot give a useful template; ids must never become labels |
| D5 | LLD §23.3: a non-JSON upstream error becomes the status map's code, `INTERNAL_ERROR` for 5xx | Upstream status is kept. 4xx: code from the status map (413 `PAYLOAD_TOO_LARGE` and 414 `URI_TOO_LONG` added), `details: [{"upstream": n}]`. 5xx: always `UPSTREAM_ERROR`, message "The service returned an unexpected error.", `details: [{"upstream": n, "upstream_status": s}]`. `INTERNAL_ERROR` is reserved for gateway bugs and `NOT_READY` for the gateway's own `/ready` | A 500 from patient-svc is not a bug in the gateway; the two must be told apart in logs and dashboards |
| D6 | LLD §23.2 builds the upstream URL with `httpx.URL(path=..., query=...)` | Same, but `query=` is passed only when the request has one, and `tests/api/test_url_passthrough.py` proves path and query reach the upstream byte for byte (`%7E`, `+`, `%2B`, 500 UUIDs in `ids=`, trailing slash) | The proof found that `query=b""` appends a stray `?` to every request without a query string |
| D9 | LLD §20.1 `verify_access_token` (older code) | auth-svc's CURRENT function: `sub` must be a UUID (auth D23), expiry checked against the injected clock (auth D4). `tests/unit/test_security.py` repeats auth-svc's token cases | The LLD code predates auth-svc's later changes; the two copies must apply identical rules |
| D10 | LLD §25.4 builds the state inside the lifespan | `build_state()` runs in `create_app()`; the lifespan only starts the background tasks and closes the clients | httpx's `ASGITransport` never runs lifespan events, so tests could not inject fake upstreams otherwise |
| D11 | LLD §19.2: trailing slash tolerated, public routes matched on the template | `POST /api/auth/login/` (trailing slash) is not public: public means the exact path of §18.1 | "Exact (method, path). No trailing-slash variants" in the design's own comment |
| D12 | Not specified | `httpx` and `httpcore` loggers are set to WARNING in `configure_logging` | httpx logs `HTTP Request: GET <full url>` at INFO, which would write query strings (patient search text) to the logs |
| D13 | `Clock.mono()` | `Clock.monotonic()` | Clearer name; `FakeClock` moves both readings together |
| D14 | LLD §24: a preflight's `Access-Control-Request-Method` is tested with `in "GET, POST, ..."` (substring) | Exact membership of the allowed-method tuple | The substring test accepts `PO`, `GET, P` and the empty string |
| D15 | LLD §27.4: Swagger UI with an Authorize button | Swagger UI assets come from the jsDelivr CDN (dev-only page); the aggregated spec gets a `bearerAuth` scheme injected, because auth-svc and patient-svc read the header themselves and declare none | Without a scheme Swagger shows no Authorize button and "Try it out" would always get `401` |
| D16 | LLD §30.2 lists `kind` values `stream` and `non_json` | Both are counted in `gateway_upstream_errors_total` | Listed in the design but not wired in its code |
| D17 | LLD §8.3: the request-header allow-list has no `X-Mock-Scenario` | `x-mock-scenario` is forwarded **only** when `ENVIRONMENT` is not `production` **and** the route's upstream is `ai`; elsewhere it is dropped like any unknown header. CORS lists `X-Mock-Scenario` in `Access-Control-Allow-Headers` only outside production | The AI tab's demo options (ai-svc LLD B7.5, `LLM_PROVIDER=mock`, `APP_ENV=dev`) could never reach ai-svc. Tests: `tests/api/test_mock_scenario.py` |
| D18 | LLD §29: compose for the gateway only | `docker-compose.yml` sets `AUTH_SVC_URL`, `PATIENT_SVC_URL`, `LAB_SVC_URL`, `AI_SVC_URL` to `http://<svc>:8000`, `DOCS_ENABLED: "true"`, container name `gateway`, `read_only`, 256 MiB, `stop_grace_period: 15s`; `.env` is optional (`required: false`) | Every value has a default, so a fresh checkout starts; the repo-root compose includes this file |

## Status and open items

- Image built and running on `nephro-net` (`make up`, healthy, no `.env` needed); `make test` 457 passed, `make lint` clean.
- `make smoke` (19 checks) first ran against the running auth-svc and lab-svc only: the auth, CORS, routing and path-safety
  checks passed. patient-svc and ai-svc were not running, so those two 200 checks returned 502 as they should. The full
  PASS run against all four services is recorded by the repo-root `make smoke` (phase A5).
- Observed on a busy Docker Desktop host: DNS lookups inside the container occasionally take a few hundred ms and, with
  `UPSTREAM_CONNECT_TIMEOUT_S=1`, an occasional first request answers `502 UPSTREAM_UNAVAILABLE`. Raise the timeout in `.env` if
  it shows up on your machine; the default follows the LLD.
- Open: `make lock` (D1). Hash-locked requirements and `--require-hashes` in the Dockerfile.
