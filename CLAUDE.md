# Nephro EMR Frontend — Standing Rules for AI Coding Agents

> Put this file at the repo root. Claude Code reads `CLAUDE.md` automatically.
> For Cursor, copy it to `.cursor/rules/project.mdc`. For other agents, use `AGENTS.md`.
> These rules apply to EVERY task in this repo. The phase prompts in `PROMPTS.md` build on them.

## 1. What we are building
The Angular frontend of a **General Nephrology EMR**. It covers patient management, outpatient encounters, lab results with kidney-function monitoring, and an AI clinical summary.

- **Visual source of truth:** `reference/emr-ui.html`. The Angular app must match it exactly.
- **Functional source of truth:** `reference/assignment.pdf` (sections 2–4).
- **Backend:** Python FastAPI microservices behind a custom API gateway. The frontend talks ONLY to the gateway, through `environment.apiBaseUrl`. It never calls an LLM provider directly.
- **Data:** synthetic only. Never use real names that look like real patients, real MRNs or real PHI.

## 2. Priority order when rules conflict
1. Patient safety and honesty: never fabricate clinical data, and always label AI content.
2. The assignment's functional requirements.
3. Visual fidelity to the reference HTML.
4. Code quality and architecture rules below.
5. Speed.

If the HTML and the assignment disagree, follow the assignment for **behavior** and the HTML for **look**. Log each conflict in `docs/ui-inventory.md` under "Conflicts".

## 3. Visual fidelity rules (non-negotiable)
- Copy exact CSS values from the HTML: colors, font families and weights, sizes, line heights, spacing, radii, shadows, transitions, breakpoints. Do not round, "modernize" or "improve" them.
- All tokens live in `src/styles/_tokens.scss` as CSS custom properties. Components reference tokens and never hard-code a color, spacing or font value.
- Same fonts, same icon set, same copy text, same hover, focus, active and disabled states.
- Do not add a UI kit (Angular Material, PrimeNG, Bootstrap, Tailwind) unless the HTML already uses it.
- Component styles are scoped SCSS. Global styles are limited to reset, tokens, typography, and the few utility classes the HTML genuinely uses globally.
- Verify parity at 1440px, 1024px, 768px and 375px wide.
- Any screen the HTML lacks must be designed ONLY from the HTML's existing visual language: reuse its cards, tables, buttons, badges and spacing scale.

## 4. Angular conventions
- Use the latest stable Angular that supports the installed Node version. Use whatever change-detection setup the CLI generates by default; if the default is zoneless, keep it zoneless.
- Standalone components only. No NgModules.
- `ChangeDetectionStrategy.OnPush` on every component.
- Use `inject()` instead of constructor injection.
- Use signal-based `input()`, `output()` and `model()`. Use `computed()` for derived state, and `effect()` only for side effects you cannot express any other way.
- Use built-in control flow (`@if`, `@for` with a meaningful `track`, `@switch`, `@defer` where it helps). No `*ngIf` or `*ngFor`.
- Use typed reactive forms (`FormBuilder.nonNullable`). Template-driven forms are not allowed.
- Use functional route guards, functional resolvers and functional HTTP interceptors, registered with `provideHttpClient(withInterceptors([...]))`.
- Use `provideRouter(routes, withComponentInputBinding())` so route params can come in as inputs.
- Lazy-load each feature with `loadComponent` / `loadChildren`.
- RxJS is for HTTP and event streams only. Convert to signals at the component boundary with `toSignal`. Unsubscribe with `takeUntilDestroyed()`.
- TypeScript `strict: true`. No `any`, and no non-null assertions (`!`) unless the code proves the value exists. Prefer `readonly` and `as const`.
- Naming: `kebab-case` file names, `PascalCase` classes, and selectors prefixed `emr-`.
- No business logic in templates. Pure logic (CKD staging, abnormal flagging, eGFR math, validators) lives in plain TypeScript functions under `shared/utils` or `core/clinical` and is unit-tested.

## 5. Architecture
```
src/
  app/
    core/              # singletons: auth, http interceptors, api config, error handler, clinical rules
      api/             # endpoints.ts (all paths), api.types.ts
      auth/            # auth.service, auth.guard, token storage
      http/            # auth, error and mock interceptors
      clinical/        # reference-ranges, ckd-stage, egfr, lab-flagging (pure + tested)
      mocks/           # synthetic data + mock backend
    shared/
      ui/              # presentational, reusable components (no services injected)
      pipes/
      validators/
      utils/
      models/          # domain interfaces
    layout/            # app shell, header, sidebar, page header
    features/
      auth/
      patients/
      encounters/
      labs/
      ai-summary/
  styles/
    _tokens.scss
    _reset.scss
    _typography.scss
    styles.scss
  environments/
```
- **Container components** (pages) inject services, hold state and handle routing.
- **Presentational components** (in `shared/ui` and feature `components/`) receive inputs, emit outputs and inject nothing except other presentational helpers.
- One data-access service per feature (for example `PatientsApi`). Components never call `HttpClient` directly.
- All endpoint paths live in `core/api/endpoints.ts`.

## 6. Data and state rules
- Every async view has explicit **loading, empty, error and success** states, each styled from the HTML.
- Model remote state as a discriminated union or with a small helper. Never use tangled boolean flags such as `isLoading && !hasError && data`.
- Dates: store ISO strings and display with `DatePipe` in one consistent format, taken from the HTML.
- Units: each lab parameter has a canonical unit (see `core/clinical/reference-ranges.ts`). Always display the unit next to the value.
- Missing clinical data renders as **"Not documented"**. Never show a blank, `undefined`, `null` or a guessed value.

## 7. Clinical-safety UI rules
- AI-generated content must always sit in a visually distinct container labeled **"AI-generated"**, with a model or generated-at timestamp and this disclaimer:
  *"AI-generated summary for clinician review only. It may be incomplete or inaccurate. It is not a diagnosis or treatment recommendation. Verify against the patient record."*
- The UI must never present AI text as part of the patient record and never auto-save AI text into clinical fields.
- Abnormal lab values are flagged with text or an icon (H/L), not color alone, for accessibility.
- Reference ranges and CKD criteria come from one configurable source, never scattered literals.

## 8. Accessibility and UX
- Semantic HTML: `<main>`, `<nav>`, `<header>`, `<table>` with `<th scope>`, and `<button>` for every action.
- Every input has a `<label>`. Errors are linked with `aria-describedby`.
- Full keyboard support, visible focus rings (matching the HTML's style if it has one), and focus trapping in modals.
- Use `aria-live="polite"` for search results counts, save confirmations and the AI summary result.
- Meet contrast of 4.5:1 for text. If the HTML fails contrast somewhere, note it in the inventory rather than silently changing it.

## 9. Quality gates (run before every commit)
- **Docker only.** The host Node (v22.11.0) is unsupported. NEVER run `node`, `npm`, `npx` or `ng` on the host: `node_modules` holds Linux binaries and a host run would corrupt it. Run everything through the `web` service in `frontend/compose.yaml`, e.g. `docker compose exec web npx ng build`, `docker compose exec web npm install <pkg>`, `docker compose exec web npx ng test --watch=false`, `docker compose exec web npx ng lint`. If `ng test` needs a browser that is missing in the container, report it; do not install Chrome into the image.
- `ng build` passes with zero errors and zero warnings.
- `ng test` passes. Use the CLI's default test runner.
- `ng lint` passes (angular-eslint), and Prettier is applied.
- No `console.log` left behind, and the browser console is clean.

## 10. Working style
- Work in the phase order given in `PROMPTS.md`. Finish, verify and commit each phase before starting the next.
- Commit messages use Conventional Commits, for example `feat(labs): add CKD stage badge`.
- Before writing code for a phase, state a short plan of the files you will create or change.
- Never silently skip a requirement. If something is blocked or ambiguous, say so and propose an option.
- Add short comments explaining any non-obvious decision. The developer must be able to defend every choice in a technical interview.
- Do not install a package without stating why it is needed and what the alternative was.
