import pytest

from app.core.config import Settings


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_defaults():
    s = make()
    assert s.service_name == "gateway"
    assert s.environment == "development"
    assert s.uvicorn_workers == 1
    assert s.cors_allowed_origins == ["http://localhost:4200"]
    assert s.max_url_bytes == 24_576


def test_only_auth_is_configured_by_default():
    # PATIENT_SVC_URL defaults to empty (the LLD); .env.example and compose set it
    assert make().upstream_urls() == {"auth": "http://auth-svc:8000", "patient": "", "lab": "", "ai": ""}


def test_jwks_url_derived_from_auth_url():
    assert make(auth_svc_url="http://x:1/").jwks_url == "http://x:1/.well-known/jwks.json"
    assert make(jwks_url="http://k/j").jwks_url == "http://k/j"


def test_csv_settings(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("READY_REQUIRES", "auth,patient")
    s = make()
    assert s.cors_allowed_origins == ["https://a.example", "https://b.example"]
    assert s.ready_requires == ["auth", "patient"]


@pytest.mark.parametrize("origins", ["*", "https://*.example.com"])
def test_wildcard_origin_rejected(origins):
    with pytest.raises(ValueError, match="exact origins"):
        make(cors_allowed_origins=origins)


def test_environment_must_be_known():
    with pytest.raises(ValueError):
        make(environment="staging")
