import pytest

from app.core.config import Settings
from app.core.guard import ConfigurationError, enforce_production, production_problems
from app.main import create_app

SAFE = dict(
    environment="production",
    cors_allowed_origins="https://emr.example.org",
    docs_enabled=False,
    metrics_enabled=True,
    metrics_token="not-a-real-token",
    rate_limit_enabled=True,
    hsts_enabled=True,
)


def prod(**overrides):
    return Settings(_env_file=None, **{**SAFE, **overrides})


def test_safe_production_config_has_no_problems():
    assert production_problems(prod()) == []


def test_development_is_never_checked():
    s = Settings(_env_file=None, environment="development", docs_enabled=True, hsts_enabled=False)
    assert production_problems(s) == []


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"cors_allowed_origins": "http://localhost:4200"}, "CORS_ALLOWED_ORIGINS"),
        ({"docs_enabled": True}, "DOCS_ENABLED"),
        ({"metrics_token": ""}, "METRICS_TOKEN"),
        ({"rate_limit_enabled": False}, "RATE_LIMIT_ENABLED"),
        ({"hsts_enabled": False}, "HSTS_ENABLED"),
    ],
)
def test_each_unsafe_setting_is_reported(overrides, fragment):
    problems = production_problems(prod(**overrides))
    assert len(problems) == 1 and fragment in problems[0]


def test_metrics_off_needs_no_token():
    assert production_problems(prod(metrics_enabled=False, metrics_token="")) == []


def test_all_problems_listed_together():
    s = prod(cors_allowed_origins="http://localhost:4200", docs_enabled=True, hsts_enabled=False)
    with pytest.raises(ConfigurationError) as exc:
        enforce_production(s)
    assert len(exc.value.problems) == 3


def test_create_app_refuses_unsafe_production():
    with pytest.raises(ConfigurationError):
        create_app(prod(docs_enabled=True))
