# Assignment checklist

Every requirement of [reference/assignment.pdf](../reference/assignment.pdf), quoted word for word, with its status and
where to see it. Status is `met`, `partly met` or `not met`. "Where to see it" names the screen and its route, the screenshot
in [screenshots/](screenshots/), the endpoint (through the gateway, see [API.md](API.md)), the code and a test. The statuses
come from reading the code and the earlier test runs; this page was written without starting the stack.

Contents:

- [Summary of rows that are not fully met](#summary-of-rows-that-are-not-fully-met)
- [2. Technology requirements](#2-technology-requirements)
- [3A. Patient management](#3a-patient-management)
- [3B. Clinical encounter management](#3b-clinical-encounter-management)
- [3C. Laboratory results and kidney function monitoring](#3c-laboratory-results-and-kidney-function-monitoring)
- [3D. AI-powered clinical assistant](#3d-ai-powered-clinical-assistant)
- [4. Engineering expectations](#4-engineering-expectations)
- [5. Submission requirements](#5-submission-requirements)

## Summary of rows that are not fully met

| Requirement | Status | Why |
|---|---|---|
| "Highlight abnormal laboratory values using supplied reference ranges." (3C) and the AI equivalent (3D item 4) | partly met | No reference-ranges file came with the assignment. Values are common adult intervals from the prototype, kept in one data file and marked as a placeholder ([DATABASE.md](DATABASE.md#reference-ranges)) |
| "Display the established CKD stage or classify eGFR using the supplied classification criteria." (3C) | partly met | The established stage is shown, and eGFR is classified with KDIGO 2012 categories, but no criteria were supplied to compare with |
| "Database schema and synthetic patient data." (5) | partly met | The schema is documented from the migrations and the data from the seeds ([DATABASE.md](DATABASE.md)). The generated `docs/db/*.sql` dumps are produced by `make schema-dump` and are not committed |
| "Screenshots or a short screen recording demonstrating the application." (5) | partly met | Fifteen screenshots, but 04, 07 and 09 predate the move to Chart.js and show the earlier chart drawing. No screen recording |
| "Use reusable Angular components." (4) | met, with a caveat | About half of the shared form and layout components are used only by the dev UI-kit page; the feature pages use the reference markup directly ([frontend README](../frontend/README.md#reusable-components)) |

## 2. Technology requirements

| Requirement | Status | Where to see it |
|---|---|---|
| Frontend: "Angular" | met | The whole app: [frontend/](../frontend/), Angular 22 |
| "TypeScript, HTML, and CSS." | met | TypeScript in `frontend/src/app`, templates in `*.html`, styles in SCSS (compiled to CSS) in `frontend/src/styles` |
| "Use a charting library for laboratory trend visualization." | met | Chart.js 4 draws the creatinine and eGFR charts: [line-chart.ts](../frontend/src/app/shared/ui/charts/line-chart.ts); screenshots [07](screenshots/07-labs-table-and-trends.png), [09](screenshots/09-trend-charts.png); decision in [decisions.md](../frontend/docs/decisions.md#charting-library); test [chart-axes.spec.ts](../frontend/src/app/shared/utils/chart-axes.spec.ts) |
| Backend: "Implement REST APIs for frontend-backend communication." | met | Four services behind a gateway, all JSON over REST: [API.md](API.md) |
| ".NET is preferred; however, candidates are free to choose their preferred backend technology, programming language, and libraries (e.g., Python, Node.js, or others)." | met (free choice used) | Python FastAPI; reason in HLD [ADR-013](HLD.md#adr-013-python-fastapi-async) |
| "Focus on clean API design, proper request/response handling, and backend integration with the frontend." | met | One error envelope, pagination, optimistic locking, OpenAPI per service ([API.md](API.md#conventions)); the frontend maps DTOs and handles every error code ([core/api](../frontend/src/app/core/api)); end-to-end test [flow.e2e.ts](../frontend/e2e/flow/flow.e2e.ts) |
| Database: "Candidates may use any suitable SQL-based database (e.g., SQL Server, PostgreSQL, or SQLite)." | met | PostgreSQL, one database per service: [DATABASE.md](DATABASE.md) |
| "Alternatively, candidates may use locally stored JSON files or a predefined static dataset to store and retrieve patient information." | not applicable | PostgreSQL is used instead |
| "The choice of data storage is flexible; the focus should be on effective data handling and integration with the application." | met | Schemas with constraints and triggers, read model for labs, derived sort keys: [DATABASE.md](DATABASE.md) |
| AI integration: "Integrate an LLM using an available API such as OpenAI, Gemini, Claude, or an equivalent model. (optional if paid, use free/open source providers)" | met | ai-svc adapter with Groq (free tier) and a mock: [ai-svc/app/llm/](../ai-svc/app/llm); [ARCHITECTURE.md](ARCHITECTURE.md#providers); test [test_groq.py](../ai-svc/tests/unit/test_groq.py), opt-in [test_groq_live.py](../ai-svc/tests/live/test_groq_live.py) |
| "Free-tier APIs or a documented mock implementation are acceptable where API access is restricted." | met | The mock is the default and is documented with its scenarios: [ai-svc README](../ai-svc/README.md#llm-providers-and-demo-scenarios); [mock.py](../ai-svc/app/llm/mock.py) |
| AI coding tools: "The use of AI coding assistants and agents is encouraged." and the three bullets that follow | informational | How they were used: [DEVELOPMENT.md](DEVELOPMENT.md#how-ai-coding-agents-were-used) |

## 3A. Patient management

| Requirement | Status | Where to see it |
|---|---|---|
| "Patient listing with Patient ID, name, age, gender, and primary diagnosis." | met | Screen: Patients, `/patients` ([screenshot 03](screenshots/03-patient-list-filtered.png)). Endpoint `GET /api/patients`. Code [patient-list-page.ts](../frontend/src/app/features/patients/patient-list-page.ts), [repositories/patients.py](../patient-svc/app/repositories/patients.py). Test [test_patients.py](../patient-svc/tests/api/test_patients.py) |
| "Search patients by name or patient ID." | met | Search box on the list and the header search. Endpoint `GET /api/patients?q=`. Code [domain/search.py](../patient-svc/app/domain/search.py). Test `test_search` in [test_patients.py](../patient-svc/tests/api/test_patients.py) |
| "Patient demographics and medical history." | met | Patient chart, Overview tab ([screenshot 04](screenshots/04-overview-kidney-panel.png)). Endpoints `GET /api/patients/{id}`, `PATCH /api/patients/{id}`. Test [test_patients.py](../patient-svc/tests/api/test_patients.py) |
| "Comorbidities and established diagnoses." | met | Conditions tab ([screenshot 05](screenshots/05-conditions-stage-mismatch.png)). Endpoints `GET` and `POST /api/patients/{id}/conditions`, `PATCH` and `DELETE` on `/conditions/{cid}`. Test [test_chart.py](../patient-svc/tests/api/test_chart.py) |
| "Current medications and allergies." | met | Medications and allergies tab. Endpoints under `/api/patients/{id}/medications` and `/allergies`. Test [test_chart.py](../patient-svc/tests/api/test_chart.py) |
| "Previous clinical encounters." | met | Encounters tab and the Overview's recent encounters. Endpoint `GET /api/patients/{id}/encounters`. Test [test_encounters.py](../patient-svc/tests/api/test_encounters.py) |

## 3B. Clinical encounter management

| Requirement | Status | Where to see it |
|---|---|---|
| "Create a new patient encounter." | met | New encounter button, [screenshot 06](screenshots/06-encounter-form.png). Endpoint `POST /api/patients/{id}/encounters`. Code [encounter-modal.ts](../frontend/src/app/features/modals/encounter-modal.ts), [services/encounters.py](../patient-svc/app/services/encounters.py). Test `test_create_draft_roundtrip` in [test_encounters.py](../patient-svc/tests/api/test_encounters.py) |
| "Record visit date and encounter details." | met | Visit date, type, clinician, status in the form and the encounters table. Same endpoint; `encounter_date`, `encounter_type`. Test [test_encounters.py](../patient-svc/tests/api/test_encounters.py) |
| "Capture patient vitals such as BP, heart rate, temperature, and weight." | met | Vitals fields in the form. Table `encounter_vitals` with plausibility checks ([DATABASE.md](DATABASE.md#patient-svc)). Tests [test_encounters.py](../patient-svc/tests/api/test_encounters.py), [test_db_guards.py](../patient-svc/tests/db/test_db_guards.py) |
| "Record chief complaints, symptoms, and clinical examination notes." | met | Chief complaint, symptom chips and examination notes in the form. Fields `chief_complaint`, `symptoms`, `examination_notes`. Test [test_encounters.py](../patient-svc/tests/api/test_encounters.py) |
| "Record clinical assessment and diagnoses." | met | Assessment text and diagnosis rows with ICD-10 and "add to problem list". Fields `assessment`, `diagnoses`. Test [test_encounters.py](../patient-svc/tests/api/test_encounters.py) |
| "Document the treatment/follow-up plan." | met | Plan and follow-up date. Fields `plan`, `follow_up_date`; upcoming follow-ups on the dashboard (`GET /api/encounters`). Test [test_dashboard.py](../patient-svc/tests/api/test_dashboard.py) |
| "Save and retrieve previous encounters." | met | Save draft, finalise, reopen from the Encounters tab. Endpoints `PATCH`, `POST .../finalize`, `GET .../encounters/{eid}`. Test [test_encounters.py](../patient-svc/tests/api/test_encounters.py); trigger test [test_db_guards.py](../patient-svc/tests/db/test_db_guards.py) |

## 3C. Laboratory results and kidney function monitoring

"Implement a laboratory results module with the following parameters:"

| Requirement | Status | Where to see it |
|---|---|---|
| "Serum Creatinine." | met | Labs tab; test code `CREAT`, canonical mg/dL, also µmol/L. [catalog_data.py](../lab-svc/app/domain/catalog_data.py); `GET /api/labs/tests` |
| "eGFR." | met | `EGFR`, mL/min/1.73m². Same file |
| "Blood Urea Nitrogen (BUN)." | met | `BUN`, mg/dL, also mmol/L (urea). Same file |
| "Potassium." | met | `K`, mmol/L, also mEq/L. Same file |
| "Hemoglobin." | met | `HB`, g/dL, also g/L. Same file |
| "Calcium." | met | `CA`, mg/dL, also mmol/L. Same file |
| "Phosphorus." | met | `PHOS`, mg/dL, also mmol/L. Same file |
| "Urine Albumin-Creatinine Ratio (UACR)." | met | `UACR`, mg/g, also mg/mmol. Same file. Test that all eight are in the catalog: [test_catalog.py](../lab-svc/tests/api/test_catalog.py) |

"Users should be able to:"

| Requirement | Status | Where to see it |
|---|---|---|
| "Add laboratory results with dates and units." | met | Add lab report modal with date, lab name, per-result unit and live preview ([screenshot 08](screenshots/08-add-lab-report-preview.png)). Endpoint `POST /api/labs/patients/{id}/reports`. Code [lab-modal.ts](../frontend/src/app/features/modals/lab-modal.ts), [services/reports.py](../lab-svc/app/services/reports.py). Tests [test_reports.py](../lab-svc/tests/api/test_reports.py), [lab-preview.spec.ts](../frontend/src/app/core/clinical/lab-preview.spec.ts) |
| "View historical laboratory results." | met | Labs tab result history with filters and paging ([screenshot 07](screenshots/07-labs-table-and-trends.png)). Endpoint `GET /api/labs/patients/{id}/results`. Test [test_reads.py](../lab-svc/tests/api/test_reads.py) |
| "Visualize Creatinine and eGFR trends using charts." | met | Overview kidney panel and Labs tab ([screenshot 09](screenshots/09-trend-charts.png)). Endpoint `GET /api/labs/patients/{id}/trends`. Code [line-chart.ts](../frontend/src/app/shared/ui/charts/line-chart.ts), [trends.py](../lab-svc/app/domain/trends.py). Tests [test_domain.py](../lab-svc/tests/unit/test_domain.py), [chart-axes.spec.ts](../frontend/src/app/shared/utils/chart-axes.spec.ts) |
| "Highlight abnormal laboratory values using supplied reference ranges." | partly met | Flags (Low, High, Critical, No range) as text and arrows. Ranges are placeholders, not supplied; see the summary above. Code [flagging.py](../lab-svc/app/domain/flagging.py); test [test_domain.py](../lab-svc/tests/unit/test_domain.py) |
| "Display the established CKD stage or classify eGFR using the supplied classification criteria." | partly met | Established stage chip and eGFR category in the chart header and patient list; mismatch chip. KDIGO 2012 is used. Code [ckd.py](../lab-svc/app/domain/ckd.py); endpoint `GET /api/labs/patients/{id}/latest`. Test [test_domain.py](../lab-svc/tests/unit/test_domain.py) |

## 3D. AI-powered clinical assistant

"Implement an AI-powered feature that generates a clinical summary for a selected patient." Screen: patient chart, AI
summary tab, `/patients/{id}/ai` ([screenshots 10 to 14](screenshots/11-ai-summary-completed.png)). Endpoints:
`POST /api/ai/patients/{id}/summary`, `GET /api/ai/summaries/{id}`. Code [ai-svc/app/orchestrator/](../ai-svc/app/orchestrator).
Test [test_summary_api.py](../ai-svc/tests/api/test_summary_api.py). Pipeline: [ARCHITECTURE.md](ARCHITECTURE.md#ai-integration).

"The AI assistant should:"

| Requirement | Status | Where to see it |
|---|---|---|
| "Summarize the patient's nephrology history." | met | `history_summary` in the AI panel. Code [output_schema.py](../ai-svc/app/validation/output_schema.py), [prompts/v1/](../ai-svc/app/prompts/v1). Test [test_validation.py](../ai-svc/tests/unit/test_validation.py) |
| "Summarize relevant medical conditions and comorbidities." | met | `comorbidity_summary`. Same files |
| "Identify trends in Creatinine and eGFR based on historical results." | met | Calculated facts panel (numbers from code) and `trend_commentary`. Code [facts.py](../ai-svc/app/orchestrator/facts.py), [numbers.py](../ai-svc/app/validation/numbers.py). Test [test_validation.py](../ai-svc/tests/unit/test_validation.py) |
| "Highlight abnormal laboratory findings based on supplied reference ranges." | partly met | Abnormal results listed from lab-svc flags, plus `abnormal_commentary`. Same range caveat as 3C. Test [test_context.py](../ai-svc/tests/unit/test_context.py) |
| "Identify missing or inconsistent clinical information." | met | The "Missing or inconsistent" panel from the sixteen-rule engine. Code [gaps.py](../ai-svc/app/insights/rules/gaps.py); endpoint `GET /api/insights/patients/{id}/gaps`; screenshot on PT-000107 and PT-000108 data. Test [test_rules.py](../ai-svc/tests/unit/test_rules.py) |
| "Generate follow-up considerations for clinician review." | met | `follow_up_considerations`, at most six, screened by the safety lint. Code [safety.py](../ai-svc/app/validation/safety.py). Test [test_validation.py](../ai-svc/tests/unit/test_validation.py) |

"Technical expectations:"

| Requirement | Status | Where to see it |
|---|---|---|
| "Integrate an LLM through a backend service." | met | ai-svc; the browser never calls an LLM. [llm/](../ai-svc/app/llm); [ARCHITECTURE.md](ARCHITECTURE.md#providers) |
| "Prepare relevant patient context before calling the LLM." | met | Allow-list packet with scrubbing, references, budget and hash. [context/](../ai-svc/app/context). Test [test_context.py](../ai-svc/tests/unit/test_context.py) |
| "Handle missing information without fabricating patient details." | met | `not_documented`, "Not documented." sections, gap engine. [pipeline.py](../ai-svc/app/validation/pipeline.py). Test [test_validation.py](../ai-svc/tests/unit/test_validation.py) |
| "Implement error handling for invalid LLM responses and API failures." | met | Schema and citation validation with one repair, degraded and failed states ([screenshots 12](screenshots/12-ai-summary-degraded.png), [13](screenshots/13-ai-summary-failed.png)), circuit breaker. [resilience.py](../ai-svc/app/llm/resilience.py). Tests [test_resilience.py](../ai-svc/tests/unit/test_resilience.py), [test_summary_api.py](../ai-svc/tests/api/test_summary_api.py) |
| "Clearly distinguish AI-generated information from original patient records." | met | Separate "AI-generated" panel with provider, model and time; AI output stored only in `ai_summaries`; never written to the chart. [schemas/summary.py](../ai-svc/app/schemas/summary.py), [ai-tab.html](../frontend/src/app/features/patients/tabs/ai-tab.html). Test [ai-tab.spec.ts](../frontend/src/app/features/patients/tabs/ai-tab.spec.ts) |
| "Include an appropriate clinical review disclaimer." | met | Server-injected disclaimer text on every summary. [schemas/summary.py](../ai-svc/app/schemas/summary.py). Test [ai-tab.spec.ts](../frontend/src/app/features/patients/tabs/ai-tab.spec.ts) |
| "AI-generated content must not independently diagnose patients or prescribe treatment." | met | Safety lint blocks prescribing, dosing, new-diagnosis and admission language; the prompt forbids it. [safety.py](../ai-svc/app/validation/safety.py). Test [test_validation.py](../ai-svc/tests/unit/test_validation.py) |

## 4. Engineering expectations

| Requirement | Status | Where to see it |
|---|---|---|
| "Use reusable Angular components." | met, with a caveat | [shared/ui](../frontend/src/app/shared/ui), listed in the [frontend README](../frontend/README.md#reusable-components) |
| "Implement clean and well-structured backend APIs." | met | Layered services (routes, services, repositories, domain), OpenAPI per service, one error envelope: [DEVELOPMENT.md](DEVELOPMENT.md#conventions); layering tests such as [test_layers.py](../patient-svc/tests/unit/test_layers.py) |
| "Maintain appropriate separation of concerns." | met | Four services plus gateway; frontend core, shared and features split: [ARCHITECTURE.md](ARCHITECTURE.md#why-four-services) |
| "Implement basic error handling and input validation." | met | Pydantic validation and database constraints in every service; the frontend shows each error ([error-messages.ts](../frontend/src/app/core/api/error-messages.ts)); error table in [API.md](API.md#error-envelope) |
| "Maintain meaningful database relationships." | met | Foreign keys, partial unique indexes, triggers: [DATABASE.md](DATABASE.md) |
| "Include basic testing for important functionality." | met | Counts per suite in the [README](../README.md#tests) |
| "Provide setup and execution instructions." | met | [README Quick start](../README.md#quick-start) and each service README's Run section |

## 5. Submission requirements

| Requirement | Status | Where to see it |
|---|---|---|
| "Complete source code in a Git repository." | met | This repository |
| "README with setup and execution instructions." | met | [README.md](../README.md#quick-start) |
| "Database schema and synthetic patient data." | partly met | [DATABASE.md](DATABASE.md); seeds in each service (`make seed`); the generated dumps are not committed |
| "API documentation or endpoint descriptions." | met | [API.md](API.md) and `<service>/docs/api/openapi.json` |
| "A brief explanation of application architecture and AI integration." | met | [ARCHITECTURE.md](ARCHITECTURE.md) |
| "Screenshots or a short screen recording demonstrating the application." | partly met | [README Screenshots](../README.md#screenshots); three are older than the chart library change |
