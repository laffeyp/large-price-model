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
