import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, UrlTree, provideRouter } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../api/endpoints';
import { errorInterceptor } from '../http/error.interceptor';
import { authGuard, guestGuard, safeReturnUrl } from './auth.guard';
import { authInterceptor } from './auth.interceptor';
import { AuthService } from './auth.service';
import { refreshInterceptor } from './refresh.interceptor';

const REFRESH = `${API_BASE}/auth/refresh`;
const user = {
  id: 'u1',
  email: 'dr@x.test',
  full_name: 'Dr. Rao',
  role: 'clinician',
  last_login_at: null,
};
const token = (t: string, expires_in = 900) => ({
  access_token: t,
  token_type: 'Bearer',
  expires_in,
  user,
});
const envelope = (code: string, message = 'msg') => ({
  error: { code, message, details: [], request_id: 'req-1' },
});

function setup() {
  TestBed.configureTestingModule({
    providers: [
      provideRouter([{ path: 'login', children: [] }]),
      provideHttpClient(withInterceptors([authInterceptor, refreshInterceptor, errorInterceptor])),
      provideHttpClientTesting(),
    ],
  });
  return {
    auth: TestBed.inject(AuthService),
    http: TestBed.inject(HttpClient),
    ctrl: TestBed.inject(HttpTestingController),
    router: TestBed.inject(Router),
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('session', () => {
  it('login keeps the token in memory only and exposes the user with the Nephrologist label', async () => {
    const { auth, ctrl } = setup();
    const p = firstValueFrom(auth.login(' dr@x.test ', 'pw'));
    const req = ctrl.expectOne(`${API_BASE}/auth/login`);
    expect(req.request.body).toEqual({ email: 'dr@x.test', password: 'pw' });
    expect(req.request.withCredentials).toBe(true);
    expect(req.request.headers.has('Authorization')).toBe(false);
    req.flush(token('T1'));
    expect((await p).roleLabel).toBe('Nephrologist');
    expect(auth.accessToken()).toBe('T1');
    expect(auth.status()).toBe('authenticated');
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });

  it('restoreSession refreshes with the cookie; no cookie leaves the person anonymous', async () => {
    const { auth, ctrl } = setup();
    const p = auth.restoreSession();
    ctrl
      .expectOne(REFRESH)
      .flush(envelope('UNAUTHENTICATED'), { status: 401, statusText: 'Unauthorized' });
    await p;
    expect(auth.status()).toBe('anonymous');
    expect(auth.user()).toBeNull();
  });

  it('logout clears the session even when the server call fails', async () => {
    const { auth, ctrl } = setup();
    void firstValueFrom(auth.login('a@b.c', 'pw'));
    ctrl.expectOne(`${API_BASE}/auth/login`).flush(token('T1'));
    const p = firstValueFrom(auth.logout());
    ctrl.expectOne(`${API_BASE}/auth/logout`).flush(null, { status: 500, statusText: 'x' });
    await p;
    expect(auth.accessToken()).toBeNull();
    expect(auth.status()).toBe('anonymous');
  });
});

describe('refresh', () => {
  it('is single-flight: three concurrent refreshes cause exactly one POST', async () => {
    const { auth, ctrl } = setup();
    const all = Promise.all([
      firstValueFrom(auth.refresh()),
      firstValueFrom(auth.refresh()),
      firstValueFrom(auth.refresh()),
    ]);
    ctrl.expectOne(REFRESH).flush(token('NEW'));
    expect(await all).toEqual(['NEW', 'NEW', 'NEW']);
  });

  it('retries once after 409 REFRESH_RACE and keeps the session', async () => {
    vi.useFakeTimers();
    const { auth, ctrl } = setup();
    const p = firstValueFrom(auth.refresh());
    ctrl
      .expectOne(REFRESH)
      .flush(envelope('REFRESH_RACE'), { status: 409, statusText: 'Conflict' });
    await vi.advanceTimersByTimeAsync(400);
    ctrl.expectOne(REFRESH).flush(token('AFTER_RACE'));
    expect(await p).toBe('AFTER_RACE');
    expect(auth.status()).toBe('authenticated');
  });

  it('REFRESH_REUSED signs out and keeps the server message for the sign-in page', async () => {
    const { auth, ctrl } = setup();
    const p = firstValueFrom(auth.refresh()).catch((e: unknown) => e);
    ctrl
      .expectOne(REFRESH)
      .flush(envelope('REFRESH_REUSED', 'Your session was ended for safety.'), {
        status: 401,
        statusText: 'Unauthorized',
      });
    await p;
    expect(auth.status()).toBe('anonymous');
    expect(auth.notice()).toBe('Your session was ended for safety.');
  });

  it('ensureFresh does nothing while the token has more than a minute left, and refreshes otherwise', async () => {
    const { auth, ctrl } = setup();
    void firstValueFrom(auth.login('a@b.c', 'pw'));
    ctrl.expectOne(`${API_BASE}/auth/login`).flush(token('T1', 900));
    await firstValueFrom(auth.ensureFresh());
    ctrl.expectNone(REFRESH);

    const p = firstValueFrom(auth.ensureFresh(10_000_000));
    ctrl.expectOne(REFRESH).flush(token('T2'));
    await p;
    expect(auth.accessToken()).toBe('T2');
  });
});

describe('interceptors', () => {
  it("attach the bearer to this app's API only and credentials to /api/auth/* only", async () => {
    const { auth, http, ctrl } = setup();
    void firstValueFrom(auth.login('a@b.c', 'pw'));
    ctrl.expectOne(`${API_BASE}/auth/login`).flush(token('T1'));

    http.get(`${API_BASE}/patients`).subscribe();
    const api = ctrl.expectOne(`${API_BASE}/patients`);
    expect(api.request.headers.get('Authorization')).toBe('Bearer T1');
    expect(api.request.withCredentials).toBe(false);
    api.flush({});

    http.get(`${API_BASE}/auth/me`).subscribe();
    const me = ctrl.expectOne(`${API_BASE}/auth/me`);
    expect(me.request.headers.get('Authorization')).toBe('Bearer T1');
    expect(me.request.withCredentials).toBe(true);
    me.flush({});

    http.get('https://elsewhere.example/api/patients').subscribe();
    const other = ctrl.expectOne('https://elsewhere.example/api/patients');
    expect(other.request.headers.has('Authorization')).toBe(false);
    other.flush({});
  });

  it('three concurrent 401s cause ONE refresh and each request is retried once with the new token', async () => {
    const { auth, http, ctrl } = setup();
    void firstValueFrom(auth.login('a@b.c', 'pw'));
    ctrl.expectOne(`${API_BASE}/auth/login`).flush(token('OLD'));

    const results: unknown[] = [];
    for (const path of ['patients', 'labs/tests', 'insights/dashboard']) {
      http.get(`${API_BASE}/${path}`).subscribe((r) => results.push(r));
    }
    for (const path of ['patients', 'labs/tests', 'insights/dashboard']) {
      ctrl
        .expectOne(`${API_BASE}/${path}`)
        .flush(envelope('TOKEN_EXPIRED'), { status: 401, statusText: 'Unauthorized' });
    }
    ctrl.expectOne(REFRESH).flush(token('NEW'));
    for (const path of ['patients', 'labs/tests', 'insights/dashboard']) {
      const retry = ctrl.expectOne(`${API_BASE}/${path}`);
      expect(retry.request.headers.get('Authorization')).toBe('Bearer NEW');
      retry.flush({ ok: path });
    }
    expect(results).toHaveLength(3);
  });

  it('retries only once: a second 401 is returned to the caller', async () => {
    const { auth, http, ctrl } = setup();
    void firstValueFrom(auth.login('a@b.c', 'pw'));
    ctrl.expectOne(`${API_BASE}/auth/login`).flush(token('OLD'));

    let failed: unknown;
    http.get(`${API_BASE}/patients`).subscribe({ error: (e: unknown) => (failed = e) });
    ctrl
      .expectOne(`${API_BASE}/patients`)
      .flush(envelope('TOKEN_EXPIRED'), { status: 401, statusText: 'Unauthorized' });
    ctrl.expectOne(REFRESH).flush(token('NEW'));
    ctrl
      .expectOne(`${API_BASE}/patients`)
      .flush(envelope('TOKEN_EXPIRED'), { status: 401, statusText: 'Unauthorized' });
    ctrl.expectNone(REFRESH);
    expect(failed).toMatchObject({ status: 401, code: 'TOKEN_EXPIRED' });
  });

  it('a failed refresh clears the session and sends the person to /login?returnUrl=', async () => {
    const { auth, http, ctrl, router } = setup();
    void firstValueFrom(auth.login('a@b.c', 'pw'));
    ctrl.expectOne(`${API_BASE}/auth/login`).flush(token('OLD'));
    const nav = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    http.get(`${API_BASE}/patients`).subscribe({ error: () => undefined });
    ctrl
      .expectOne(`${API_BASE}/patients`)
      .flush(envelope('TOKEN_EXPIRED'), { status: 401, statusText: 'Unauthorized' });
    ctrl
      .expectOne(REFRESH)
      .flush(envelope('REFRESH_EXPIRED'), { status: 401, statusText: 'Unauthorized' });

    expect(auth.status()).toBe('anonymous');
    expect(nav).toHaveBeenCalledWith(['/login'], {
      queryParams: { returnUrl: expect.any(String) },
    });
  });

  it('does not try to refresh when an auth call itself returns 401', async () => {
    const { http, ctrl } = setup();
    let failed: unknown;
    http.post(`${API_BASE}/auth/login`, {}).subscribe({ error: (e: unknown) => (failed = e) });
    ctrl
      .expectOne(`${API_BASE}/auth/login`)
      .flush(envelope('INVALID_CREDENTIALS'), { status: 401, statusText: 'x' });
    ctrl.expectNone(REFRESH);
    expect(failed).toMatchObject({ code: 'INVALID_CREDENTIALS' });
  });
});

describe('guards', () => {
  it.each([
    ['/patients/abc?tab=labs', '/patients/abc?tab=labs'],
    ['/dashboard', '/dashboard'],
    ['https://evil.example/x', '/patients'],
    ['//evil.example/x', '/patients'],
    ['/\\evil.example', '/patients'],
    ['javascript:alert(1)', '/patients'],
    ['/login?returnUrl=/x', '/patients'],
    ['/signup', '/patients'],
    ['', '/patients'],
    [undefined, '/patients'],
    ['/a\nb', '/patients'],
  ])('safeReturnUrl(%j) -> %s', (raw, expected) => {
    expect(safeReturnUrl(raw)).toBe(expected);
  });

  it('authGuard lets a signed-in person in and sends everyone else to /login with returnUrl', async () => {
    const { auth, ctrl } = setup();
    const run = () =>
      TestBed.runInInjectionContext(() =>
        authGuard({} as never, { url: '/patients/1/labs' } as never),
      );
    const anonymous = run() as UrlTree;
    expect(TestBed.inject(Router).serializeUrl(anonymous)).toBe(
      '/login?returnUrl=%2Fpatients%2F1%2Flabs',
    );

    void firstValueFrom(auth.login('a@b.c', 'pw'));
    ctrl.expectOne(`${API_BASE}/auth/login`).flush(token('T'));
    expect(run()).toBe(true);
  });

  it('guestGuard keeps signed-in people off /login', async () => {
    const { auth, ctrl } = setup();
    const run = () => TestBed.runInInjectionContext(() => guestGuard({} as never, {} as never));
    expect(run()).toBe(true);
    void firstValueFrom(auth.login('a@b.c', 'pw'));
    ctrl.expectOne(`${API_BASE}/auth/login`).flush(token('T'));
    expect(TestBed.inject(Router).serializeUrl(run() as UrlTree)).toBe('/patients');
  });
});
