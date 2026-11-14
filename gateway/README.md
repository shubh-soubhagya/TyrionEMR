# gateway

The single entry point of the NephroCare EMR and the only component with a published port. The gateway checks every request
before it reaches a service: it refuses unsafe paths, applies rate limits, verifies the access token, enforces size limits,
and forwards the call to the owning service with a request id. It has no business logic and no database.

It owns: CORS, path safety, rate limiting, token verification at the edge, routing by prefix, request ids, header filtering,
the mapping of upstream failures to the error envelope, the development Swagger page.
It does not own: any data, any clinical rule, or token issue (auth-svc).

## Endpoints

Gateway-owned routes. Every `/api/**` route belongs to a service: [docs/API.md](../docs/API.md).

| Method | Path | Purpose |
|---|---|---|
| any | `/api/**` | Routed by the first segment after `/api` (table below). `/api/internal/**` is never routed and answers `404` |
| GET | `/health` | Liveness, always `200` while the process runs |
| GET | `/ready` | Readiness: the upstreams named in `READY_REQUIRES` (default `auth`) are healthy (`503 NOT_READY` otherwise) |
| GET | `/metrics` | Prometheus metrics; protected by `METRICS_TOKEN` in production |
| GET | `/docs`, `/docs/{upstream}/openapi.json` | Aggregated Swagger UI, development only (`DOCS_ENABLED`) |

### Route table

The table is code (`app/routing/table.py`), reviewed like a contract. Only URLs and timeouts are configurable.

| Prefix | Service | Timeout | Body limit | Notes |
|---|---|---|---|---|
| `/api/auth` | auth-svc | 5 s | 16 KiB | Forwards the refresh cookie and passes `Set-Cookie` back |
| `/api/patients` | patient-svc | 5 s | 1 MiB | |
| `/api/encounters` | patient-svc | 5 s | 1 MiB | |
| `/api/labs` | lab-svc | 5 s | 1 MiB | |
| `/api/ai` | ai-svc | 5 s | 1 MiB | `X-Mock-Scenario` forwarded outside production (D17) |
| `/api/insights` | ai-svc | 10 s | 1 MiB | |

Public routes (no token): `POST /api/auth/login`, `signup`, `refresh` and `logout`, matched on the exact path (no trailing
slash). Everything else needs a bearer token.

### Request pipeline

`app/services/pipeline.py` defines the order in one method; cheap rejections come first and the network call last.

1. URL length (24,576 bytes at most, else `414`).
2. Path safety: encoded dots, slashes, backslashes and NUL are refused, not normalised (`400 INVALID_PATH`).
3. Resolve the route by prefix (unknown prefix and `/api/internal/**` give `404`).
4. Check the upstream is configured (`503 UPSTREAM_NOT_DEPLOYED` otherwise).
5. Per-IP rate limits.
6. Public route? Skip steps 7 and 8.
7. Verify the RS256 token against the cached JWKS.
8. Per-user rate limits.
9. Read the body within the limit (`413` before reading when `Content-Length` is too large; chunked bodies are counted).
10. Forward with an allow-listed set of headers, `X-Request-ID` and the client IP, and map the answer back.

Rate-limit policies and numbers: [docs/API.md](../docs/API.md#conventions). CORS allows the origins in
`CORS_ALLOWED_ORIGINS` (default `http://localhost:4200`).

## Data

None. The gateway keeps no database. Rate-limit buckets live in memory (per process, at most 100,000 keys).

## Dependencies

| Dependency | Used for | If it fails |
|---|---|---|
| auth-svc `/.well-known/jwks.json` | Token verification (`app/services/jwks_cache.py`: 5 min cache, refetch on an unknown key id at most every 30 s, up to 24 h stale) | Cached keys keep working; unknown key ids fail until it returns |
| auth-svc, patient-svc, lab-svc, ai-svc | Forwarding. Connect timeout 1 s, per-route read timeouts above | `502 UPSTREAM_UNAVAILABLE`, `504 UPSTREAM_TIMEOUT`, or the upstream's own 5xx as `UPSTREAM_ERROR` (D5). A background probe records upstream health for `/ready` |

## Run

As part of the stack: see the root [README](../README.md#quick-start). Alone, for development (Python 3.12):

```bash
make install   # venv and dev dependencies
make test      # in-process tests, no Docker and no network
make lint      # ruff and mypy
make up        # setup/network.sh, then build and start the container on nephro-net (publishes :8080)
make smoke     # end-to-end check against the running services (setup/smoke-test.sh, 19 checks)
make down logs build
```

Network: Docker network `nephro-net` (external). Containers listen on 8000 and publish nothing; only the gateway publishes
`${GATEWAY_PORT:-8080}`. Host-run ports: auth-svc 8001, patient-svc 8002, lab-svc 8003, ai-svc 8004, gateway 8080. The four
upstream URLs are set in `.env.example` and `docker-compose.yml` (`http://<service>:8000`); a prefix whose URL is empty
answers `503 UPSTREAM_NOT_DEPLOYED`.

## Configuration

Service-specific settings. The full list is in [.env.example](.env.example); defaults are in `app/core/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_SVC_URL`, `PATIENT_SVC_URL`, `LAB_SVC_URL`, `AI_SVC_URL` | `http://<service>:8000` in compose | Upstream base URLs |
| `ENVIRONMENT` | `development` | `production` turns on the startup guard (D3) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:4200` | Allowed browser origins; `*` is refused |
| `UPSTREAM_CONNECT_TIMEOUT_S` / `UPSTREAM_DEFAULT_TIMEOUT_S` / `INSIGHTS_TIMEOUT_S` | `1` / `5` / `10` | Upstream timeouts |
| `MAX_BODY_BYTES` / `MAX_AUTH_BODY_BYTES` / `MAX_URL_BYTES` | `1048576` / `16384` / `24576` | Size limits |
| `RL_*` | see [API.md](../docs/API.md#conventions) | Rate-limit rates and bursts per policy |
| `DOCS_ENABLED` | `false` (`true` in compose) | Serve the aggregated Swagger UI |
| `METRICS_ENABLED`, `METRICS_TOKEN` | | `/metrics`; production needs the token |

## Tests

```bash
make test       # in-process, no Docker; upstreams are faked
make lint
make smoke      # the running stack
```

Last recorded full run: 457 passed; the smoke test passes 19 of 19. The tests cover path safety, route resolution, header
handling, the auth gate, rate limits, CORS, URL pass-through byte for byte, error mapping, the production guard and
log redaction.

## Design and deviations

Design: [docs/gateway-HLD-LLD.md](docs/gateway-HLD-LLD.md). Build plan (kept as a record): [docs/PHASES.md](docs/PHASES.md).
The row numbers skip D7 and D8, which were never used.

| # | Design | Here | Why |
|---|---|---|---|
| D1 | LLD §15/§29.1: unhashed `pip install`, wheels stage | The image installs from `pyproject.toml` with version floors and no hashes, by decision | Kept simple; the gateway has seven direct dependencies and no database |
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

## Known limitations

- Rate limits are in memory and per process; several gateway replicas would each keep their own buckets.
- The image installs from `pyproject.toml` without hash locking, by decision (D1), like every other service.
- No CI workflow for the gateway; only auth-svc has one.
- On a busy Docker Desktop host, a first request can occasionally answer `502 UPSTREAM_UNAVAILABLE` because DNS lookups
  exceed the 1 s connect timeout. Raise `UPSTREAM_CONNECT_TIMEOUT_S` in `.env` if it shows up.
