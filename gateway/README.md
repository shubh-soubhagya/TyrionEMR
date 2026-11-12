# gateway

The custom API gateway of the NephroCare EMR: the only component with a published port. Design:
[docs/gateway-HLD-LLD.md](docs/gateway-HLD-LLD.md). Build plan: [PHASES.md](PHASES.md).

Self-contained like `auth-svc/` and `patient-svc/`: own `app/core`, no shared library.

## Network and ports

- Docker network `nephro-net` (external). Postgres alias `postgres` (the gateway has no database).
- Containers `auth-svc` and `patient-svc` listen on 8000 and publish nothing. Only the gateway publishes
  `${GATEWAY_PORT:-8080}`.
- Host-run ports: auth-svc 8001, patient-svc 8002, gateway 8080.
- LLD R10 (standardise on `nephro-net` / alias `postgres`) is already satisfied: auth-svc and patient-svc
  both use them.
- `LAB_SVC_URL` and `AI_SVC_URL` are empty everywhere: those prefixes answer `503 UPSTREAM_NOT_DEPLOYED`.
  `PATIENT_SVC_URL` defaults to empty in `Settings`; `.env.example` and `docker-compose.yml` set it.

## Development

```
make install   # venv + dev dependencies (host Python 3.12)
make test      # in-process tests, no Docker, no network
make lint      # ruff + mypy
make lock      # regenerate hash-locked requirements inside the pinned image (needs Docker)
```

## Deviations from the design document

| # | Design | Here | Why |
|---|---|---|---|
| D1 | LLD §15/§29.1: unhashed `pip install`, wheels stage | `requirements*.lock` with hashes (`make lock` in the pinned image), digest-pinned base image, `--require-hashes`, non-root uid 10001, CI workflow | Same supply-chain rules as auth-svc (D13) and patient-svc |
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
