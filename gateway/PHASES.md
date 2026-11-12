# gateway — Development Phases

Source: [docs/gateway-HLD-LLD.md](docs/gateway-HLD-LLD.md) (§ numbers below refer to it).
Paths are relative to `gateway/` and follow the code layout in §16.
Build order follows the checklist in §33, grouped into 9 phases. Each phase must be finished, tested and committed before the next starts.
All Python work is tested in-process with fake upstreams (`httpx.MockTransport`) and a fake JWKS; Docker is needed only from Phase 8.

| # | Phase | Checklist steps | Main result |
|---|---|---|---|
| 1 | Skeleton, config and core helpers | 1 | Folder tree, settings, logging, request id, error envelope; ruff and mypy clean |
| 2 | Pure routing and rate-limit logic | 2, 3 | Path safety, route table, policies, token bucket, `InMemoryRateLimiter` |
| 3 | Token verification and JWKS cache | 4 | `verify_access_token`, `JwksCache` with rotation and staleness cap |
| 4 | Header policy and proxy service | 5, 6 | Allow-listed headers, cookie scoping, `Location` rewrite, streaming proxy, 502/503/504 |
| 5 | Pipeline, auth gate and catch-all route | 7 | Ordered pipeline of §5, `/api/**` routing, internal routes blocked, body limits |
| 6 | Edge middleware: CORS and security headers | 8 | Preflight, ACAO on every response (including gateway errors), security headers |
| 7 | Health, readiness, metrics and dev docs | 9 | `/health`, `/ready`, prober, `/metrics` token, `/docs` aggregation |
| 8 | Container image, compose and smoke test | 10, 11 | `make up` healthy, `make smoke` passes against the real auth-svc |
| 9 | Frontend wiring, README and cross-service follow-ups | 12, 13, 14 | Sign-in works from `localhost:4200` through `:8080`; docs and sibling notes committed |

---

## Phase 1 — Skeleton, config and core helpers (§15, §16, §17, §26)

**Goal:** an importable, lint-clean package with every cross-cutting helper the later phases use.

**Work**
- `pyproject.toml` exactly as §15, `.gitignore`, `.dockerignore`, `.env.example` (§17).
- Folder skeleton of §16.1 with empty `__init__.py` files.
- `app/core/config.py` (Settings, CSV helper, `upstream_urls()`, wildcard-origin guard).
- Copy from auth-svc: `logging.py` (verbatim), `context.py`, `middleware.py` (`RequestContextMiddleware`), base of `errors.py` and `metrics.py`.
- `app/core/errors.py` error catalog of §26, including the gateway codes `INVALID_PATH`, `URI_TOO_LONG`, `UPSTREAM_NOT_DEPLOYED`, `GATEWAY_BUSY`.
- `app/domain/clock.py` (`Clock`, `SystemClock`, `FakeClock`).
- `tests/conftest.py` scaffolding (test RSA key, app factory).

**Done when**
- `ruff` and `mypy` pass.
- Settings tests: defaults, CSV parsing, derived `JWKS_URL`, `CORS_ALLOWED_ORIGINS=*` rejected.
- Error envelope test (`test_error_envelope.py`: shape and `request_id`).

---

## Phase 2 — Pure routing and rate-limit logic (§6, §8.1, §9.1, §18, §19, §21)

**Goal:** all decisions that need no I/O, fully unit-tested.

**Work**
- `app/routing/paths.py`: `safe_segments()` (refuse dot segments, encoded `/ . \ NUL %`, empty or backslash segments, non-`pchar`), `route_template()` (ids to `{id}`).
- `app/routing/table.py`: `Route`, `build_routes()`, `PUBLIC_ROUTES` (§18.1).
- `app/routing/resolver.py`: whole-segment match, `/api/internal/**` and unknown prefixes give `404`.
- `app/routing/policies.py`: `ip_policies()`, `user_policies()` (§18.2).
- `app/domain/token_bucket.py` and `app/services/rate_limiter.py`: `RateLimiter` protocol, `InMemoryRateLimiter` with `RL_MAX_KEYS` LRU cap and `Retry-After`.
- `app/cli/print_routes.py`.

**Done when**
- `test_paths`, `test_resolver`, `test_policies`, `test_token_bucket` pass (traversal variants, `/api/encountersX` is 404, burst and refill with `FakeClock`).
- `test_pure_modules_have_no_io_imports` enforces that `routing/` and `domain/` import no FastAPI, Starlette or httpx.

---

## Phase 3 — Token verification and JWKS cache (§7, §20)

**Goal:** the gateway authenticates tokens exactly as auth-svc defines them, and survives key rotation and auth-svc outages.

**Work**
- `app/core/security.py`: `verify_access_token()` copied from auth-svc (RS256 only, `iss`, `aud`, `exp`, `iat`, `sub`, 30 s leeway), `bearer_token()`, `unverified_kid()`, `Claims`. No `require_role`.
- `app/services/jwks_cache.py`: `parse_jwks()` (only RSA, `use=sig`, RS256, ≥ 2048 bits, `kid` equals RFC 7638 thumbprint), `JwksCache` (replace on success, keep on failure, `JWKS_MAX_STALE_S` cap, single-flight unknown-`kid` refetch at most once per 30 s, backoff 2 s to 30 s at startup, 5 min scheduled refresh).
- `app/services/auth_gate.py`: bearer, then `kid`, then key, then verify; `401 TOKEN_EXPIRED` vs `401 UNAUTHENTICATED`.

**Done when**
- `test_security` repeats auth-svc's token cases (alg `none`, HS256 key confusion, wrong `iss`/`aud`, expired, missing claims, unknown `kid`).
- `test_jwks_cache` covers replace vs keep, max stale, single-flight, refetch rate limit, thumbprint rejection.

---

## Phase 4 — Header policy and proxy service (§8.3, §8.4, §9.2–9.4, §22, §23)

**Goal:** forward a request upstream safely and relay the response, mapping every transport failure to the envelope.

**Work**
- `app/services/headers.py`: request allow-list, gateway-set `X-Request-ID`, `X-Forwarded-*`, `Accept-Encoding: identity`; response hop-by-hop, `Server`, `X-Powered-By` and upstream `X-Request-ID` removed; cookie scoping (auth routes only); `rewrite_location()`.
- `app/services/upstreams.py`: one `httpx.AsyncClient` per upstream (pool 100/20, `trust_env=False`, connect 1 s, pool 1 s).
- `app/services/proxy.py`: bounded request buffering, streamed response, `asyncio.timeout` for time-to-headers, one retry for `GET` on connect failure only, non-JSON upstream errors wrapped (ADR-G13), upstream closed in `finally` on client disconnect.
- Errors: `502 UPSTREAM_UNAVAILABLE`, `504 UPSTREAM_TIMEOUT`, `503 GATEWAY_BUSY`.

**Done when**
- `test_headers`, `test_routing`, `test_timeouts`, `test_streaming`, `test_cookies_passthrough` pass.
- A multi-`Set-Cookie` auth response arrives unmerged; the same on another route is dropped.
- POST is never retried.

---

## Phase 5 — Pipeline, auth gate and catch-all route (§5, §19, §25, §27)

**Goal:** one handler that runs the ordered steps of §5 and is the only place the order is defined.

**Work**
- `app/services/pipeline.py` (`GatewayPipeline.handle()`): URL length, path safety, resolve, upstream configured (`503 UPSTREAM_NOT_DEPLOYED`), IP limits, public vs JWT, user limits, body limit, proxy. Whole handler wrapped so any exception becomes `500 INTERNAL_ERROR`.
- `app/api/routes/gateway.py`: catch-all `/api` and `/api/{rest:path}`; `HEAD`, `TRACE`, `CONNECT` give `405`; WebSocket upgrades refused.
- `app/api/deps.py`, `app/main.py` (`create_app()`, `build_state()`, lifespan starting JWKS task).
- Client IP from the socket peer, `TRUST_PROXY_HOPS` honoured (R13).

**Done when**
- `test_auth_gate`, `test_internal_blocked`, `test_body_limit`, `test_rate_limit`, `test_request_id`, `test_no_phi_in_logs` pass.
- Login 6th attempt gives `429` with `Retry-After`; `ai_poll` bucket independent of `user_default`.
- `Authorization` reaches the upstream byte for byte; no identity headers are added.

---

## Phase 6 — Edge middleware: CORS and security headers (§8.5, §8.7, §24, §25)

**Goal:** every response, including gateway-made errors, is readable by the browser and safe to cache-wise.

**Work**
- `app/core/cors.py`: preflight answered with `204` and never forwarded, exact-origin allow-list, credentials, `Vary: Origin`, `Max-Age`, foreign-origin `403 ORIGIN_NOT_ALLOWED` for preflight and unsafe methods, exposed headers.
- `app/core/security_headers.py`: `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `Cross-Origin-Resource-Policy`, `Cache-Control: no-store` only when upstream set none, HSTS behind `HSTS_ENABLED`.
- `app/core/common_setup.py`: fixed middleware order (request context, security headers, metrics, CORS).

**Done when**
- `test_cors`, `test_cors_api` pass.
- A gateway `401`, `429` and `500` all carry `Access-Control-Allow-Origin` for the allowed origin.

---

## Phase 7 — Health, readiness, metrics and dev docs (§10, §27, §30)

**Goal:** the gateway can be operated and observed.

**Work**
- `app/services/health_prober.py`: `/health` probe of each configured upstream every 10 s, `gateway.upstream.health_changed` event.
- `app/api/routes/health.py`: `/health` (self), `/ready` (JWKS loaded and fresh, `READY_REQUIRES` upstreams healthy; per ADR-G11 only auth by default).
- `app/core/metrics.py`: `http_request_duration_seconds` plus gateway metrics of §30.2; `/metrics` protected by `METRICS_TOKEN` when set.
- `app/api/routes/docs.py`: aggregated Swagger UI at `/docs` and `/docs/{upstream}/openapi.json`, only when `DOCS_ENABLED`.
- Access log fields of §10 (`route` template, `upstream_ms`, `user_id`, `rate_limited`); never query strings, headers, cookies or bodies.

**Done when**
- `test_health` passes: ready fails with no keys or stale keys, works while patient, lab or ai are down.
- `/docs` returns `404` when disabled.

---

## Phase 8 — Container image, compose and smoke test (§29, §32)

**Goal:** a runnable image on `nephro-net` and a real end-to-end check.

**Work**
- `Dockerfile` (multi-stage, non-root), `scripts/entrypoint.sh` (exec uvicorn with `--no-proxy-headers`, one worker, `--h11-max-incomplete-event-size 32768`).
- `docker-compose.yml`: external `nephro-net`, publishes `${GATEWAY_PORT:-8080}:8000`, 256 MiB limit, healthcheck.
- `Makefile`: `venv`, `install`, `run`, `test`, `lint`, `routes`, `build`, `up`, `down`, `logs`, `smoke`.
- `setup/network.sh` (idempotent), `setup/smoke-test.sh` (login, refresh cookie, `/api/auth/me`, 401 without token, `/api/internal/...` 404, traversal 400, preflight 204).
- Runbooks of §32 checked against the running container.

**Done when**
- `make up` shows the container healthy and restart takes under 2 s.
- `make smoke` is all PASS against the real auth-svc; the auth-svc README open item (JWKS cache and smoke test) is ticked.
- Gateway starts and serves `/health` with auth-svc stopped.

---

## Phase 9 — Frontend wiring, README and cross-service follow-ups (§14, §28.3, §33 steps 12–14)

**Goal:** close the loop with Angular and leave the siblings aligned.

**Work**
- Frontend (run Node tooling only through Docker, per repo `CLAUDE.md`): `environment.development.ts` `apiBaseUrl` to `http://localhost:8080/api` (R9); `withCredentials: true` on `/api/auth/*` calls.
- `README.md`: layout, first run, smoke test, embedded `print_routes` output, deviations from this LLD, status and open items.
- Cross-service notes in the sibling READMEs: R8 (patient-svc h11 limit 32 KiB), R10 (network name `nephro-net`, alias `postgres`), R14 (`redirect_slashes=False`).
- Resolve open questions §34 or record the chosen defaults.

**Done when**
- Sign-in, silent refresh and sign-out work from `localhost:4200` with mocks off.
- Full suite (unit and API) green; `ruff` and `mypy` clean; README committed.
