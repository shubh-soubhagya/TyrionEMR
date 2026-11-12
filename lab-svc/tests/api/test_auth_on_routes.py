"""LLD B13.2 "Auth": every business route rejects a missing, wrong-audience, expired or non-clinician token.

The route list comes from the application itself, so a route added later cannot ship without a token check.
"""
from __future__ import annotations

import uuid

import httpx
import pytest

pytestmark = pytest.mark.api
OPEN = {"/health", "/ready", "/metrics"}


def business_routes(app) -> list[tuple[str, str]]:
    """Every business operation, read from the OpenAPI document (FastAPI wraps included routers)."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        if path not in OPEN and (path.startswith("/labs") or path.startswith("/internal/labs")):
            out += [(method.upper(), path) for method in sorted(ops)]
    return out


def fill(path: str) -> str:
    return (path.replace("{patient_id}", str(uuid.uuid4())).replace("{result_id}", str(uuid.uuid4())))


def test_the_route_inventory_is_what_the_lld_lists(app) -> None:
    got = {(m, p) for m, p in business_routes(app)}
    assert got == {
        ("GET", "/labs/tests"), ("POST", "/labs/patients/{patient_id}/reports"),
        ("GET", "/labs/patients/{patient_id}/results"), ("GET", "/labs/patients/{patient_id}/trends"),
        ("GET", "/labs/patients/{patient_id}/latest"), ("GET", "/labs/summary"),
        ("POST", "/labs/results/{result_id}/correct"),
        ("GET", "/internal/labs/patients/{patient_id}/results"), ("GET", "/internal/labs/patients/{patient_id}/trends"),
        ("GET", "/internal/labs/patients/{patient_id}/latest"), ("GET", "/internal/labs/status"),
    }


@pytest.fixture
def routes(app) -> list[tuple[str, str]]:
    found = business_routes(app)
    assert len(found) == 11                   # a vacuous loop below would prove nothing
    return found


async def call(client: httpx.AsyncClient, method: str, path: str, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return await client.request(method, fill(path), headers=headers, json={} if method == "POST" else None)


async def test_no_token_is_401_everywhere(client, routes) -> None:
    for method, path in routes:
        r = await call(client, method, path, None)
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED", (method, path)


async def test_wrong_audience_and_expired_tokens_are_401_everywhere(client, routes, sign) -> None:
    for token in (sign(aud="someone-else"), sign(ttl=-3600), sign(iss="evil")):
        for method, path in routes:
            assert (await call(client, method, path, token)).status_code == 401, (method, path)


async def test_a_non_clinician_role_is_403_everywhere(client, routes, sign) -> None:
    for role in ("admin", "patient", ""):
        for method, path in routes:
            r = await call(client, method, path, sign(role=role))
            assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN", (role, method, path)


async def test_ops_routes_are_open(client) -> None:
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/metrics")).status_code == 200


async def test_a_valid_clinician_token_gets_past_authentication(client, routes, sign) -> None:
    for method, path in routes:
        r = await call(client, method, path, sign())
        assert r.status_code not in (401, 403), (method, path, r.status_code)
