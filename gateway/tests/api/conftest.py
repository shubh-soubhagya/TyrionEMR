from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.domain.clock import FakeClock
from app.main import create_app
from tests.jwt_helpers import claims, jwks_doc, new_key, sign
from tests.proxy_harness import Recorder, build_app, client_for


@pytest.fixture
def proxy_settings():
    def factory(**kw):
        base = {"auth_svc_url": "http://auth-svc:8000", "patient_svc_url": "http://patient-svc:8000",
                "lab_svc_url": "http://lab-svc:8000", "ai_svc_url": "http://ai-svc:8000"}
        return Settings(_env_file=None, **{"environment": "test", **base, **kw})

    return factory


@pytest.fixture
def upstreams():
    return {name: Recorder() for name in ("auth", "patient", "lab", "ai")}


@pytest.fixture
async def gw(proxy_settings, upstreams):
    """(client, upstreams): a gateway app over four recording fake upstreams."""
    app, registry = build_app(proxy_settings(), upstreams)
    async with client_for(app) as client:
        yield client, upstreams
    await registry.aclose()


@pytest.fixture(scope="session")
def signing_key():
    return new_key()


@dataclass
class Pipe:
    """The real gateway (pipeline, auth, limits) over fake upstreams and a fake JWKS."""

    app: FastAPI
    client: httpx.AsyncClient
    ups: dict[str, Recorder]
    clock: FakeClock
    key: object
    settings: Settings

    def token(self, **over: object) -> str:
        return sign(self.key, claims(self.clock.wall(), **over))  # type: ignore[arg-type]

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.token()}


@pytest.fixture
async def make_pipe(proxy_settings, signing_key):
    opened: list[httpx.AsyncClient] = []

    async def factory(**settings: object) -> Pipe:
        clock = FakeClock()
        ups = {name: Recorder() for name in ("auth", "patient", "lab", "ai")}
        s = proxy_settings(**settings)

        async def jwks_fetch():
            return jwks_doc(signing_key)

        app = create_app(s, clock=clock, jwks_fetch=jwks_fetch,
                         transports={**{n: httpx.MockTransport(r) for n, r in ups.items()},
                                 "jwks": httpx.MockTransport(lambda request: httpx.Response(503))})
        await app.state.jwks.refresh("test")
        client = client_for(app)
        opened.append(client)
        return Pipe(app, client, ups, clock, signing_key, s)

    yield factory
    for c in opened:
        await c.aclose()


@pytest.fixture
async def pipe(make_pipe):
    return await make_pipe()
