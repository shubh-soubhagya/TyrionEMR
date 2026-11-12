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
| D9 | LLD §20.1 `verify_access_token` (older code) | auth-svc's CURRENT function: `sub` must be a UUID (auth D23), expiry checked against the injected clock (auth D4). `tests/unit/test_security.py` repeats auth-svc's token cases | The LLD code predates auth-svc's later changes; the two copies must apply identical rules |
| D11 | LLD §19.2: trailing slash tolerated, public routes matched on the template | `POST /api/auth/login/` (trailing slash) is not public: public means the exact path of §18.1 | "Exact (method, path). No trailing-slash variants" in the design's own comment |
| D13 | `Clock.mono()` | `Clock.monotonic()` | Clearer name; `FakeClock` moves both readings together |
