# API reference

Every call the Angular app makes goes through the gateway. This page is the guide; the tables at the bottom list every
endpoint and are generated from each service's OpenAPI file (`make docs`). The OpenAPI files hold the full request and
response schemas.

Contents:

- [Base URL and access](#base-url-and-access)
- [Authentication](#authentication)
- [Error envelope](#error-envelope)
- [Conventions](#conventions)
- [Workflows](#workflows)
- [Endpoint tables](#endpoint-tables)

## Base URL and access

| Item | Value |
|---|---|
| Base URL | `http://localhost:8080/api` (the gateway is the only published port) |
| Routed prefixes | `/api/auth`, `/api/patients`, `/api/encounters`, `/api/labs`, `/api/ai`, `/api/insights` |
| Never routed | `/api/internal/**` answers `404`, like any unknown prefix |
| Format | JSON, UTF-8 |
| Interactive docs | The gateway serves an aggregated Swagger UI at `http://localhost:8080/docs` outside production. Each service also serves its own `/docs` when run alone (auth-svc on 8001, patient-svc on 8002, lab-svc on 8003) |

The gateway strips `/api` and forwards the rest to the owning service: `/api/labs/patients/{id}/trends` becomes
`/labs/patients/{id}/trends` on lab-svc. Routes and limits: [gateway/README.md](../gateway/README.md).

## Authentication

1. `POST /api/auth/login` with `{"email", "password"}`. The response body holds the access token and the user. The response
   also sets the refresh cookie.
2. Send the token on every other call: `Authorization: Bearer <access_token>`.
3. When the token expires, `POST /api/auth/refresh` with the cookie (no body) returns a new token and a new cookie.
4. `POST /api/auth/logout` revokes the refresh token and clears the cookie.

Request and response, with the token shortened:

```http
POST /api/auth/login
Content-Type: application/json

{"email": "dr.rao@nephrocare.demo", "password": "<demo password, see the root README>"}
```

```http
HTTP/1.1 200 OK
Set-Cookie: nephro_rt=<opaque>; HttpOnly; Secure; SameSite=Strict; Path=/api/auth

{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {"id": "<uuid>", "email": "dr.rao@nephrocare.demo", "full_name": "Dr. Anita Rao",
           "role": "clinician", "last_login_at": "2026-11-14T09:12:41Z"}
}
```

```http
GET /api/auth/me
Authorization: Bearer eyJ...
```

| Item | Value |
|---|---|
| Access token | RS256, 15 minutes, kept in browser memory only. It holds no personal data (`sub`, `role`, `iss`, `aud`, `kid`, `iat`, `exp`) |
| Refresh token | 7 days, rotated on every refresh. The cookie `nephro_rt` is HttpOnly, Secure, SameSite=Strict, `Path=/api/auth` |
| Silent refresh | The Angular app calls refresh once at start-up and again on a `401 TOKEN_EXPIRED`, with a single in-flight request. A reload therefore keeps the session |
| Public routes | `POST /api/auth/login`, `signup`, `refresh` and `logout`. Everything else needs a bearer token |
| Verification | The gateway verifies the token against the published keys, and each service verifies it again |

Browsers accept the Secure cookie only for `localhost` or HTTPS, so open the app as `http://localhost:4200`, not by IP.
Design: [auth-svc/README.md](../auth-svc/README.md#token-and-cookie-model).

## Error envelope

Every error from the gateway or any service has the same shape:

```json
{"error": {"code": "VERSION_CONFLICT", "message": "The record was changed by someone else.", "details": [],
           "request_id": "req-3f9a1c2b7d10"}}
```

`request_id` is also the `X-Request-ID` response header. It appears in every service log line for the call, so quote it
when reporting a problem. Validation errors list `{"field", "issue"}` pairs in `details` and never echo the submitted value.

| Code | HTTP | Returned by | What the client does |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | all services, gateway | Show the `details` next to the fields |
| `BAD_REQUEST` | 400 | gateway | Fix the request (malformed or unreadable body) |
| `INVALID_PATH` | 400 | gateway | Fix the URL (encoded dots, slashes or NUL are refused, not normalised) |
| `INVALID_CURSOR` | 400 | lab-svc | Restart the bulk read from the first page |
| `UNAUTHENTICATED` | 401 | all | Refresh once, then send the user to sign in |
| `TOKEN_EXPIRED` | 401 | gateway, auth-svc, ai-svc | Call refresh and retry once |
| `INVALID_CREDENTIALS` | 401 | auth-svc | Show "email or password is wrong" (same answer for an unknown email) |
| `REFRESH_MISSING`, `REFRESH_INVALID`, `REFRESH_EXPIRED`, `REFRESH_REUSED` | 401 | auth-svc | Sign in again |
| `REFRESH_RACE` | 409 | auth-svc | Two refreshes overlapped; retry once |
| `FORBIDDEN` | 403 | all | Show "not allowed" |
| `ACCOUNT_DISABLED`, `SIGNUP_DISABLED`, `ORIGIN_NOT_ALLOWED` | 403 | auth-svc, gateway | Show the message |
| `NOT_FOUND` | 404 | all | Show the not-found page |
| `PATIENT_NOT_FOUND`, `RESULT_NOT_FOUND`, `SUMMARY_NOT_FOUND` | 404 | lab-svc, ai-svc | Show the not-found state |
| `METHOD_NOT_ALLOWED` | 405 | gateway | Programming error |
| `EMAIL_TAKEN` | 409 | auth-svc | Ask for another email |
| `VERSION_CONFLICT` | 409 | patient-svc | Reload the record, then let the user redo the edit |
| `ENCOUNTER_FINAL` | 409 | patient-svc | The encounter is final and cannot change; reload |
| `PRIMARY_CONFLICT`, `CONDITION_NOT_ACTIVE` | 409 | patient-svc | Reload the problem list |
| `DUPLICATE_ALLERGY`, `ALLERGIES_PRESENT` | 409 | patient-svc | Show the message |
| `MEDICATION_ALREADY_DISCONTINUED` | 409 | patient-svc | Reload the medication list |
| `RESULT_ALREADY_SUPERSEDED` | 409 | lab-svc | The result was already corrected; `details` carries the current id |
| `NO_CHANGE` | 422 | lab-svc | A correction must change the value or unit |
| `TOO_MANY_IDS` | 422 | lab-svc | Send fewer ids per call |
| `PAYLOAD_TOO_LARGE` | 413 | gateway | Send a smaller body |
| `URI_TOO_LONG` | 414 | gateway | Send a shorter URL |
| `ACCOUNT_LOCKED` | 429 | auth-svc | Wait for `Retry-After` |
| `RATE_LIMITED` | 429 | gateway, auth-svc | Wait for `Retry-After` |
| `AI_QUOTA_EXCEEDED` | 429 | ai-svc | Today's AI summary limit is reached; `details` has the limit and `resets_at` |
| `INTERNAL_ERROR` | 500 | all | Report the `request_id` |
| `UPSTREAM_ERROR` | the upstream's own 5xx | gateway | A service returned a non-JSON or unexpected 5xx; the status is kept. Retry later |
| `UPSTREAM_UNAVAILABLE` | 502 | gateway, lab-svc, ai-svc | A dependency is down; retry |
| `UPSTREAM_TIMEOUT` | 504 | gateway, lab-svc, ai-svc | A dependency was too slow; retry |
| `DB_UNAVAILABLE`, `SERVICE_BUSY`, `GATEWAY_BUSY`, `INSIGHTS_TOO_LARGE`, `NOT_READY`, `UPSTREAM_NOT_DEPLOYED` | 503 | service named by the code | Retry after `Retry-After` |

An upstream error that is already in the envelope passes through unchanged. For a 4xx without an envelope the gateway maps the
status to a code and adds `details: [{"upstream": <status>}]`. For a 5xx without an envelope it answers with the same status,
the code `UPSTREAM_ERROR` and `details: [{"upstream": <status>, "upstream_status": <status>}]`. The mapping is in
[gateway/README.md](../gateway/README.md#design-and-deviations) (D5).

AI summaries have a second kind of failure: the call succeeds and the summary document carries `status` of `degraded` or
`failed` with an `error_code`. See [AI summary workflow](#4-generate-an-ai-summary).

## Conventions

| Topic | Rule |
|---|---|
| Identifiers | UUID for every resource. The MRN (`PT-000101`) is the human-readable patient number and is searchable |
| Timestamps | ISO 8601 in UTC (`2026-11-14T09:12:41Z`); dates without time are `YYYY-MM-DD` in the clinic time zone (`Asia/Kolkata`) |
| Pagination | `page` (from 1) and `size` query parameters; the response is `{"items": [...], "page", "size", "total"}`. Bulk internal reads use `cursor` and `limit` |
| Optimistic locking | Patient `PATCH` bodies carry the `version` the client read. A stale version answers `409 VERSION_CONFLICT`. Responses return the new `version` |
| Immutable records | A finalised encounter cannot change (`409 ENCOUNTER_FINAL`). Deletes are soft deletes. Lab results are append-only; a correction supersedes the old result |
| Caching | `GET /api/labs/patients/{id}/latest` returns `ETag: W/"status-<n>"` and honours `If-None-Match` with `304` |
| Units | Lab values are stored in a canonical unit per test. A request may use another accepted unit; the response keeps both `value` and `value_original` |
| Limits | Body 1 MiB (16 KiB on `/api/auth`); URL 24,576 bytes; upstream connect timeout 1 s; default upstream timeout 5 s, 10 s for `/api/insights` |
| Request id | The client may send `X-Request-ID`; the gateway generates one when it is missing and returns it |

Rate limits (token bucket, per minute with a burst allowance; the gateway answers `429 RATE_LIMITED` with `Retry-After`):

| Policy | Applies to | Key | Per minute | Burst |
|---|---|---|---|---|
| `ip_global` | every request | IP | 1200 | 200 |
| `auth_login` | `POST /api/auth/login`, `signup` | IP | 10 | 5 |
| `auth_refresh` | `POST /api/auth/refresh` | IP | 60 | 20 |
| `user_default` | every authenticated call | user | 300 | 100 |
| `ai_generate` | `POST /api/ai/patients/{id}/summary` | user | 10 | 3 |
| `ai_poll` | `GET /api/ai/summaries/{id}` (replaces `user_default`) | user | 300 | 60 |

The values are the defaults in `gateway/app/core/config.py` and can be changed in the gateway's environment.

## Workflows

Bodies are abridged to the fields that matter; the schemas in the OpenAPI files are complete. All examples use synthetic
data and a shortened token (`eyJ...`).

### 1. Register a patient

```http
POST /api/patients
Authorization: Bearer eyJ...

{"first_name": "Ramesh", "last_name": "Kulkarni", "date_of_birth": "1959-04-17", "sex": "M"}
```

`201 Created` returns the patient with a server-assigned `id`, `mrn` (`PT-000111` and up), `version: 1` and a
`Location` header. Then:

- `GET /api/patients?q=Kulkarni&sort=name&page=1&size=8` searches by name or MRN (`q`), filters by `sex` and `stage`, and sorts by
  `name`, `mrn`, `age`, `dx` or `visit`.
- `PATCH /api/patients/{id}` with the changed fields and `version` edits demographics.
- `POST /api/patients/{id}/conditions`, `/medications` and `/allergies` fill the chart.

### 2. Record and finalise an encounter

```http
POST /api/patients/{id}/encounters
Authorization: Bearer eyJ...

{"encounter_date": "2026-11-11T10:15:00+05:30", "encounter_type": "follow_up",
 "chief_complaint": "Review of labs", "symptoms": ["Fatigue"],
 "vitals": {"systolic_bp": 138, "diastolic_bp": 82, "heart_rate": 74, "temperature_c": 36.7, "weight_kg": 72.9},
 "assessment": "Persistent eGFR decline", "plan": "Follow-up in 6 weeks", "follow_up_date": "2026-12-23",
 "diagnoses": [{"icd10_code": "N18.32", "description": "Chronic kidney disease, stage 3b", "add_to_problem_list": true}],
 "status": "draft"}
```

1. With `"status": "draft"` the call returns `201` with `{"encounter": {...}, "problem_list_changes": {"added": 0, "reactivated": 0, "linked": 0}}`.
   A draft can be edited with `PATCH /api/patients/{id}/encounters/{eid}` (sending its `version`) or deleted.
2. `POST /api/patients/{id}/encounters/{eid}/finalize` freezes it. The diagnoses marked `add_to_problem_list` are
   linked to existing conditions or added, and the response reports the counts in `problem_list_changes`.
3. A final encounter answers `409 ENCOUNTER_FINAL` to any later change. Sending `"status": "final"` on create does both
   steps at once.

### 3. Add a lab report entered in µmol/L and read the trend

```http
POST /api/labs/patients/{id}/reports
Authorization: Bearer eyJ...

{"collected_at": "2026-11-12T08:30:00Z", "lab_name": "Metro Lab",
 "results": [{"test_code": "CREAT", "value": 170, "unit": "µmol/L"},
             {"test_code": "UACR", "value": 36, "unit": "mg/g"}]}
```

`201 Created` returns `{"report", "results", "summary"}`. Each result carries the value converted to the canonical unit
(`1.92 mg/dL` for 170 µmol/L), the original value and unit, the reference range used, and a `flag` (`normal`, `low`, `high`,
`critical_low`, `critical_high` or `unknown`). `summary` is the patient's updated lab status.

Read it back:

- `GET /api/labs/patients/{id}/trends?tests=CREAT,EGFR` returns one series per test with `points`, `stats` (first, last,
  change, slope per year, `direction`, `rapid_decline`), the `reference` range and, for eGFR, `stage_bands`.
- `GET /api/labs/patients/{id}/latest` returns the newest result per test, the CKD block and `result_count`.
- `POST /api/labs/results/{result_id}/correct` with `{"value", "unit", "reason"}` supersedes a result; the old one is kept.

### 4. Generate an AI summary

1. `POST /api/ai/patients/{id}/summary` returns `202 Accepted` with a summary document whose `status` is `running`, a
   `progress` list of the pipeline steps, and a `summary_id`. Add `?force=true` to skip the cache.
2. Poll `GET /api/ai/summaries/{summary_id}` about every second until `status` is no longer `running`.
3. The final document has `status`:
   - `completed`: `facts` (computed in code), `gaps` (rule findings), `ai.content` (the narrative), `sources` (the records each
     citation points to), `validation` and the server-injected `disclaimer`.
   - `degraded`: the facts and gaps are present but the narrative is not (`ai` is null, `error_code` says why).
   - `failed`: nothing usable; `error_code` and `error_message` say why.
4. `GET /api/ai/patients/{id}/summaries` lists earlier summaries.

Full examples of every shape (running, completed, degraded, failed, cache hit) are in
[ai-svc/docs/api/examples/](../ai-svc/docs/api/examples/). The design is in [ARCHITECTURE.md](ARCHITECTURE.md#ai-integration).

## Endpoint tables

Generated by `scripts/docs/gen_api_docs.py` from the OpenAPI files. Do not edit between the markers. The `Auth` column
follows the gateway's public-route table. Summaries are the route function names.

<!-- BEGIN GENERATED -->

### auth-svc

Source: [auth-svc/docs/api/openapi.json](../auth-svc/docs/api/openapi.json). 6 endpoints are reachable through the gateway.

| Method | Gateway path | Summary | Auth | Query parameters | Success |
|---|---|---|---|---|---|
| POST | `/api/auth/login` | Login | public | - | 200 |
| POST | `/api/auth/logout` | Logout | public | - | 204 |
| GET | `/api/auth/me` | Me | bearer | - | 200 |
| POST | `/api/auth/password` | Change Password | bearer | - | 204 |
| POST | `/api/auth/refresh` | Refresh | public | - | 200 |
| POST | `/api/auth/signup` | Signup | public | - | 201 |

Not reachable through the gateway (auth-svc):

| Method | Service path | Summary | Caller |
|---|---|---|---|
| GET | `/.well-known/jwks.json` | Jwks | the gateway and the other services (token verification) |
| GET | `/health` | Health | Docker health check and the gateway's readiness probe |
| GET | `/ready` | Ready | Docker health check and the gateway's readiness probe |

### patient-svc

Source: [patient-svc/docs/api/openapi.json](../patient-svc/docs/api/openapi.json). 22 endpoints are reachable through the gateway.

| Method | Gateway path | Summary | Auth | Query parameters | Success |
|---|---|---|---|---|---|
| GET | `/api/encounters` | Dashboard | bearer | `status`, `upcoming_followups`, `limit` | 200 |
| GET | `/api/patients` | List Patients | bearer | `q`, `sex`, `stage`, `ids`, `sort`, `dir`, `page`, `size` | 200 |
| POST | `/api/patients` | Create Patient | bearer | - | 201 |
| GET | `/api/patients/{pid}` | Get Patient | bearer | - | 200 |
| PATCH | `/api/patients/{pid}` | Patch Patient | bearer | - | 200 |
| DELETE | `/api/patients/{pid}` | Delete Patient | bearer | - | 204 |
| GET | `/api/patients/{pid}/allergies` | List Allergies | bearer | - | 200 |
| POST | `/api/patients/{pid}/allergies` | Create Allergy | bearer | - | 201 |
| DELETE | `/api/patients/{pid}/allergies/{aid}` | Remove Allergy | bearer | - | 200 |
| GET | `/api/patients/{pid}/conditions` | List Conditions | bearer | `status` | 200 |
| POST | `/api/patients/{pid}/conditions` | Create Condition | bearer | - | 201 |
| PATCH | `/api/patients/{pid}/conditions/{cid}` | Patch Condition | bearer | - | 200 |
| DELETE | `/api/patients/{pid}/conditions/{cid}` | Delete Condition | bearer | - | 204 |
| GET | `/api/patients/{pid}/encounters` | List Encounters | bearer | `status`, `page`, `size` | 200 |
| POST | `/api/patients/{pid}/encounters` | Create Encounter | bearer | - | 201 |
| GET | `/api/patients/{pid}/encounters/{eid}` | Get Encounter | bearer | - | 200 |
| PATCH | `/api/patients/{pid}/encounters/{eid}` | Patch Encounter | bearer | - | 200 |
| DELETE | `/api/patients/{pid}/encounters/{eid}` | Delete Encounter | bearer | - | 204 |
| POST | `/api/patients/{pid}/encounters/{eid}/finalize` | Finalize Encounter | bearer | - | 200 |
| GET | `/api/patients/{pid}/medications` | List Medications | bearer | `status` | 200 |
| POST | `/api/patients/{pid}/medications` | Create Medication | bearer | - | 201 |
| PATCH | `/api/patients/{pid}/medications/{mid}` | Patch Medication | bearer | - | 200 |

Not reachable through the gateway (patient-svc):

| Method | Service path | Summary | Caller |
|---|---|---|---|
| GET | `/health` | Health | Docker health check and the gateway's readiness probe |
| GET | `/internal/patients/charts` | Bulk Charts | ai-svc (private network) |
| GET | `/internal/patients/{pid}/basic` | Basic | ai-svc (private network) |
| GET | `/internal/patients/{pid}/chart` | Chart | ai-svc (private network) |
| GET | `/internal/patients/{pid}/conditions` | Conditions | ai-svc (private network) |
| GET | `/internal/patients/{pid}/encounters` | Encounters | ai-svc (private network) |
| GET | `/internal/patients/{pid}/medications-allergies` | Medications Allergies | ai-svc (private network) |
| GET | `/ready` | Ready | Docker health check and the gateway's readiness probe |

### lab-svc

Source: [lab-svc/docs/api/openapi.json](../lab-svc/docs/api/openapi.json). 7 endpoints are reachable through the gateway.

| Method | Gateway path | Summary | Auth | Query parameters | Success |
|---|---|---|---|---|---|
| GET | `/api/labs/patients/{patient_id}/latest` | Latest | bearer | - | 200 |
| POST | `/api/labs/patients/{patient_id}/reports` | Create Report | bearer | - | 201 |
| GET | `/api/labs/patients/{patient_id}/results` | Results | bearer | `test`, `from`, `to`, `flag`, `report_id`, `include_superseded`, `page`, `size` | 200 |
| GET | `/api/labs/patients/{patient_id}/trends` | Trends | bearer | `tests`, `from`, `to` | 200 |
| POST | `/api/labs/results/{result_id}/correct` | Correct Result | bearer | - | 201 |
| GET | `/api/labs/summary` | Summary | bearer | `patient_ids` | 200 |
| GET | `/api/labs/tests` | List Tests | bearer | `sex`, `age` | 200 |

Not reachable through the gateway (lab-svc):

| Method | Service path | Summary | Caller |
|---|---|---|---|
| GET | `/health` | Health | Docker health check and the gateway's readiness probe |
| GET | `/internal/labs/patients/{patient_id}/latest` | Latest | ai-svc (private network) |
| GET | `/internal/labs/patients/{patient_id}/results` | Internal Results | ai-svc (private network) |
| GET | `/internal/labs/patients/{patient_id}/trends` | Trends | ai-svc (private network) |
| GET | `/internal/labs/status` | Status | ai-svc (private network) |
| GET | `/ready` | Ready | Docker health check and the gateway's readiness probe |

### ai-svc

Source: [ai-svc/docs/api/openapi.json](../ai-svc/docs/api/openapi.json). 6 endpoints are reachable through the gateway.

| Method | Gateway path | Summary | Auth | Query parameters | Success |
|---|---|---|---|---|---|
| GET | `/api/ai/patients/{patient_id}/summaries` | History | bearer | `page`, `size` | 200 |
| POST | `/api/ai/patients/{patient_id}/summary` | Start Summary | bearer | `force` | 202 |
| GET | `/api/ai/summaries/{summary_id}` | Get Summary | bearer | `include` | 200 |
| GET | `/api/insights/dashboard` | Dashboard | bearer | - | 200 |
| GET | `/api/insights/patients/{patient_id}/gaps` | Gaps | bearer | - | 200 |
| GET | `/api/insights/worklist` | Worklist | bearer | `attention` | 200 |

Not reachable through the gateway (ai-svc):

| Method | Service path | Summary | Caller |
|---|---|---|---|
| GET | `/health` | Health | Docker health check and the gateway's readiness probe |
| GET | `/ready` | Ready | Docker health check and the gateway's readiness probe |

<!-- END GENERATED -->
