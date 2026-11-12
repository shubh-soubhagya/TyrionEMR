# Build checklist

One line per screen, tab, modal and interaction in `reference/emr-ui.html` (line numbers are `html:LINE`), plus one line per assignment requirement. Tick off as milestones complete. The final report is generated from this file.

Legend: `[x]` done, `[ ]` not yet, `⚑` added (not in the HTML), `❌` not done (reason in the line).

## A. Foundation (M0–M3, done)

- [x] Workspace, tooling, Docker workflow (M0)
- [x] UI inventory and decisions (M1)
- [x] Tokens, reset, typography, shell, mobile drawer ⚑, user menu ⚑, skip link ⚑ (M2)
- [ ] Shared UI library (M3): built, gates pending at the time of writing

## B. Seed data from the HTML (html:417-488), to be reproduced exactly as the first records

Ten patients, `PT-000101` to `PT-000110`, with the clinician "Dr. Anita Rao" (the signed-in user, html:494):

- [ ] PT-000101 Ramesh Kulkarni, M, 67, CKD G3b, penicillin allergy, diabetic nephropathy, 4 encounters (1 draft)
- [ ] PT-000102 Sunita Verma, F, 58, G3a, sulfonamide allergy, hypertensive CKD
- [ ] PT-000103 Arjun Mehta, M, 45, G2, allergy status unknown, IgA nephropathy
- [ ] PT-000104 Fatima Sheikh, F, 72, G4, severe NSAID allergy + contrast, diabetic nephropathy
- [ ] PT-000105 Vikram Rao, M, 39, no stage, no known allergies, AKI (improving eGFR 30 to 74)
- [ ] PT-000106 Lakshmi Iyer, F, 63, ADPKD (established stage G4 vs eGFR G3b: mismatch case)
- [ ] PT-000107 Mohan Das, M, 55, G2, diabetic nephropathy, last labs 230 days ago, last reported eGFR bumped (+16)
- [ ] PT-000108 Priya Nair, F, 50, no labs, no encounters, no conditions, allergy unknown
- [ ] PT-000109 Aditya Singh, M, 61, G5, latex allergy, critical potassium 6.2
- [ ] PT-000110 Kavita Joshi, F, 34, no stage, lupus nephritis, hydroxychloroquine with an end date

## C. Screens and tabs

- [ ] Shell: sidebar, brand, nav (Dashboard, Patients), clinic card, topbar, global search, user chip (html:661-671)
- [ ] Sign in (html:713-733) and Sign up (html:734-750): present in code only, unreachable in the prototype
- [ ] Dashboard (html:1277-1305): greeting, KPI strip, Needs attention, eGFR category bars, Abnormal results, Follow-ups, Draft encounters
- [ ] Patient list (html:753-799): KPI strip, search, sex filter, stage filter, Needs-attention filter, clear filters, sortable columns, sparkline, pager, empty state
- [ ] Patient shell (html:837-858): breadcrumb, header chips, allergy chip, stage strip with mismatch chip, tab bar with count pills
- [ ] Overview tab (html:862-871): kidney function panel, demographics, history, at a glance, recent encounters, gap alert
- [ ] Conditions tab (html:874-891): established stage select, mismatch alert, nephrology and comorbidity tables, set primary, mark resolved
- [ ] Medications and allergies tab (html:894-915)
- [ ] Encounters tab (html:919-931): list, view modal (final), edit modal (draft)
- [ ] Labs tab (html:1006-1034): CKD grid, latest grid, range select, stage-band toggle, two charts, history table, filters, pager
- [ ] AI summary tab (html:1198-1256): intro, stepper, calculated facts, missing/inconsistent, AI narrative, sources, copy, history, what the AI was given, demo options
- [ ] Not-found page ⚑ (M2 placeholder exists)
- [ ] Mobile navigation drawer ⚑ (done in M2)

## D. Modals and forms

- [ ] Register patient (html:802-815), Edit patient
- [ ] Add condition (html:885)
- [ ] Add medication (html:903), discontinue confirmation
- [ ] Add allergy (html:909), remove confirmation, confirm no known allergies
- [ ] Encounter form (html:935-979): vitals, chip input, diagnoses rows, draft vs finalize, finalize confirmation, delete draft
- [ ] Encounter view (html:925)
- [ ] Add lab report (html:1036-1067): rows, units, live flag preview
- [ ] Confirm dialog (html:640)

## E. Interactions

- [ ] Global search to `/patients?q=`
- [ ] List search (debounced), filters, sort, paging, URL sync
- [ ] Row open (click and Enter)
- [ ] Established CKD stage change
- [ ] Set primary condition, mark resolved or reactivate
- [ ] Show discontinued medications
- [ ] Allergy status transitions
- [ ] Symptom chips, diagnosis rows
- [ ] Lab range, stage bands, test filter, abnormal-only, paging
- [ ] Live lab flag and unit conversion
- [ ] Chart tooltips
- [ ] AI generate, regenerate, cache hit, copy, open source chip, open earlier summary
- [ ] AI failure scenarios (invalid, timeout, rate limit, upstream)
- [ ] Toasts
- [ ] Sign out

## F. Assignment requirements

### 3A Patient management
- [ ] Patient listing with ID, name, age, gender, primary diagnosis
- [ ] Search by name or patient ID
- [ ] Demographics and medical history
- [ ] Comorbidities and established diagnoses
- [ ] Current medications and allergies
- [ ] Previous clinical encounters

### 3B Clinical encounters
- [ ] Create a new encounter
- [ ] Visit date and details
- [ ] Vitals: BP, heart rate, temperature, weight
- [ ] Chief complaint, symptoms, examination notes
- [ ] Assessment and diagnoses
- [ ] Treatment and follow-up plan
- [ ] Save and retrieve previous encounters

### 3C Laboratory results
- [ ] Eight parameters
- [ ] Add results with dates and units
- [ ] View historical results
- [ ] Creatinine and eGFR trend charts
- [ ] Abnormal values highlighted from reference ranges
- [ ] Established CKD stage or eGFR classification

### 3D AI assistant
- [ ] Summarize nephrology history
- [ ] Summarize conditions and comorbidities
- [ ] Creatinine and eGFR trends
- [ ] Abnormal laboratory findings
- [ ] Missing or inconsistent information
- [ ] Follow-up considerations for clinician review
- [ ] Missing information is not fabricated
- [ ] Invalid response and API failure handling
- [ ] AI content visibly distinguished from the record
- [ ] Clinical review disclaimer
- [ ] No diagnosis or treatment prescribed

### 4 Engineering
- [ ] Reusable Angular components
- [ ] Separation of concerns
- [ ] Error handling and input validation
- [ ] Basic testing
- [ ] Setup and execution instructions

### 5 Submission (frontend share)
- [ ] README, synthetic data, API description, architecture and AI explanation, screenshots
