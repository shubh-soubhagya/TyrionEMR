// Every HTTP path of the app, built from one base. No path string may appear anywhere else (CLAUDE.md §5).
// The base is relative ('/api'): the Angular dev server proxies it to the gateway (proxy.conf.mjs), so the browser
// only ever talks to its own origin and the refresh cookie (Path=/api/auth) is sent.
import { environment } from '@env/environment';

export const API_BASE = environment.apiBaseUrl;

const seg = (id: string): string => encodeURIComponent(id);

export const AUTH = {
  login: `${API_BASE}/auth/login`,
  signup: `${API_BASE}/auth/signup`,
  refresh: `${API_BASE}/auth/refresh`,
  logout: `${API_BASE}/auth/logout`,
  me: `${API_BASE}/auth/me`,
  password: `${API_BASE}/auth/password`,
} as const;

export const PATIENTS = {
  list: `${API_BASE}/patients`,
  one: (id: string) => `${API_BASE}/patients/${seg(id)}`,
  conditions: (id: string) => `${API_BASE}/patients/${seg(id)}/conditions`,
  condition: (id: string, cid: string) => `${API_BASE}/patients/${seg(id)}/conditions/${seg(cid)}`,
  medications: (id: string) => `${API_BASE}/patients/${seg(id)}/medications`,
  medication: (id: string, mid: string) =>
    `${API_BASE}/patients/${seg(id)}/medications/${seg(mid)}`,
  allergies: (id: string) => `${API_BASE}/patients/${seg(id)}/allergies`,
  allergy: (id: string, aid: string) => `${API_BASE}/patients/${seg(id)}/allergies/${seg(aid)}`,
  encounters: (id: string) => `${API_BASE}/patients/${seg(id)}/encounters`,
  encounter: (id: string, eid: string) => `${API_BASE}/patients/${seg(id)}/encounters/${seg(eid)}`,
  finalize: (id: string, eid: string) =>
    `${API_BASE}/patients/${seg(id)}/encounters/${seg(eid)}/finalize`,
} as const;

/** Cross-patient encounter queries behind the dashboard. */
export const ENCOUNTERS = { list: `${API_BASE}/encounters` } as const;

export const LABS = {
  tests: `${API_BASE}/labs/tests`,
  reports: (id: string) => `${API_BASE}/labs/patients/${seg(id)}/reports`,
  results: (id: string) => `${API_BASE}/labs/patients/${seg(id)}/results`,
  trends: (id: string) => `${API_BASE}/labs/patients/${seg(id)}/trends`,
  latest: (id: string) => `${API_BASE}/labs/patients/${seg(id)}/latest`,
  summary: `${API_BASE}/labs/summary`,
} as const;

export const INSIGHTS = {
  dashboard: `${API_BASE}/insights/dashboard`,
  worklist: `${API_BASE}/insights/worklist`,
  gaps: (id: string) => `${API_BASE}/insights/patients/${seg(id)}/gaps`,
} as const;

export const AI = {
  start: (id: string) => `${API_BASE}/ai/patients/${seg(id)}/summary`,
  summary: (sid: string) => `${API_BASE}/ai/summaries/${seg(sid)}`,
  history: (id: string) => `${API_BASE}/ai/patients/${seg(id)}/summaries`,
} as const;

/** True for a URL of this app's API (the only place the bearer token may be sent). */
export function isApiUrl(url: string): boolean {
  return url === API_BASE || url.startsWith(`${API_BASE}/`);
}

/** True for the auth endpoints: the only requests that carry the refresh cookie. */
export function isAuthUrl(url: string): boolean {
  return url.startsWith(`${API_BASE}/auth/`);
}
