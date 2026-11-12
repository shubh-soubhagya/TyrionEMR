import pytest

from app.core.config import Settings
from app.routing.paths import safe_segments
from app.routing.resolver import resolve
from app.routing.table import PUBLIC_ROUTES, build_routes

S = Settings(_env_file=None)
ROUTES = build_routes(S)
UUID = "0b7c1e2a-4d5f-4a6b-8c7d-0e1f2a3b5a69"


def r(method: str, raw: str):
    return resolve(method, raw, safe_segments(raw), ROUTES)


@pytest.mark.parametrize(
    ("raw", "upstream", "upstream_path"),
    [
        ("/api/auth/login", "auth", "/auth/login"),
        ("/api/patients", "patient", "/patients"),
        ("/api/patients/", "patient", "/patients/"),
        ("/api/encounters", "patient", "/encounters"),
        (f"/api/labs/patients/{UUID}/trends", "lab", f"/labs/patients/{UUID}/trends"),
        ("/api/ai/summaries/7", "ai", "/ai/summaries/7"),
        ("/api/insights/x", "ai", "/insights/x"),
    ],
)
def test_prefix_maps_to_upstream_and_only_api_is_stripped(raw, upstream, upstream_path):
    m = r("GET", raw)
    assert m is not None
    assert m.route.upstream == upstream
    assert m.upstream_path == upstream_path


@pytest.mark.parametrize(
    "raw",
    ["/api", "/api/", "/api/internal/patients/x/basic", "/api/internal", "/api/encountersX",
     "/api/patientsX", "/api/unknown", "/health", "/other/patients", "/"],
)
def test_unknown_and_internal_are_404(raw):
    assert r("GET", raw) is None


def test_whole_segment_match_not_string_prefix():
    assert r("GET", "/api/encounters") is not None
    assert r("GET", "/api/encounters2") is None


def test_insights_has_its_own_timeout_and_auth_its_own_body_limit_and_cookies():
    assert ROUTES["insights"].timeout_s == 10.0 and ROUTES["ai"].timeout_s == 5.0
    assert ROUTES["auth"].max_body_bytes == 16_384 and ROUTES["patients"].max_body_bytes == 1_048_576
    assert ROUTES["auth"].forward_cookies and ROUTES["auth"].pass_set_cookie
    assert not any(v.forward_cookies for k, v in ROUTES.items() if k != "auth")


@pytest.mark.parametrize("method_path", sorted(PUBLIC_ROUTES))
def test_public_routes(method_path):
    method, path = method_path
    m = r(method, path)
    assert m is not None and m.public


@pytest.mark.parametrize(
    ("method", "raw"),
    [("GET", "/api/auth/login"), ("GET", "/api/auth/me"), ("POST", "/api/auth/password"),
     ("POST", "/api/auth/login/"), ("POST", "/api/patients"), ("GET", "/api/auth/refresh")],
)
def test_everything_else_needs_a_token(method, raw):
    m = r(method, raw)
    assert m is not None and not m.public


def test_template_hides_ids():
    m = r("GET", f"/api/labs/patients/{UUID}/results")
    assert m is not None and m.template == "/api/labs/patients/{id}/results"


def test_each_service_prefix_owns_an_upstream_name():
    assert {v.upstream for v in ROUTES.values()} == {"auth", "patient", "lab", "ai"}
