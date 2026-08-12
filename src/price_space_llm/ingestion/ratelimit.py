"""Token-bucket rate limiter for INGESTION_CALL_ISSUED cadence.

Layer-4 cadence rule (v0.2): `INGESTION_CALL_ISSUED <= 75 per minute per
Source`. This module implements the enforcement at the call site.

The bucket refills continuously at `capacity / period_seconds` tokens per
second; `acquire()` returns immediately if a token is available, else
raises `RateLimitExhausted`. Callers translate the raise into a
SOURCE_FALLBACK_TRIGGERED emit (reason=rate_limit_exhausted) or wait.

Wall-clock is injected as a callable so tests can drive the bucket
without sleeping.
"""

from __future__ import annotations

from collections.abc import Callable


class RateLimitExhausted(RuntimeError):
    """Token bucket is empty; no fetch allowed at this moment."""


class TokenBucket:
    def __init__(
        self,
        capacity: int,
        period_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        if period_seconds <= 0:
            raise ValueError(f"period_seconds must be > 0, got {period_seconds}")
        self._capacity = capacity
        self._refill_rate = capacity / period_seconds
        self._clock = clock
        self._tokens: float = float(capacity)
        self._last_refill = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    def acquire(self) -> None:
        """Consume one token or raise `RateLimitExhausted`."""
        self._refill()
        if self._tokens < 1.0:
            raise RateLimitExhausted(
                f"bucket empty: {self._tokens:.3f} tokens; "
                f"capacity={self._capacity}, refill_rate={self._refill_rate:.3f}/s"
            )
        self._tokens -= 1.0

    def tokens_available(self) -> float:
        self._refill()
        return self._tokens
