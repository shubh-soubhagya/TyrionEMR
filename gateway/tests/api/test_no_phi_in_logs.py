"""Never log query strings, header values, cookies, tokens or bodies (CLAUDE rules, LLD §10)."""
import logging

import httpx

from app.core.logging import JsonFormatter

SECRETS = {
    "query": "q=Ramesh+Kulkarni-SECRETQUERY",
    "cookie": "nephro_rt=SECRETCOOKIE",
    "body": b'{"password":"SECRETPASSWORD","name":"SECRETNAME"}',
    "header": "SECRETHEADERVALUE",
}


def everything_logged(caplog) -> str:
    fmt = JsonFormatter("gateway")
    return "\n".join(fmt.format(r) for r in caplog.records)


async def test_nothing_sensitive_is_logged_on_a_proxied_request(pipe, caplog):
    token = pipe.token()
    with caplog.at_level(logging.DEBUG):
        await pipe.client.post(
            "/api/patients?" + SECRETS["query"], content=SECRETS["body"],
            headers={"Authorization": f"Bearer {token}", "Cookie": SECRETS["cookie"],
                     "X-Custom": SECRETS["header"], "Content-Type": "application/json"})
    logged = everything_logged(caplog)
    assert "http.request" in logged                                         # the access line exists
    for secret in ("SECRETQUERY", "Kulkarni", "SECRETCOOKIE", "SECRETPASSWORD", "SECRETNAME", "SECRETHEADERVALUE",
                   token, "Bearer"):
        assert secret not in logged, secret


async def test_nothing_sensitive_is_logged_on_rejections(pipe, caplog):
    token = pipe.token(aud="wrong")
    with caplog.at_level(logging.DEBUG):
        await pipe.client.get("/api/patients?" + SECRETS["query"], headers={"Authorization": f"Bearer {token}"})
        await pipe.client.get("/api/internal/x?" + SECRETS["query"])
        await pipe.client.get("/api/patients?" + SECRETS["query"])
    logged = everything_logged(caplog)
    assert "SECRETQUERY" not in logged and token not in logged
    assert '"reason":"invalid"' in logged                                    # the reason only


async def test_upstream_errors_do_not_log_urls_or_messages(pipe, caplog):
    p = pipe

    def boom(request):
        raise httpx.ConnectError("could not connect to http://patient-svc:8000/patients?q=SECRETQUERY")

    p.ups["patient"]._handler = boom
    with caplog.at_level(logging.DEBUG):
        r = await p.client.get("/api/patients?q=SECRETQUERY", headers=p.auth)
    assert r.status_code == 502
    logged = everything_logged(caplog)
    assert "SECRETQUERY" not in logged and "gateway.upstream.error" in logged


async def test_httpx_request_lines_are_silenced(pipe, caplog):
    """httpx logs 'HTTP Request: GET <full url>' at INFO, which would include the query string."""
    with caplog.at_level(logging.DEBUG):
        await pipe.client.get("/api/patients?" + SECRETS["query"], headers=pipe.auth)
    assert not [r for r in caplog.records if r.name.startswith(("httpx", "httpcore"))
                and "SECRETQUERY" in r.getMessage()]


async def test_a_bug_logs_the_exception_type_never_its_message(pipe, caplog):
    def explode(*a, **k):
        raise RuntimeError("SECRETBUGDETAIL patient name")

    pipe.app.state.pipeline._proxy.forward = explode
    with caplog.at_level(logging.DEBUG):
        r = await pipe.client.get("/api/patients", headers=pipe.auth)
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "SECRETBUGDETAIL" not in everything_logged(caplog) and "SECRETBUGDETAIL" not in r.text
