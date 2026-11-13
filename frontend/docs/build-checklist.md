# Build checklist

One line per screen, tab, modal and interaction in `reference/emr-ui.html` (line numbers are `html:LINE`), plus one line per assignment requirement. Tick off as milestones complete. The final report is generated from this file.

Legend: `[x]` done and checked (live in a browser against the running stack, or by a test: the note says which), `[ ]` not yet, `⚑` added (not in the HTML), `❌` not done (reason in the line).

State on 14 Nov 2026, after the screens were connected to the services: every screen reads the real backend through the gateway. "Live" means a Playwright run against the whole stack; "unit" means a test with a fake HTTP backend only.

## A. Foundation (M0–M3, done)

- [x] Workspace, tooling, Docker workflow (M0)
- [x] UI inventory and decisions (M1)
- [x] Tokens, reset, typography, shell, mobile drawer ⚑, user menu ⚑, skip link ⚑ (M2)
- [x] Shared UI library (M3)

## B. Seed data (now served by the services' seeds; the HTML's own list is the design)

Ten patients, `PT-000101` to `PT-000110`, with the clinician "Dr. Anita Rao" (the signed-in user, html:494):

- [x] PT-000101 Ramesh Kulkarni, M, 67, CKD G3b, penicillin allergy, diabetic nephropathy, 4 encounters (1 draft) (live: present through the API)
- [x] PT-000102 Sunita Verma, F, 58, G3a, sulfonamide allergy, hypertensive CKD (live: present through the API)
- [x] PT-000103 Arjun Mehta, M, 45, G2, allergy status unknown, IgA nephropathy (live: present through the API)
- [x] PT-000104 Fatima Sheikh, F, 72, G4, severe NSAID allergy + contrast, diabetic nephropathy (live: present through the API)
- [x] PT-000105 Vikram Rao, M, 39, no stage, no known allergies, AKI (improving eGFR 30 to 74) (live: present through the API)
- [x] PT-000106 Lakshmi Iyer, F, 63, ADPKD (established stage G4 vs eGFR G3b: mismatch case) (live: present through the API)
- [x] PT-000107 Mohan Das, M, 55, G2, diabetic nephropathy, last labs 230 days ago, last reported eGFR bumped (+16) (live: present through the API)
- [x] PT-000108 Priya Nair, F, 50, no labs, no encounters, no conditions, allergy unknown (live: present through the API)
- [x] PT-000109 Aditya Singh, M, 61, G5, latex allergy, critical potassium 6.2 (live: present through the API)
- [x] PT-000110 Kavita Joshi, F, 34, no stage, lupus nephritis, hydroxychloroquine with an end date (live: present through the API)

## C. Screens and tabs

- [x] Shell: sidebar, brand, nav (Dashboard, Patients), clinic card, topbar, global search, user chip (html:661-671)
- [x] Sign in (html:713-733) and Sign up (html:734-750): present in code only, unreachable in the prototype
- [x] Dashboard (html:1277-1305): greeting, KPI strip, Needs attention, eGFR category bars, Abnormal results, Follow-ups, Draft encounters
- [x] Patient list (html:753-799): KPI strip, search, sex filter, stage filter, Needs-attention filter, clear filters, sortable columns, sparkline, pager, empty state
- [x] Patient shell (html:837-858): breadcrumb, header chips, allergy chip, stage strip with mismatch chip, tab bar with count pills
- [x] Overview tab (html:862-871): kidney function panel, demographics, history, at a glance, recent encounters, gap alert
- [x] Conditions tab (html:874-891): established stage select, mismatch alert, nephrology and comorbidity tables, set primary, mark resolved
- [x] Medications and allergies tab (html:894-915)
- [x] Encounters tab (html:919-931): list, view modal (final), edit modal (draft)
- [x] Labs tab (html:1006-1034): CKD grid, latest grid, range select, stage-band toggle, two charts, history table, filters, pager
- [x] AI summary tab (html:1198-1256): intro, stepper, calculated facts, missing/inconsistent, AI narrative, sources, copy, history, what the AI was given, demo options
- [x] Not-found page ⚑ (M2 placeholder exists)
- [x] Mobile navigation drawer ⚑ (unit)

## D. Modals and forms

- [x] Register patient (html:802-815), Edit patient
- [x] Add condition (html:885)
- [x] Add medication (html:903), discontinue confirmation
- [x] Add allergy (html:909), remove confirmation, confirm no known allergies
- [x] Encounter form (html:935-979): vitals, chip input, diagnoses rows, draft vs finalize, finalize confirmation, delete draft
- [x] Encounter view (html:925)
- [x] Add lab report (html:1036-1067): rows, units, live flag preview
- [x] Confirm dialog (html:640)

## E. Interactions

- [x] Global search to `/patients?q=`
- [x] List search (debounced), filters, sort, paging, URL sync
- [x] Row open (click and Enter)
- [x] Established CKD stage change
- [x] Set primary condition, mark resolved or reactivate
- [x] Show discontinued medications
- [x] Allergy status transitions (live: add allergy; unit: remove, no known allergies)
- [x] Symptom chips, diagnosis rows (live: diagnosis rows; symptom chips unchanged and unit-tested only through the form)
- [x] Lab range, stage bands, test filter, abnormal-only, paging
- [x] Live lab flag and unit conversion
- ❌ Chart tooltips: component unchanged, not re-checked after the data source changed
- [x] AI generate, regenerate, open source chip, open earlier summary (live); cache hit and copy (unit only: the live regenerate sends force=true, which skips the cache)
- [x] AI failure scenarios (invalid, timeout, rate limit, upstream)
- [x] Toasts
- [x] Sign out

## F. Assignment requirements

### 3A Patient management

- [x] Patient listing with ID, name, age, gender, primary diagnosis
- [x] Search by name or patient ID
- [x] Demographics and medical history
- [x] Comorbidities and established diagnoses
- [x] Current medications and allergies
- [x] Previous clinical encounters

### 3B Clinical encounters

- [x] Create a new encounter
- [x] Visit date and details
- [x] Vitals: BP, heart rate, temperature, weight
- [x] Chief complaint, symptoms, examination notes
- [x] Assessment and diagnoses
- [x] Treatment and follow-up plan
- [x] Save and retrieve previous encounters

### 3C Laboratory results

- [x] Eight parameters
- [x] Add results with dates and units
- [x] View historical results
- [x] Creatinine and eGFR trend charts
- [x] Abnormal values highlighted from reference ranges
- [x] Established CKD stage or eGFR classification

### 3D AI assistant

- [x] Summarize nephrology history
- [x] Summarize conditions and comorbidities
- [x] Creatinine and eGFR trends
- [x] Abnormal laboratory findings
- [x] Missing or inconsistent information
- [x] Follow-up considerations for clinician review
- [x] Missing information is not fabricated
- [x] Invalid response and API failure handling
- [x] AI content visibly distinguished from the record
- [x] Clinical review disclaimer
- [x] No diagnosis or treatment prescribed

### 4 Engineering

- [x] Reusable Angular components
- [x] Separation of concerns
- [x] Error handling and input validation
- [x] Basic testing
- [x] Setup and execution instructions (root README)

### 5 Submission (frontend share)

- [x] README, synthetic data, API description, architecture and AI explanation, screenshots (root README and docs/screenshots)

## G. Not done, with reasons

- ❌ Visual parity at 1440, 1024, 768 and 375 px against the reference HTML: the parity harness compares pixels, and the data now comes from the services' seeds, so every screen differs in text. Differences that are data are listed in `docs/ui-inventory.md` section 8; layout was not changed.
- ❌ Labs tab count pill: lab-svc has no count of results in the patient header, so the pill is gone (decision recorded in ui-inventory section 8).
