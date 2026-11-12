import pytest

from app.core.config import Settings
from tests.proxy_harness import Recorder, build_app, client_for


@pytest.fixture
def proxy_settings():
    def factory(**kw):
        base = {"auth_svc_url": "http://auth-svc:8000", "patient_svc_url": "http://patient-svc:8000",
                "lab_svc_url": "http://lab-svc:8000", "ai_svc_url": "http://ai-svc:8000"}
        return Settings(_env_file=None, environment="test", **{**base, **kw})

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
