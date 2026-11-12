from app.domain.clock import FakeClock
from app.domain.token_bucket import take
from app.routing.policies import Policy
from app.services.rate_limiter import DisabledRateLimiter, InMemoryRateLimiter

LOGIN = Policy("auth_login", "ip", 10, 5)


def test_burst_then_refused_with_retry_after():
    b = None
    for i in range(5):
        b, d = take(b, 0.0, 5, 10 / 60)
        assert d.allowed and d.remaining == 4 - i
    b, d = take(b, 0.0, 5, 10 / 60)
    assert not d.allowed and d.retry_after_s == 6          # LLD §21.1 worked example


def test_refill_lets_one_more_through_then_refuses_again():
    b = None
    for _ in range(5):
        b, _d = take(b, 0.0, 5, 10 / 60)
    b, d = take(b, 6.0, 5, 10 / 60)
    assert d.allowed
    b, d = take(b, 6.0, 5, 10 / 60)
    assert not d.allowed


def test_never_exceeds_capacity():
    b, _ = take(None, 0.0, 3, 1.0)
    b, d = take(b, 10_000.0, 3, 1.0)
    assert d.allowed and d.remaining == 2


def test_clock_going_backwards_does_not_mint_tokens():
    b, _ = take(None, 100.0, 1, 1.0)
    _, d = take(b, 50.0, 1, 1.0)
    assert not d.allowed


def test_limiter_keys_are_independent_per_policy_and_per_key():
    clock = FakeClock()
    rl = InMemoryRateLimiter(clock, 1000)
    for _ in range(5):
        assert rl.check(LOGIN, "1.1.1.1").allowed
    assert not rl.check(LOGIN, "1.1.1.1").allowed
    assert rl.check(LOGIN, "2.2.2.2").allowed
    assert rl.check(Policy("ip_global", "ip", 1200, 200), "1.1.1.1").allowed


def test_limiter_refills_with_the_fake_clock():
    clock = FakeClock()
    rl = InMemoryRateLimiter(clock, 1000)
    for _ in range(5):
        rl.check(LOGIN, "ip")
    assert not rl.check(LOGIN, "ip").allowed
    clock.advance(6)
    assert rl.check(LOGIN, "ip").allowed


def test_limiter_is_lru_capped():
    rl = InMemoryRateLimiter(FakeClock(), 3)
    for i in range(10):
        rl.check(LOGIN, f"k{i}")
    assert len(rl) == 3


def test_evicted_key_starts_fresh_and_recent_key_survives():
    rl = InMemoryRateLimiter(FakeClock(), 2)
    for _ in range(5):
        rl.check(LOGIN, "hot")
    rl.check(LOGIN, "a")
    rl.check(LOGIN, "hot")            # touch: hot becomes most recent
    rl.check(LOGIN, "b")              # evicts "a"
    assert not rl.check(LOGIN, "hot").allowed


def test_disabled_limiter_always_allows():
    rl = DisabledRateLimiter()
    assert all(rl.check(LOGIN, "x").allowed for _ in range(100))
