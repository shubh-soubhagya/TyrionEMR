import { HttpErrorResponse } from '@angular/common/http';

/** One entry of the envelope's `details` array (field-level validation problems and similar). */
export interface ApiErrorDetail {
  readonly field?: string;
  readonly issue?: string;
  readonly code?: string;
  readonly [key: string]: unknown;
}

/**
 * The platform error envelope `{error: {code, message, details, request_id}}` as one object.
 * `status` 0 means the request never got an answer (network down, CORS); its code is `NETWORK_ERROR`.
 * The `code` is for the program; screens show `message` and `requestId`, never the code.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: readonly ApiErrorDetail[],
    readonly requestId: string | null,
    readonly retryAfterS: number | null,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** Field-level problems keyed by dotted / indexed path (`results[1].unit`, `vitals.systolic_bp`). */
  fieldIssues(): ReadonlyMap<string, string> {
    const out = new Map<string, string>();
    for (const d of this.details) {
      if (typeof d.field === 'string' && !out.has(d.field)) {
        out.set(d.field, d.issue ?? this.message);
      }
    }
    return out;
  }

  hasDetailCode(code: string): boolean {
    return this.details.some((d) => d.code === code);
  }
}

const GENERIC = 'Something went wrong. Please try again.';
const NETWORK = 'The server could not be reached. Check your connection and try again.';

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

function parseRetryAfter(raw: string | null): number | null {
  if (raw === null) return null;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? Math.ceil(n) : null;
}

/** Turns any failed HttpClient response into an ApiError. Never throws; a non-JSON body gets a generic message. */
export function toApiError(err: HttpErrorResponse): ApiError {
  if (err.status === 0) {
    return new ApiError(0, 'NETWORK_ERROR', NETWORK, [], null, null);
  }
  const retryAfter = parseRetryAfter(err.headers?.get('Retry-After') ?? null);
  const body: unknown = err.error;
  const env = isRecord(body) && isRecord(body['error']) ? body['error'] : null;
  if (env === null) {
    return new ApiError(err.status, 'HTTP_' + err.status, GENERIC, [], null, retryAfter);
  }
  const details = Array.isArray(env['details'])
    ? (env['details'].filter(isRecord) as ApiErrorDetail[])
    : [];
  return new ApiError(
    err.status,
    typeof env['code'] === 'string' ? env['code'] : 'HTTP_' + err.status,
    typeof env['message'] === 'string' ? env['message'] : GENERIC,
    details,
    typeof env['request_id'] === 'string' ? env['request_id'] : null,
    retryAfter,
  );
}
