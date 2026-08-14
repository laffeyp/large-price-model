"""IngestionClient facade over Fetcher(s).

Wires the five ingest-category tags the v0.2 vocabulary declares:
`INGESTION_CALL_ISSUED`, `INGESTION_CALL_CACHED`,
`SOURCE_FALLBACK_TRIGGERED`, `RAW_OBSERVATION_WRITTEN`, `REVISION_LANDED`.

Tech-arch §4.2 sketch: `IngestionClient` owns the rate limiter, the
cache, retry-with-backoff, and the primary-vs-fallback flow. Sprint
021 ships the rate limiter, the JSON cache, the fallback flow, and
the five emit sites. Retry-with-backoff is deferred to the sprint
that first hits a real 429; Parquet cache is deferred to the sprint
that first reads cached bytes into a Polars DataFrame. Both are
noted in `sprints/sprint-021-ingestion-client-facade.md § notes`.

The `RawFetcher` type — `Callable[[str, dict[str, Any]], dict[str, Any]]`
— is intentionally distinct from `probe.Fetcher` (coverage metadata).
The probe checks whether a channel is usable; the client fetches the
actual rows. Different callers, different signatures.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from price_space_llm.ingestion import cache as _cache
from price_space_llm.ingestion.ratelimit import (
    RateLimitExhausted,
    TokenBucket,
)
from price_space_llm.signals import StrictSignalEmitter

RawFetcher = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass(slots=True, frozen=True, kw_only=True)
class ObservationMetadata:
    """What the caller extracts from a vendor response to populate RAW_OBSERVATION_WRITTEN.

    value_time: the primary observation time (batch high-watermark for multi-row responses).
    known_at: when the caller learned about the data; for historical bars typically
        `value_time + 1 minute`, for streaming ingestion the wall-clock stamp at receipt.
    rows_written: the count of observations the response carried into the cache.
    """

    value_time: datetime
    known_at: datetime
    rows_written: int


ExtractMetadata = Callable[[dict[str, Any]], ObservationMetadata]


class IngestionCallFailed(RuntimeError):
    """Both primary and fallback failed (or primary failed with no fallback)."""


def _map_reason(exc: BaseException) -> str:
    """Map exception to the SOURCE_FALLBACK_TRIGGERED.reason enum.

    v0.2 enum: {frequency_unavailable, history_gap, rate_limit_exhausted,
    response_invalid}. RateLimitExhausted → rate_limit_exhausted; every
    other exception → response_invalid. Frequency/history reasons are
    semantic decisions the caller makes before calling; the client sees
    only exceptions from the wrapped fetcher.
    """
    if isinstance(exc, RateLimitExhausted):
        return "rate_limit_exhausted"
    return "response_invalid"


class IngestionClient:
    def __init__(
        self,
        primary: RawFetcher,
        primary_source: str,
        cache_dir: Path,
        emitter: StrictSignalEmitter,
        clock: Callable[[], float],
        fallback: RawFetcher | None = None,
        fallback_source: str | None = None,
        rate_limit_per_minute: int = 75,
        rate_limit_behavior: str = "raise",
        run_id: str = "unknown",
        git_sha: str = "0" * 40,
    ) -> None:
        if (fallback is None) != (fallback_source is None):
            raise ValueError("fallback and fallback_source must both be set or both None")
        if rate_limit_behavior not in ("raise", "block"):
            raise ValueError(
                f"rate_limit_behavior must be 'raise' or 'block'; got {rate_limit_behavior!r}"
            )
        self._primary = primary
        self._primary_source = primary_source
        self._fallback = fallback
        self._fallback_source = fallback_source
        self._cache_dir = cache_dir
        self._emitter = emitter
        self._run_id = run_id
        self._git_sha = git_sha
        self._rate_limit_behavior = rate_limit_behavior
        self._primary_bucket = TokenBucket(rate_limit_per_minute, 60.0, clock)
        self._fallback_bucket = (
            TokenBucket(rate_limit_per_minute, 60.0, clock) if fallback is not None else None
        )

    def _acquire(self, bucket: TokenBucket) -> None:
        """Acquire a token; block or raise per constructor config."""
        if self._rate_limit_behavior == "block":
            bucket.acquire_blocking()
        else:
            bucket.acquire()

    def call(
        self,
        *,
        channel: str,
        symbol: str,
        tool: str,
        params: dict[str, Any],
        extract_metadata: ExtractMetadata,
    ) -> dict[str, Any]:
        """Fetch, cache, emit. Returns the response payload dict.

        Cache-hit path: emits INGESTION_CALL_CACHED, returns cached payload,
        no fetcher call, no RAW_OBSERVATION_WRITTEN, no extract_metadata call.

        Cache-miss path: acquire rate token, call primary. On failure and
        with fallback set, emit SOURCE_FALLBACK_TRIGGERED, acquire fallback
        token, call fallback. Emit INGESTION_CALL_ISSUED for each fetcher
        invocation. On success, cache the payload, call extract_metadata to
        derive value_time / known_at / rows_written from the response, emit
        RAW_OBSERVATION_WRITTEN; if a prior cached copy existed with a
        different payload hash, also emit REVISION_LANDED.

        `extract_metadata` is caller-provided because the observation-time
        and row-count are properties of the vendor response, unknown until
        the response returns. Alpha-Vantage callers use
        `alphavantage.alphavantage_extract_metadata`; other providers
        supply their own extractor.
        """
        key = _cache.cache_key(tool, channel, symbol, params)
        params_hash = key

        path = _cache.cache_path(self._cache_dir, self._primary_source, tool, key)
        cached = _cache.read_with_freshness(path, tool)
        if cached is not None:
            self._emitter.emit(
                "INGESTION_CALL_CACHED",
                source=self._primary_source,
                tool=tool,
                params_hash=params_hash,
                channel=channel,
                symbol=symbol,
                cache_key=key,
            )
            return cached

        response, source_used, prior_hash = self._fetch_with_fallback(
            channel=channel,
            symbol=symbol,
            tool=tool,
            params=params,
            params_hash=params_hash,
            key=key,
        )

        target_path = _cache.cache_path(self._cache_dir, source_used, tool, key)
        new_hash_int = int(_cache.payload_hash(response)[:15], 16)
        prior_hash_int = int(prior_hash[:15], 16) if prior_hash is not None else 0
        _cache.write_with_meta(
            target_path,
            response,
            cache_dir=self._cache_dir,
            tool=tool,
            channel=channel,
            symbol=symbol,
            params=params,
            key=key,
            pulled_by_run_id=self._run_id,
            git_sha=self._git_sha,
        )

        meta = extract_metadata(response)
        self._emitter.emit(
            "RAW_OBSERVATION_WRITTEN",
            source=source_used,
            channel=channel,
            symbol=symbol,
            value_time=meta.value_time.isoformat(),
            released_at=meta.known_at.isoformat(),
            known_at=meta.known_at.isoformat(),
            rows_written=meta.rows_written,
            revision_id=new_hash_int,
        )

        if prior_hash is not None and prior_hash != _cache.payload_hash(response):
            self._emitter.emit(
                "REVISION_LANDED",
                source=source_used,
                channel=channel,
                symbol=symbol,
                value_time=meta.value_time.isoformat(),
                prior_revision_id=prior_hash_int,
                new_revision_id=new_hash_int,
            )

        return response

    def _fetch_with_fallback(
        self,
        *,
        channel: str,
        symbol: str,
        tool: str,
        params: dict[str, Any],
        params_hash: str,
        key: str,
    ) -> tuple[dict[str, Any], str, str | None]:
        """Try primary, then fallback if configured. Returns (response, source_used, prior_hash)."""
        try:
            self._acquire(self._primary_bucket)
            self._emitter.emit(
                "INGESTION_CALL_ISSUED",
                source=self._primary_source,
                tool=tool,
                params_hash=params_hash,
                channel=channel,
                symbol=symbol,
            )
            response = self._primary(tool, params)
        except Exception as primary_exc:
            if self._fallback is None:
                raise IngestionCallFailed(
                    f"primary source {self._primary_source!r} failed and no fallback configured: "
                    f"{type(primary_exc).__name__}: {primary_exc}"
                ) from primary_exc

            assert self._fallback_source is not None
            assert self._fallback_bucket is not None
            self._emitter.emit(
                "SOURCE_FALLBACK_TRIGGERED",
                from_source=self._primary_source,
                to_source=self._fallback_source,
                channel=channel,
                symbol=symbol,
                reason=_map_reason(primary_exc),
            )
            try:
                self._acquire(self._fallback_bucket)
                self._emitter.emit(
                    "INGESTION_CALL_ISSUED",
                    source=self._fallback_source,
                    tool=tool,
                    params_hash=params_hash,
                    channel=channel,
                    symbol=symbol,
                )
                response = self._fallback(tool, params)
            except Exception as fallback_exc:
                raise IngestionCallFailed(
                    f"primary {self._primary_source!r} and fallback "
                    f"{self._fallback_source!r} both failed: "
                    f"primary={type(primary_exc).__name__}: {primary_exc}; "
                    f"fallback={type(fallback_exc).__name__}: {fallback_exc}"
                ) from fallback_exc
            source_used = self._fallback_source
        else:
            source_used = self._primary_source

        prior_path = _cache.cache_path(self._cache_dir, source_used, tool, key)
        prior = _cache.read(prior_path)
        prior_hash = _cache.payload_hash(prior) if prior is not None else None
        return response, source_used, prior_hash


__all__ = [
    "ExtractMetadata",
    "IngestionCallFailed",
    "IngestionClient",
    "ObservationMetadata",
    "RawFetcher",
]
