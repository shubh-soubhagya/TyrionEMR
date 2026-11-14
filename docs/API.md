# API

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
