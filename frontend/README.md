# NephroCare EMR — Angular frontend

Angular 22 (standalone components, signals), SCSS, Vitest. The visual reference is
`../reference/emr-ui.html`; the functional reference is `../reference/assignment.pdf`.

## Run (primary): Docker

The host Node version does not matter. **Never run `node`, `npm`, `npx` or `ng` on the host**:
`node_modules` contains Linux binaries and a host run would corrupt it.

```bash
cd frontend
docker compose up              # app at http://localhost:4200 (hot reload)
```

The first start runs `npm ci` (several minutes on Windows). Later starts skip it as long as
`node_modules` exists.

Everything else goes through the running `web` service:

```bash
docker compose exec web npx ng generate component <name>
docker compose exec web npm install <pkg>
docker compose exec web npx ng build
docker compose exec web npx ng lint
docker compose exec web npx ng test --watch=false     # or: npm run test:ci
docker compose exec web npm run format                # prettier --write
docker compose exec web npm run format:check
```

## Run (alternative): Node installed locally

Requires Node **22.22.3+** or **24.15+** (see `.nvmrc`, `engines` in `package.json`).

```bash
cd frontend
npm ci
npm start
```

Do not mix the two: `node_modules` installed in Docker (Linux) will not work on a Windows host
and the reverse. Delete `node_modules` before switching.

## Environments

`src/environments/environment.ts` is the production default; `environment.development.ts`
replaces it in the development build (`fileReplacements`). The only fields are `production` and
`apiBaseUrl` (`/api` in both).

## How it talks to the gateway

The browser only calls its own origin, `/api/...`. In development the dev server proxies `/api` to the gateway
(`proxy.conf.mjs`, target `GATEWAY_URL`, default `http://host.docker.internal:8080`; the `web` service has the matching
`extra_hosts`). The gateway is the only public door to auth-svc, patient-svc, lab-svc and ai-svc. Open the app as
`http://localhost:4200`: the gateway and auth-svc accept only that origin, and the refresh cookie is `Secure`, which a
browser only accepts for `localhost` or https.

Start the whole system with `make up` at the repo root (and `make seed` once), then `docker compose up -d web` here.

## Authentication

The access token lives in memory only (a signal in `core/auth/auth.service.ts`); nothing is written to
`localStorage` or `sessionStorage`. The refresh token is an HttpOnly cookie that the browser sends to `/api/auth/*` by
itself, so a reload restores the session with one silent `POST /api/auth/refresh` (the app initializer). `authInterceptor`
adds the bearer to `/api` requests only, `refreshInterceptor` turns a 401 `TOKEN_EXPIRED` into one shared refresh and one
retry, `errorInterceptor` turns the error envelope into an `ApiError`. Guards: `authGuard` (every app page) and `guestGuard`
(`/login`, `/signup`). Design and reasons: `docs/decisions.md` D3.

## Where the API types live

`src/app/core/api/`: `endpoints.ts` (every path), `dto/` (exact wire shapes of the four services), `mappers/` (DTO to view
model, the only place the two vocabularies meet), `api-error.ts`, `remote.ts` and `remote-signal.ts` (loading, empty,
error, ok as one union), `form-errors.ts` and `error-messages.ts` (how an error is shown). `src/app/core/data/` holds one
API service per area (`patients`, `chart`, `encounters`, `labs`, `insights`, `ai`). Components never call `HttpClient`.
The browser computes only the lab form's live preview (exact decimals, `core/clinical/lab-preview.ts`, checked against
`lab-svc/tests/vectors/lab_cases.json`), the established-stage mismatch chip, display formatting and form validation.

## Tests, lint and the end-to-end flow

```bash
docker compose exec web npx ng test --watch=false     # unit and component tests (HTTP is faked)
docker compose exec web npx ng lint
docker compose exec web npx prettier --check .
docker compose exec web npx ng build
docker compose --profile tools run --rm flow           # the whole flow in a browser, against the running stack
docker compose --profile tools run --rm flow npx playwright test --config=playwright.flow.config.ts screenshots
```

The unit tests read two files of other services through read-only mounts (`/lab-vectors`, `/ai-examples` in
`compose.yaml`) and fail, not skip, when they are missing. The flow test (`e2e/flow/flow.e2e.ts`) writes records to the dev
database (an encounter, a lab report, an AI summary) with the seeded data; `make seed` does not undo that. The screenshots
land in `../docs/screenshots/`.

## Path aliases

`@core/*`, `@shared/*`, `@features/*`, `@layout/*`, `@env/*` (see `tsconfig.json`).

## Visual parity check (Playwright)

Compares `../reference/emr-ui.html` with the running Angular app at 1440, 1024, 768 and 375 px.
It replaces manual side-by-side checking and is reused by every later phase (add a
`<screen>.parity.ts` under `e2e/parity/`).

```bash
docker compose up -d web                                   # the app must be running
docker compose --profile tools run --rm parity             # runs `npm run parity` in the Playwright image
```

- Output: `docs/parity/<screen>-<width>.png` (left to right: reference, Angular, diff) and
  `docs/parity/report.md` with the pixel-diff percentage per screen and width.
- The `parity` service uses `mcr.microsoft.com/playwright:v1.65.0-noble`. **Its tag must equal the
  installed `@playwright/test` version** (pinned exactly in `package.json`); change both together.
- The Angular app is reached at `http://host.docker.internal:4200` (allowed in `angular.json`
  `serve.options.allowedHosts`); the reference HTML is mounted read-only at `/reference`.
- IBM Plex is served to the reference page from the same npm fonts the app uses, so a missing
  internet connection does not skew the diff.
