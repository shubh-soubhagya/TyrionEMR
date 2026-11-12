import httpx

from app.services.proxy import _body
from tests.proxy_harness import _Stream


async def test_large_body_is_relayed_unchanged(gw):
    client, ups = gw
    payload = bytes(range(256)) * 20_000                                  # about 5 MB
    ups["lab"]._handler = lambda req: httpx.Response(
        200, content=payload, headers={"Content-Type": "application/octet-stream"})
    r = await client.get("/api/labs/export")
    assert r.status_code == 200 and r.content == payload
    assert r.headers["content-length"] == str(len(payload))


async def test_gateway_asks_upstreams_for_identity_encoding(gw):
    client, ups = gw
    await client.get("/api/patients", headers={"Accept-Encoding": "gzip"})
    assert ups["patient"].last.headers["accept-encoding"] == "identity"      # nothing is compressed (ADR-G12)


async def test_upstream_stream_is_closed_after_a_normal_relay(gw):
    client, ups = gw
    holder = {}

    def handler(req):
        holder["stream"] = _Stream(b"x" * 1000)
        return httpx.Response(200, headers={"Content-Type": "application/json"}, stream=holder["stream"])

    ups["patient"]._handler = handler
    await client.get("/api/patients")
    assert holder["stream"].closed


async def test_upstream_is_released_when_the_client_disconnects_mid_stream():
    """Starlette cancels the body generator on disconnect; finally must close the upstream response."""
    stream = _Stream(b"x" * 300_000, chunk=1000)
    upstream = httpx.Response(200, stream=stream)
    gen = _body(upstream)
    assert await gen.__anext__() == b"x" * 1000                           # client reads one chunk, then goes away
    await gen.aclose()
    assert stream.closed


async def test_stream_error_after_headers_is_not_hidden():
    class Boom(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            raise httpx.ReadError("reset by peer")

    gen = _body(httpx.Response(200, stream=Boom()))
    assert await gen.__anext__() == b"partial"
    try:
        await gen.__anext__()
    except httpx.ReadError:
        pass
    else:
        raise AssertionError("a mid-stream failure must close the connection, not look like a complete body")
