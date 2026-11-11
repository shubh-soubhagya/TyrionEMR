import asyncio

from app.services.password_hasher import PasswordHasherService
from tests.conftest import make_settings


async def test_hash_is_argon2id_and_verifies():
    h = PasswordHasherService(make_settings())
    encoded = await h.hash("Kidney2026care")
    assert encoded.startswith("$argon2id$")
    assert await h.verify(encoded, "Kidney2026care") is True
    assert await h.verify(encoded, "wrong-password1") is False


async def test_verify_garbage_hash_is_false_not_error():
    h = PasswordHasherService(make_settings())
    assert await h.verify("not-a-hash", "whatever1234") is False


async def test_rehash_detected_when_cost_changes():
    old = await PasswordHasherService(make_settings(argon2_time_cost=1)).hash("Kidney2026care")
    assert PasswordHasherService(make_settings(argon2_time_cost=2)).needs_rehash(old) is True
    assert PasswordHasherService(make_settings(argon2_time_cost=1)).needs_rehash(old) is False


async def test_dummy_verify_runs_and_returns_none():
    assert await PasswordHasherService(make_settings()).verify_dummy("x1234567890") is None


async def test_hashing_does_not_block_the_event_loop():
    h = PasswordHasherService(make_settings(argon2_memory_kib=65536, argon2_time_cost=2))
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    t = asyncio.create_task(ticker())
    await h.hash("Kidney2026care")
    t.cancel()
    assert ticks >= 2   # the loop kept running while argon2 worked in a thread
