"""JWKS cache: rotation, outage, unknown kid throttling (LLD A7, phase 1)."""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.jwks import JwksCache, parse_jwks, thumbprint_kid
from tests.conftest import jwk_for, make_settings


def new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Source:
    def __init__(self, *keys):
        self.keys, self.fail, self.calls = list(keys), False, 0

    async def __call__(self):
        self.calls += 1
        if self.fail:
            raise ConnectionError("down")
        return {"keys": [jwk_for(k) for k in self.keys]}


class Mono:
    t = 0.0

    def __call__(self):
        return self.t


async def test_keys_are_loaded_and_found_by_kid():
    k = new_key()
    cache = JwksCache(Source(k), make_settings())
    assert await cache.refresh("t")
    assert await cache.key_for(thumbprint_kid(k.public_key())) is not None and cache.key_count == 1


async def test_rotation_replaces_the_key_set():
    old, new = new_key(), new_key()
    src, mono = Source(old), Mono()
    cache = JwksCache(src, make_settings(jwks_min_refetch_s=0), mono)
    await cache.refresh("t")
    src.keys = [new]
    assert await cache.key_for(thumbprint_kid(new.public_key())) is not None   # unknown kid triggers a refetch
    assert await cache.key_for(thumbprint_kid(old.public_key())) is None       # replaced, not merged


async def test_outage_keeps_the_last_good_keys():
    k = new_key()
    src, mono = Source(k), Mono()
    cache = JwksCache(src, make_settings(jwks_min_refetch_s=0), mono)
    await cache.refresh("t")
    src.fail = True
    assert not await cache.refresh("scheduled")
    assert await cache.key_for(thumbprint_kid(k.public_key())) is not None


async def test_keys_older_than_max_stale_are_no_longer_trusted():
    k = new_key()
    src, mono = Source(k), Mono()
    cache = JwksCache(src, make_settings(jwks_max_stale_s=100), mono)
    await cache.refresh("t")
    src.fail = True
    mono.t = 101
    assert cache.key_count == 0 and await cache.key_for(thumbprint_kid(k.public_key())) is None


async def test_unknown_kid_refetch_is_throttled():
    k = new_key()
    src, mono = Source(k), Mono()
    cache = JwksCache(src, make_settings(jwks_min_refetch_s=30), mono)
    await cache.refresh("t")
    mono.t = 31
    calls = src.calls
    for _ in range(5):
        assert await cache.key_for("nope") is None
    assert src.calls - calls == 1                           # one refetch, then throttled
    mono.t = 62
    await cache.key_for("nope")
    assert src.calls - calls == 2


def test_weak_or_mismatched_keys_are_rejected():
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    good = jwk_for(new_key())
    assert parse_jwks({"keys": [jwk_for(weak), good | {"kid": "forged"}, {"kty": "oct"}]}) == {}
