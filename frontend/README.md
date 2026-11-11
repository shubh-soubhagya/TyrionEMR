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
replaces it in the development build (`fileReplacements`). Fields: `apiBaseUrl`, `useMocks`,
`aiRequestTimeoutMs`.

## Path aliases

`@core/*`, `@shared/*`, `@features/*`, `@layout/*`, `@env/*` (see `tsconfig.json`).
