from tests.asgi_raw import call


def auth_headers(pipe, **extra):
    return [*pipe.auth.items(), *extra.items()]


async def test_413_by_declared_content_length_on_a_normal_route(make_pipe):
    p = await make_pipe(max_body_bytes=1000)
    r = await p.client.post("/api/patients", content=b"x" * 1001, headers=p.auth)
    err = r.json()["error"]
    assert r.status_code == 413 and err["code"] == "PAYLOAD_TOO_LARGE" and err["details"] == [{"limit_bytes": 1000}]
    assert not p.ups["patient"].requests


async def test_exactly_the_limit_is_accepted(make_pipe):
    p = await make_pipe(max_body_bytes=1000)
    assert (await p.client.post("/api/patients", content=b"x" * 1000, headers=p.auth)).status_code == 200


async def test_413_by_streamed_size_without_content_length(make_pipe):
    p = await make_pipe(max_body_bytes=1000)
    r = await call(p.app, "POST", "/api/patients", headers=auth_headers(p, **{"transfer-encoding": "chunked"}),
                   body_chunks=[b"x" * 600, b"x" * 600])
    assert r.status == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert not p.ups["patient"].requests


async def test_chunked_body_under_the_limit_is_buffered_and_sent_with_an_exact_length(make_pipe):
    p = await make_pipe(max_body_bytes=1000)
    r = await call(p.app, "POST", "/api/patients", headers=auth_headers(p, **{"transfer-encoding": "chunked"}),
                   body_chunks=[b"abc", b"def"])
    assert r.status == 200
    sent = p.ups["patient"].last
    assert sent.content == b"abcdef" and sent.headers["content-length"] == "6"
    assert "transfer-encoding" not in sent.headers                        # never forwarded (LLD §8.8)


async def test_auth_routes_have_the_small_16kib_limit_even_though_they_are_public(pipe):
    big = b"x" * (16 * 1024 + 1)
    r = await pipe.client.post("/api/auth/login", content=big)
    assert r.status_code == 413 and r.json()["error"]["details"] == [{"limit_bytes": 16384}]
    assert not pipe.ups["auth"].requests
    assert (await pipe.client.post("/api/auth/login", content=b"x" * 16384)).status_code == 200


async def test_other_routes_allow_more_than_16kib(pipe):
    assert (await pipe.client.post("/api/patients", content=b"x" * 20_000, headers=pipe.auth)).status_code == 200


async def test_non_numeric_content_length_is_400(pipe):
    r = await call(pipe.app, "POST", "/api/patients", headers=auth_headers(pipe, **{"content-length": "12abc"}),
                   body_chunks=[b"x"])
    assert r.status == 400 and r.json()["error"]["code"] == "BAD_REQUEST"
    assert not pipe.ups["patient"].requests


async def test_an_unauthenticated_caller_gets_401_before_any_body_is_read(make_pipe):
    p = await make_pipe(max_body_bytes=10)
    r = await p.client.post("/api/patients", content=b"x" * 5000)
    assert r.status_code == 401


async def test_get_without_a_body_sends_none_upstream(pipe):
    await pipe.client.get("/api/patients", headers=pipe.auth)
    assert pipe.ups["patient"].last.content == b""
