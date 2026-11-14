# Frontend

The Angular app of the NephroCare EMR: sign in, a dashboard, a patient list and a patient chart with overview, conditions,
medications and allergies, encounters, laboratory results with trend charts, and an AI summary tab. It talks only to the
gateway and defines no clinical data of its own. Angular 22, standalone components, signals, SCSS, Vitest.

The visual reference is [reference/emr-ui.html](../reference/emr-ui.html). The standing rules for the code are in [CLAUDE.md](../CLAUDE.md).

## Run

Docker is the only supported way. The host Node version is not supported, and `node_modules` holds Linux binaries that a host
run would corrupt. Never run `node`, `npm`, `npx` or `ng` on the host.

Start the whole system first (`make up` and `make seed` at the repo root, see the root [README](../README.md#quick-start)), then:

```bash
cd frontend
docker compose up -d web       # http://localhost:4200, hot reload
```

The first start runs `npm ci` (several minutes on Windows). Everything else goes through the running `web` service:

```bash
docker compose exec web npx ng build
docker compose exec web npx ng lint
docker compose exec web npx ng test --watch=false
docker compose exec web npm run format:check      # npm run format writes
docker compose exec web npm install <pkg>
```

If the dev server is busy, `docker compose run --rm --no-deps web <command>` runs one command in a fresh container.

## How it talks to the gateway

The browser calls only its own origin, `/api/...`. The dev server proxies `/api` to the gateway (`proxy.conf.mjs`, target
`GATEWAY_URL`, default `http://host.docker.internal:8080`). Open the app as `http://localhost:4200`: the gateway and auth-svc
accept only that origin, and the refresh cookie is `Secure`, which a browser accepts only for `localhost` or HTTPS.
`src/environments/` holds `production` and `apiBaseUrl` (`/api`). Every path is in `src/app/core/api/endpoints.ts`.

## Authentication

- The access token lives in memory (a signal in `core/auth/auth.service.ts`). Nothing is written to `localStorage` or
  `sessionStorage`.
- The refresh token is an HttpOnly cookie the browser sends to `/api/auth/*` itself. A reload restores the session with one
  silent `POST /api/auth/refresh` in the app initialiser.
- `authInterceptor` adds the bearer token to `/api` calls only. `refreshInterceptor` turns a `401 TOKEN_EXPIRED` into one
  shared refresh and one retry. `errorInterceptor` turns the error envelope into an `ApiError`.
- `authGuard` protects every app page; `guestGuard` covers `/login` and `/signup`.

## Project structure

```
src/app/
  core/            singletons and pure logic
    api/           endpoints, DTOs, mappers, Remote<T> state, error messages
    auth/          auth service, interceptors, guards
    http/          error interceptor
    data/          one data-access service per area
    clinical/      lab preview (exact decimals), display helpers, AI disclaimer text
    ui/            modal service
  shared/          presentational code
    ui/            reusable components (table below)
    utils/         chart tooltip text and axis maths, labels, password rules
  layout/          app shell, header, sidebar, page header
  features/        container pages: auth, dashboard, patients (list, chart shell, tabs), modals, not-found, dev (UI kit page)
src/styles/        tokens, reset, typography, reference styles copied from the HTML
e2e/flow/          Playwright: the end-to-end flow, tooltip checks, screenshots
```

Path aliases: `@core/*`, `@shared/*`, `@features/*`, `@layout/*`, `@env/*`. The `features/encounters`, `labs` and `ai-summary`
folders are empty: those tabs live in `features/patients/tabs/`.

## Data layer

A feature never calls `HttpClient`. The path from a service response to the screen:

1. `core/data/labs.api.ts` (an `Injectable`) calls the endpoint from `endpoints.ts` and returns an `Observable` of a DTO.
2. `core/api/dto/lab.dto.ts` mirrors the wire shape exactly (snake_case, `readonly`).
3. `core/api/mappers/trend.mapper.ts` turns a DTO into the view model the chart component draws. Mappers are the only place
   the two vocabularies meet.
4. `core/api/remote.ts` wraps the call in `Remote<T>`: `idle | loading | ok | empty | error`, one union instead of boolean flags.
   `toRemote(...)` never errors, so one failing panel cannot break the screen.
5. The container component (for example `kidney-panel.ts`) turns the stream into a signal with `remoteSignal` and renders it
   inside `emr-remote-state`, which draws the loading, empty and error states.

The browser computes only: the lab form's live preview (exact decimals, `core/clinical/lab-preview.ts`, checked against
`lab-svc/tests/vectors/lab_cases.json`), the established-stage mismatch chip, display formatting and form validation. Reference
ranges, flags, CKD categories and trends all come from the services.

## Reusable components

Standalone, OnPush, signal inputs and outputs, no services injected. "Used by" lists the places outside the component's own
folder; `UI kit page` is the dev-only showcase at `/dev/ui-kit`.

| Component | Purpose | Used by |
|---|---|---|
| `button[emr-button]` | Native button or link with variants; blocks clicks while disabled | Forms, modals, pages |
| `emr-icon` | Inline SVG icons from the reference | Sidebar, header, auth, dashboard, chart, modals |
| `emr-avatar` | Initials avatar | Header, patient chart, UI kit page |
| `emr-badge`, `emr-lab-flag` | Status badge; abnormal-value flag with text and arrow, not colour alone | Dashboard, patient list, labs, modals |
| `emr-ckd-stage-badge` | Established CKD stage chip | Patient list, patient chart |
| `emr-remote-state` | Loading, empty and error states around a `Remote<T>` | Dashboard, patient chart, tabs, modals |
| `emr-skeleton`, `emr-spinner`, `emr-empty-state`, `emr-error-state` | The state visuals | `emr-remote-state` and pages |
| `emr-modal`, `emr-modal-shell` | Dialog with focus trap and Escape | Encounter, lab, patient and small modals |
| `emr-toast-container` | Save confirmations (`aria-live`) | App root |
| `emr-tooltip` with `emrTip` | One tooltip for every chart and bar | App shell, charts, dashboard |
| `emr-line-chart` | Chart.js trend chart with reference band, stage lines and flag-coloured points | Overview kidney panel, Labs tab |
| `emr-spark` | Small eGFR sparkline | Patient list |
| `emr-trend-chips` | Direction, change and slope chips | Overview, Labs tab |
| `emr-text-field`, `emr-textarea`, `emr-select`, `emr-date-field`, `emr-checkbox`, `emr-radio-group`, `emr-search-input`, `emr-form-field-error` | Labelled form controls with `aria-describedby` errors | UI kit page only; the forms in `features/modals` use plain labelled inputs with the same styles |
| `emr-data-table`, `emr-pagination`, `emr-tabs`, `emr-panel`, `emr-kpi-strip`, `emr-alert`, `emr-value-with-unit` | Layout and data display | UI kit page only; the pages use the reference markup directly |

The components used only by the UI kit page are built and styled but are not yet adopted by the feature pages.

## Charts

The two lab trend charts (creatinine and eGFR, on the Overview kidney panel and the Labs tab) use Chart.js 4, registered
tree-shaken. A small Chart.js plugin draws the reference band, the dashed eGFR stage lines with their G1 to G5 labels, a
hover crosshair and the last-value label; points are coloured by flag. Tooltip text comes from `shared/utils/chart-tips.ts`
and is shown by the shared tooltip component. The eGFR chart draws the stage bands from lab-svc's `stage_bands`. The list
sparkline is a small inline SVG. Why: [docs/decisions.md](docs/decisions.md#charting-library).

## Screens

| Screen | Route | Screenshot |
|---|---|---|
| Sign in, sign up | `/login`, `/signup` | [sign in](../docs/screenshots/01-sign-in.png) |
| Dashboard: KPIs, needs attention, eGFR categories, abnormal results, follow-ups, drafts | `/dashboard` | [dashboard](../docs/screenshots/02-dashboard.png) |
| Patient list with search, filters, sort, sparklines | `/patients` | [list](../docs/screenshots/03-patient-list-filtered.png) |
| Overview with the kidney panel | `/patients/:id/overview` | [overview](../docs/screenshots/04-overview-kidney-panel.png) |
| Conditions with the stage mismatch | `/patients/:id/conditions` | [conditions](../docs/screenshots/05-conditions-stage-mismatch.png) |
| Medications and allergies | `/patients/:id/meds` | |
| Encounters and the encounter form | `/patients/:id/encounters` | [form](../docs/screenshots/06-encounter-form.png) |
| Labs: latest values, trends, history; add report with live preview | `/patients/:id/labs` | [labs](../docs/screenshots/07-labs-table-and-trends.png), [add report](../docs/screenshots/08-add-lab-report-preview.png), [charts](../docs/screenshots/09-trend-charts.png), [tooltip](../docs/screenshots/15-chart-tooltip.png) |
| AI summary: running, completed, degraded, failed, source chips | `/patients/:id/ai` | [running](../docs/screenshots/10-ai-summary-running.png), [completed](../docs/screenshots/11-ai-summary-completed.png), [degraded](../docs/screenshots/12-ai-summary-degraded.png), [failed](../docs/screenshots/13-ai-summary-failed.png), [source chip](../docs/screenshots/14-ai-source-chip-opens-record.png) |

## Tests

| Suite | Count | Command |
|---|---|---|
| Unit and component tests (Vitest, HTTP faked) | 136 test cases in 26 spec files, counted from the sources | `docker compose exec web npx ng test --watch=false` |
| End to end (Playwright, against the running stack) | The flow, tooltip and screenshot specs in `e2e/flow/` | `docker compose --profile tools run --rm flow` |
| Visual parity against the reference HTML | Pixel diff at 1440, 1024, 768 and 375 px | `docker compose --profile tools run --rm parity` |

Notes:

- On a busy machine a single full `ng test` run can hit Vitest worker start-up timeouts; running by folder
  (`--include="src/app/shared/**/*.spec.ts"`) works.
- The unit tests read two files of other services through read-only mounts (`/lab-vectors`, `/ai-examples` in `compose.yaml`)
  and fail, not skip, when they are missing.
- The flow test writes records to the development database (an encounter, a lab report, an AI summary) on top of the seed.
- The parity harness compares pixels, and the screens now show service seed data instead of the HTML's own list, so the
  numbers differ by data, not by layout; see [docs/ui-inventory.md](docs/ui-inventory.md) section 8.

## Decisions and known limitations

- Decisions and their reasons: [docs/decisions.md](docs/decisions.md). Every screen, state and interaction against the
  reference: [docs/build-checklist.md](docs/build-checklist.md).
- Differences found when the screens were connected to the real services:
  [docs/ui-inventory.md](docs/ui-inventory.md) section 8.
- Chart points are not keyboard-focusable, so the chart tooltip is mouse-only; the data is also in the history table.
- The Angular unit tests do not render the Chart.js canvas (the test DOM has no 2D context).
