import asyncio

import pytest

from app.core.config import Settings
from app.domain.clock import FakeClock
from app.services.jwks_cache import JwksCache, parse_jwks, thumbprint_kid
from tests.jwt_helpers import jwk_of, jwks_doc, kid_of, new_key

S = Settings(_env_file=None)


class Upstream:
    """A fake JWKS endpoint: scripted documents or failures, and a call counter."""

    def __init__(self, *docs):
        self.docs = list(docs)
        self.calls = 0
        self.delay = 0.0

    async def __call__(self):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        doc = self.docs[min(self.calls - 1, len(self.docs) - 1)]
        if isinstance(doc, Exception):
            raise doc
        return doc


@pytest.fixture(scope="module")
def k1():
    return new_key()


@pytest.fixture(scope="module")
def k2():
    return new_key()


@pytest.fixture
def clock():
    return FakeClock()


def cache(fetch, clock, **settings):
    return JwksCache(fetch, Settings(_env_file=None, **settings), clock)


async def test_first_fetch_fails_then_succeeds(k1, clock):
    up = Upstream(ConnectionError("down"), jwks_doc(k1))
    c = cache(up, clock)
    assert await c.key_for(kid_of(k1)) is None                    # nothing yet
    assert not c.fresh and c.key_count == 0
    clock.advance(31)                                              # past the refetch spacing
    assert await c.key_for(kid_of(k1)) is not None
    assert c.fresh and c.key_count == 1


async def test_rotation_one_refetch_and_new_key_verifies(k1, k2, clock):
    up = Upstream(jwks_doc(k1), jwks_doc(k1, k2))
    c = cache(up, clock)
    assert await c.refresh("startup")
    assert await c.key_for(kid_of(k1)) is not None and up.calls == 1     # cached: no fetch
    clock.advance(31)
    assert await c.key_for(kid_of(k2)) is not None
    assert up.calls == 2 and c.key_count == 2


async def test_hundred_concurrent_unknown_kids_make_exactly_one_fetch(k1, clock):
    up = Upstream(jwks_doc(k1))
    up.delay = 0.02
    c = cache(up, clock)
    await c.refresh("startup")
    up.calls = 0
    clock.advance(31)
    results = await asyncio.gather(*(c.key_for("unknown-kid") for _ in range(100)))
    assert up.calls == 1 and all(r is None for r in results)


async def test_random_kid_every_request_is_one_fetch_per_30s(k1, clock):
    up = Upstream(jwks_doc(k1))
    c = cache(up, clock)
    await c.refresh("startup")
    up.calls = 0
    clock.advance(31)
    for i in range(50):
        await c.key_for(f"random-{i}")
    assert up.calls == 1
    clock.advance(31)
    await c.key_for("another")
    assert up.calls == 2


async def test_failed_fetch_keeps_the_old_keys(k1, clock):
    up = Upstream(jwks_doc(k1), TimeoutError("slow"))
    c = cache(up, clock)
    await c.refresh("startup")
    clock.advance(400)
    assert not await c.refresh("scheduled")
    assert await c.key_for(kid_of(k1)) is not None and c.fresh


async def test_keys_expire_after_the_staleness_cap(k1, clock):
    up = Upstream(jwks_doc(k1), ConnectionError("down"))
    c = cache(up, clock)
    await c.refresh("startup")
    clock.advance(86_400)
    assert c.fresh                                                 # exactly at the cap
    clock.advance(1)
    assert not c.fresh and c.key_count == 0
    assert await c.key_for(kid_of(k1)) is None                     # retired key cannot verify forever


async def test_successful_fetch_replaces_the_keyset(k1, k2, clock):
    """Rotation step 6: auth-svc stops publishing K1, the next refresh drops it."""
    up = Upstream(jwks_doc(k1, k2), jwks_doc(k2))
    c = cache(up, clock)
    await c.refresh("startup")
    clock.advance(300)
    await c.refresh("scheduled")
    assert await c.key_for(kid_of(k2)) is not None
    clock.advance(31)
    assert await c.key_for(kid_of(k1)) is None


async def test_empty_or_unusable_keyset_is_a_failure_and_keeps_old_keys(k1, clock):
    up = Upstream(jwks_doc(k1), {"keys": []}, {"nope": 1})
    c = cache(up, clock)
    await c.refresh("startup")
    assert not await c.refresh("scheduled")
    assert not await c.refresh("scheduled")
    assert c.key_count == 1


async def test_age(k1, clock):
    c = cache(Upstream(jwks_doc(k1)), clock)
    assert c.age_s() is None
    await c.refresh("startup")
    clock.advance(42)
    assert c.age_s() == 42


# ---- parse_jwks: what is ignored --------------------------------------------------------------
def test_parse_accepts_a_good_key(k1):
    assert list(parse_jwks(jwks_doc(k1), require_thumbprint=True)) == [kid_of(k1)]


def test_thumbprint_matches_rfc7638_shape(k1):
    kid = thumbprint_kid(k1.public_key())
    assert len(kid) == 43 and "=" not in kid


def test_kid_that_is_not_the_thumbprint_is_ignored(k1, caplog):
    doc = {"keys": [jwk_of(k1, kid="chosen-by-someone")]}
    assert parse_jwks(doc, require_thumbprint=True) == {}
    assert any(getattr(r, "reason", "") == "kid_mismatch" for r in caplog.records)


def test_thumbprint_check_can_be_switched_off(k1):
    doc = {"keys": [jwk_of(k1, kid="chosen")]}
    assert list(parse_jwks(doc, require_thumbprint=False)) == ["chosen"]


def test_small_key_is_ignored(caplog):
    small = new_key(1024)
    assert parse_jwks(jwks_doc(small), require_thumbprint=True) == {}
    assert any(getattr(r, "reason", "") == "too_small" for r in caplog.records)


@pytest.mark.parametrize("override", [{"alg": "HS256"}, {"use": "enc"}, {"kty": "EC"}])
def test_wrong_alg_use_or_type_is_ignored(k1, override):
    assert parse_jwks({"keys": [jwk_of(k1, **override)]}, require_thumbprint=True) == {}


def test_malformed_key_is_ignored_not_fatal(k1):
    doc = {"keys": [{"kty": "RSA", "kid": "x", "n": "!!!", "e": "AQAB"}, jwk_of(k1)]}
    assert list(parse_jwks(doc, require_thumbprint=True)) == [kid_of(k1)]


@pytest.mark.parametrize("doc", [None, [], {"keys": "x"}, "str", {}])
def test_not_a_jwks_document(doc):
    with pytest.raises(ValueError):
        parse_jwks(doc, require_thumbprint=True)
