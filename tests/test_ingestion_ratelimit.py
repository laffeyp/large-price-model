"""Tests for the token-bucket rate limiter."""

from __future__ import annotations

import pytest

from price_space_llm.ingestion.ratelimit import (
    RateLimitExhausted,
    TokenBucket,
)


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_bucket_starts_full_and_acquires_capacity_times():
    clock = FakeClock()
    bucket = TokenBucket(capacity=5, period_seconds=60.0, clock=clock)
    for _ in range(5):
        bucket.acquire()
    assert bucket.tokens_available() < 1.0


def test_bucket_raises_when_exhausted():
    clock = FakeClock()
    bucket = TokenBucket(capacity=3, period_seconds=60.0, clock=clock)
    for _ in range(3):
        bucket.acquire()
    with pytest.raises(RateLimitExhausted):
        bucket.acquire()


def test_bucket_refills_over_time():
    clock = FakeClock(0.0)
    bucket = TokenBucket(capacity=60, period_seconds=60.0, clock=clock)  # 1 token/sec
    for _ in range(60):
        bucket.acquire()
    with pytest.raises(RateLimitExhausted):
        bucket.acquire()
    clock.t = 5.0
    for _ in range(5):
        bucket.acquire()
    with pytest.raises(RateLimitExhausted):
        bucket.acquire()


def test_bucket_caps_refill_at_capacity():
    clock = FakeClock(0.0)
    bucket = TokenBucket(capacity=10, period_seconds=1.0, clock=clock)
    bucket.acquire()
    clock.t = 1_000_000.0  # very long time passes
    assert bucket.tokens_available() == pytest.approx(10.0)


def test_bucket_rejects_nonpositive_capacity():
    with pytest.raises(ValueError, match="capacity"):
        TokenBucket(capacity=0, period_seconds=60.0, clock=FakeClock())


def test_bucket_rejects_nonpositive_period():
    with pytest.raises(ValueError, match="period_seconds"):
        TokenBucket(capacity=10, period_seconds=0.0, clock=FakeClock())


# acquire_blocking (Sprint 046) --------------------------------------------


def test_acquire_blocking_returns_immediately_when_tokens_available():
    """Sprint 046: blocking mode. Bucket with tokens hands them out with zero sleep."""
    clock = FakeClock(0.0)
    bucket = TokenBucket(capacity=5, period_seconds=60.0, clock=clock)
    sleeps: list[float] = []
    for _ in range(5):
        bucket.acquire_blocking(sleep=sleeps.append)
    assert sleeps == [0.0] * 0 or all(s == 0 for s in sleeps)  # no waits triggered


def test_acquire_blocking_waits_when_bucket_empty():
    """Empty bucket: acquire_blocking sleeps for the exact refill interval, then acquires."""
    clock = FakeClock(0.0)
    bucket = TokenBucket(capacity=2, period_seconds=60.0, clock=clock)
    # refill_rate = 2 / 60 = 0.0333/s; each token takes 30s.
    sleeps: list[float] = []

    def fake_sleep(s: float) -> None:
        sleeps.append(s)
        clock.t += s  # advance the clock to simulate real sleep

    bucket.acquire_blocking(sleep=fake_sleep)
    bucket.acquire_blocking(sleep=fake_sleep)
    # Third call: bucket empty; needs to wait 30s for one token.
    bucket.acquire_blocking(sleep=fake_sleep)
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(30.0, abs=0.01)


def test_acquire_blocking_sustains_configured_rate():
    """Long sequence at capacity respects the refill rate; total waits sum
    correctly across a burst that exceeds the bucket."""
    clock = FakeClock(0.0)
    bucket = TokenBucket(capacity=10, period_seconds=60.0, clock=clock)  # 10/min = 6s/token
    sleeps: list[float] = []

    def fake_sleep(s: float) -> None:
        sleeps.append(s)
        clock.t += s

    # Burn the initial capacity, then fire 10 more; each after burst should sleep ~6s.
    for _ in range(10):
        bucket.acquire_blocking(sleep=fake_sleep)
    assert not sleeps
    for _ in range(10):
        bucket.acquire_blocking(sleep=fake_sleep)
    # 10 waits, each about 6 seconds.
    assert len(sleeps) == 10
    assert all(5.9 < s < 6.1 for s in sleeps), f"sleeps: {sleeps}"
