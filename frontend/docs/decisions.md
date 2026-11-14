# Frontend decisions

Decisions that resolve the open questions (❓) in `ui-inventory.md` section 7.4. Recorded 2026-11-12.
Each one says what was decided, why, and where it applies.

## D1. Vitals: PROMPTS.md Phase 8 limits are the blocking limits; out-of-normal is a soft warning

**Decision.** The plausibility limits from PROMPTS.md Phase 8 block typos (validation error, form cannot be saved). Values that are outside the normal range but still plausible are accepted and show a soft warning only.

| Vital        | Blocking limit (error) | Notes                                                                                                                                          |
| ------------ | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| BP systolic  | 60–260 mmHg            |                                                                                                                                                |
| BP diastolic | 30–160 mmHg            | and must be lower than systolic (group validator)                                                                                              |
| Heart rate   | 30–220 bpm             |                                                                                                                                                |
| Temperature  | 34.0–42.0 °C           | stored and shown in °C (the HTML uses °C)                                                                                                      |
| Weight       | 2–300 kg               | 1 decimal                                                                                                                                      |
| SpO2         | not collected          | The HTML form and the HLD vitals model (`sys, dia, hr, temp, wt`) have no SpO2. Phase 8 says "only if the HTML includes it", so it is omitted. |

**Soft warnings (⚑ placeholder thresholds, need clinician sign-off).** Not errors; shown as a warning-toned hint under the field and never block saving. All thresholds live in one file (`shared/validators/vitals-limits.ts`, built in Phase 8) so a clinician can change them in one place.

| Vital       | Soft warning when                                                                                |
| ----------- | ------------------------------------------------------------------------------------------------ |
| BP          | systolic ≥ 140 or diastolic ≥ 90 (the example in PROMPTS.md), or systolic < 90 or diastolic < 60 |
| Heart rate  | < 50 or > 100 bpm                                                                                |
| Temperature | ≥ 38.0 or < 36.0 °C                                                                              |
| Weight      | none                                                                                             |

**Why.** The prototype's limits (BP 50–300, HR 20–300, T 30–45, weight 1–500) are so wide that most typos pass. Narrow blocking limits catch real mistakes (for example 1200 for 120). Clinically abnormal but real readings (a hypertensive patient at 190/110) must never be blocked, because refusing to record a true measurement is a patient-safety problem.

**Lab values.** The same rule is applied by analogy to Phase 9: the PROMPTS.md Phase 9 plausibility limits block typos (creatinine 0.1–25 mg/dL, eGFR 1–200, BUN 1–250, potassium 1.5–9.0, hemoglobin 3–25, calcium 4–16, phosphorus 0.5–15, UACR 0–10000), and abnormal-but-plausible values are saved and flagged (H / L / Critical). ⚑ This extension was not explicitly decided; say so if the HTML maxima should apply instead.

**Also decided here.** Follow-up date must not be before the visit date (HTML rule; same day allowed). Encounter diagnoses use the HTML's "Add to problem list" checkbox (the "primary" flag is set on the Conditions tab, one primary per patient).

## D2. AI disclaimer: CLAUDE.md wording, HTML styling

**Decision.** The text shown is the CLAUDE.md section 7 wording, defined once as a constant (`AI_DISCLAIMER`) and used everywhere: the panel, the copied text and the print stylesheet:

> AI-generated summary for clinician review only. It may be incomplete or inaccurate. It is not a diagnosis or treatment recommendation. Verify against the patient record.

The HTML's `.disclaimer` styling is kept (violet-tinted bar, info icon, bold "Clinical review required." lead, and the HTML's closing sentence "This narrative is stored separately and is not part of the patient record."). Only the middle sentence differs from the HTML, which reads "AI-generated content for clinician review only. It is not a diagnosis or a treatment recommendation. Verify everything against the source record."

The text states all four required points: AI-generated, for clinician review, may be inaccurate, not a diagnosis or treatment.

**Why.** CLAUDE.md ranks patient-safety wording first. The HTML wording omits "may be incomplete or inaccurate".

**Backend follow-up.** HLD section 10.9 says the server injects the disclaimer, and its sample string matches neither text. The UI renders its own constant and does not trust a server string for safety-critical text. ai-svc should be changed to return the same wording so they never disagree.

## D3. Token storage: in-memory access token plus silent refresh (httpOnly cookie)

**Evidence (read only from `auth-svc/`).**

- `app/api/cookies.py`: the refresh token is set as an **HttpOnly, SameSite=Strict, Path=/api/auth** cookie named `nephro_rt` (`app/core/config.py`), `Secure` by default, no Domain.
- `app/api/routes/auth.py`: `POST /auth/login` and `/auth/signup` return `{access_token, token_type: "Bearer", expires_in, user}` and set the cookie. `POST /auth/refresh` rotates it and returns the same shape. `POST /auth/logout` returns 204 and clears the cookie. `GET /auth/me` needs a valid access token.
- `app/core/security.py`: `/auth/refresh` and `/auth/logout` reject any request whose `Origin` header is not in `cors_allowed_origins` (default `http://localhost:4200`). CORS itself is owned by the gateway.
- `app/core/errors.py`: `409 REFRESH_RACE` ("two tabs refreshed at once") means retry and the cookie is NOT cleared. `401 REFRESH_REUSED` and the other refresh failures clear the cookie and mean the user must sign in again. `401 TOKEN_EXPIRED` and `401 UNAUTHENTICATED` are distinct codes.

**Decision.** Do not use `sessionStorage` or `localStorage` for tokens.

- Access token: kept only in a signal inside `AuthService` (memory).
- App start (`provideAppInitializer`): call `POST /auth/refresh` with credentials. Success gives an access token and user, so a page reload keeps the session. A 401 or missing cookie means signed out, so no error toast.
- On a 401 from an API call: one **single-flight** refresh (concurrent requests wait on the same promise), then retry the request once. If refresh fails, clear the session and go to `/login?returnUrl=`.
- `409 REFRESH_RACE`: wait a short random delay and retry the refresh once, since another tab already rotated the cookie. Do not sign out.
- `401 REFRESH_REUSED`: sign out and show "You were signed out for security. Please sign in again." (the server's message).
- Requests to `/auth/*` use `withCredentials: true`. The access token is attached only to requests for `environment.apiBaseUrl`.
- Logout calls `POST /auth/logout`, then clears memory.
- Proactive refresh shortly before `expires_in` is optional; the 401-then-refresh path is the required one.

**Dev setup requirement.** The cookie has `Path=/api/auth`, so the frontend must call `<origin>/api/auth/...`. In development use the Angular dev-server proxy (`/api` to the gateway) so the browser sees one origin and no CORS credentials setup is needed. If the app talks to the gateway on another port instead, the gateway must allow `http://localhost:4200` with credentials.

**Why.** The cookie is httpOnly, so JavaScript cannot read the refresh token and an XSS bug cannot steal the long-lived credential. An access token in memory lives 15 minutes and disappears on reload, then the cookie restores it. `sessionStorage` would give XSS a token it can read for the whole tab session, with no UX benefit because silent refresh already survives reloads. This also matches HLD sections 7.2 and 15.2, and it supersedes the `sessionStorage` mirror in PROMPTS.md Phase 5.

**Impact on the plan.** Phase 5 `restoreSession()` becomes "refresh, then use the returned user" (`/auth/me` is only needed if a fresh user object is required). Phase 4's `authInterceptor` and `errorInterceptor` follow the 401-then-refresh flow instead of "clear and redirect".

## D4. The six Phase 2 additions are approved

These are in the shell but not in the HTML. All are approved.

1. Mobile navigation drawer (hamburger button, slide-over sidebar, scrim, Escape closes, focus moves in and returns).
2. User menu with a Sign out action (the HTML defines the `.menu` styles but never renders the menu).
3. "Skip to main content" link.
4. `menu` icon (hamburger) drawn in the HTML's stroke style.
5. The user's name block is hidden on narrow screens so the top bar stays on one line.
6. Placeholder signed-in user.

**Placeholder user.** "Dr. Anita Rao" / "Nephrologist" is defined in exactly one place, `src/app/layout/placeholder-user.ts` (`PLACEHOLDER_USER`), imported by the shell. The file is marked `TODO(phase-5): remove`. Phase 5 replaces it with the signed-in user from `AuthService` and deletes the file.

## Charting library

A charting library was required for the laboratory trends. The reference HTML draws its charts by hand in SVG, so the first build did the same. The two lab trend charts now use **Chart.js 4** (`chart.js`, registered tree-shaken: line controller, line element, point element, linear scale). The alternative, the `ng2-charts` wrapper, would add a second dependency for no gain. The look is kept: the reference band, the dashed eGFR stage lines and labels, the flag-coloured points with a white ring, the hover crosshair and the last-value label are drawn by one small Chart.js plugin in `shared/ui/charts/line-chart.ts`. The tooltip is not Chart.js's own: hover feeds the shared tooltip component with the text from `shared/utils/chart-tips.ts`, so every tooltip in the app looks and behaves the same. Axis maths lives in `shared/utils/chart-axes.ts` and is unit-tested. The list sparkline stays hand-drawn SVG (a 86 by 26 px inline element, outside what the assignment asks for).

## Still open

- Whether ai-svc's disclaimer string will be aligned to D2 (backend change).
- The soft-warning thresholds in D1 need clinician sign-off.
- Reference ranges and CKD criteria are described as "supplied" but only placeholders exist.
- Whether the list KPI strip needs a `/patients/stats` endpoint (not in the HLD).
