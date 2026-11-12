"""Shared fixtures. Tokens are signed by a throwaway RSA key whose public half is served through a stub JWKS fetch,
so the real JwksCache / verify_access_token path runs end to end. patient-svc and lab-svc are faked with respx
(the real clients, the real HTTP stack) from the synthetic seed in tests/fixtures/seed.py."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import load_dotenv
from fastapi import FastAPI

from app.core.clock import FakeClock
from app.core.config import Settings
from app.core.jwks import JwksCache, _b64u_uint, thumbprint_kid
from app.main import create_app
from tests.fixtures import seed

load_dotenv()          # picks up AI_TEST_DATABASE_URL from .env when running on the host

ISSUER, AUDIENCE = "nephro-auth", "nephro-api"
PATIENT_URL, LAB_URL = "http://patient-svc:8000", "http://lab-svc:8000"


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        ai_database_url=os.environ.get("AI_TEST_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x"),
        app_env="test", jwks_min_refetch_s=0.0, upstream_retries=0, llm_provider="mock", _env_file=None)
    base.update(overrides)
    return Settings(**base)


def jwk_for(key: rsa.RSAPrivateKey) -> dict[str, str]:
    pub = key.public_key()
    nums = pub.public_numbers()
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": thumbprint_kid(pub),
            "n": _b64u_uint(nums.n), "e": _b64u_uint(nums.e)}


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(seed.NOW)


@pytest.fixture
def sign(rsa_key: rsa.RSAPrivateKey, clock: FakeClock) -> Callable[..., str]:
    kid = thumbprint_kid(rsa_key.public_key())

    def _sign(*, role: str = "clinician", sub: str | None = None, iss: str = ISSUER, aud: str = AUDIENCE,
              ttl: int = 900, key: rsa.RSAPrivateKey | None = None, drop: tuple[str, ...] = ()) -> str:
        now = int(clock().timestamp())
        claims: dict[str, Any] = {"sub": sub or str(uuid.uuid4()), "role": role, "iss": iss, "aud": aud,
                                  "iat": now, "nbf": now, "exp": now + ttl}
        for k in drop:
            claims.pop(k, None)
        return jwt.encode(claims, key or rsa_key, algorithm="RS256", headers={"kid": kid})

    return _sign


@pytest.fixture
def jwks(rsa_key: rsa.RSAPrivateKey, settings: Settings) -> JwksCache:
    async def fetch() -> dict:
        return {"keys": [jwk_for(rsa_key)]}

    return JwksCache(fetch, settings, mono=time.monotonic)


class Upstreams:
    """patient-svc + lab-svc, served from the seed by respx. Records calls so tests can count upstream reads."""

    def __init__(self, router: respx.MockRouter, b20_fields: bool = True) -> None:
        self.patients = seed.all_patients(b20_fields=b20_fields)
        self.by_id = {str(p["id"]): p for p in self.patients}
        self.calls: list[tuple[str, dict]] = []     # (path, headers)
        self.fail: dict[str, int] = {}               # path prefix -> status to answer
        self.delay_s = 0.0
        r = router
        r.get(url__regex=rf"{PATIENT_URL}/internal/patients/charts").mock(side_effect=self._charts)
        r.get(url__regex=rf"{PATIENT_URL}/internal/patients/[0-9a-f-]{{36}}/(?:basic|chart)").mock(
            side_effect=self._patient)
        r.get(url__regex=rf"{LAB_URL}/internal/labs/status").mock(side_effect=self._status)
        r.get(url__regex=rf"{LAB_URL}/internal/labs/patients/[0-9a-f-]{{36}}/(?:latest|trends)").mock(
            side_effect=self._lab)

    def _page(self, request: httpx.Request, items: list[dict], key: Callable[[dict], str]) -> httpx.Response:
        limit = int(request.url.params.get("limit", "200"))
        cursor = request.url.params.get("cursor")
        ordered = sorted(items, key=key)
        if cursor:
            ordered = [i for i in ordered if key(i) > cursor]
        page, rest = ordered[:limit], ordered[limit:]
        return httpx.Response(200, json={"items": page, "next_cursor": key(page[-1]) if rest else None})

    async def _record(self, request: httpx.Request) -> httpx.Response | None:
        self.calls.append((request.url.path, dict(request.headers)))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        for prefix, status in self.fail.items():
            if request.url.path.startswith(prefix):
                return httpx.Response(status, json={"error": {"code": "X"}})
        return None

    async def _charts(self, request: httpx.Request) -> httpx.Response:
        return await self._record(request) or self._page(request, [p["bulk"] for p in self.patients], lambda i: i["id"])

    async def _status(self, request: httpx.Request) -> httpx.Response:
        rows = [p["status"] for p in self.patients if p["status"]]
        return await self._record(request) or self._page(request, rows, lambda i: i["patient_id"])

    async def _patient(self, request: httpx.Request) -> httpx.Response:
        if (failed := await self._record(request)) is not None:
            return failed
        _, pid, what = request.url.path.rsplit("/", 2)
        p = self.by_id.get(pid)
        if p is None:
            return httpx.Response(404, json={"error": {"code": "PATIENT_NOT_FOUND"}})
        if what == "basic":
            c = p["chart"]["patient"]
            return httpx.Response(200, json={"id": pid, "sex": c["sex"], "date_of_birth": c["date_of_birth"]})
        return httpx.Response(200, json=p["chart"])

    async def _lab(self, request: httpx.Request) -> httpx.Response:
        if (failed := await self._record(request)) is not None:
            return failed
        parts = request.url.path.split("/")
        p = self.by_id.get(parts[-2])
        if p is None:
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
        return httpx.Response(200, json=p[parts[-1]])

    def calls_to(self, fragment: str) -> int:
        return sum(1 for path, _ in self.calls if fragment in path)


@pytest.fixture
def upstream_router() -> respx.MockRouter:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture
def upstreams(upstream_router: respx.MockRouter) -> Upstreams:
    return Upstreams(upstream_router)


@pytest.fixture
def app(settings: Settings, clock: FakeClock, jwks: JwksCache, upstreams: Upstreams) -> FastAPI:
    return create_app(settings, clock=clock, jwks=jwks)


@pytest.fixture
async def client(app: FastAPI, jwks: JwksCache, sign: Callable[..., str]) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        await jwks.refresh("test")
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     headers={"Authorization": f"Bearer {sign()}"}) as c:
            yield c
