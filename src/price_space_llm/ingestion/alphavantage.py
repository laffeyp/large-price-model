"""Alpha-Vantage HTTP fetcher for the Phase 0 probe.

Implements the `Fetcher` signature (Callable[[channel, symbol, source,
sample_date], FetchResult]) using the public Alpha-Vantage REST API
via httpx. The MCP tool namespace in the agent session is agent-only;
this module is what a shell-invoked Python script uses.

Sprint 019 scope: TIME_SERIES_INTRADAY for `channel ∈ {target,
market_context}`. Other channel families raise NotImplementedError
and are added tool-by-tool in later sprints.

Response normalisation:
- Strip ordinal prefixes from OHLCV keys ("1. open" -> "open").
- Coerce string numbers to float/int.
- Convert US/Eastern timestamps to UTC (bar_close semantics per
  tech-arch §4.3).
- Compute missing_fraction from expected bar count for the sampled
  month (rough heuristic: 21 trading days * 26 bars = 546 bars per
  RTH month; refined in a later sprint via `pandas_market_calendars`).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import httpx

from price_space_llm.ingestion.client import ObservationMetadata, RawFetcher
from price_space_llm.ingestion.probe import Fetcher, FetchResult

ALPHAVANTAGE_BASE_URL = "https://www.alphavantage.co"
US_EASTERN_OFFSET = timedelta(hours=-5)  # EST base; DST handling deferred to a real tz library
EXPECTED_BARS_PER_TRADING_MONTH = 21 * 26  # rough heuristic; refined later


class AlphaVantageError(RuntimeError):
    """Base for Alpha-Vantage fetcher failures."""


class AlphaVantageResponseError(AlphaVantageError):
    """Alpha-Vantage returned an `Error Message` payload."""


class AlphaVantageRateLimitError(AlphaVantageError):
    """Alpha-Vantage returned a `Note` or `Information` payload (rate limit)."""


def _strip_ordinal(key: str) -> str:
    """`'1. open'` -> `'open'`; `'volume'` unchanged."""
    if len(key) >= 4 and key[0].isdigit() and key[1] == "." and key[2] == " ":
        return key[3:]
    return key


def _to_utc_iso(us_eastern_ts: str) -> str:
    """Parse `'YYYY-MM-DD HH:MM:SS'` in US/Eastern and return an ISO-8601 UTC string.

    DST is a real concern; this rough conversion uses a fixed EST offset.
    A later sprint swaps in zoneinfo("America/New_York") for correctness.
    """
    naive = datetime.strptime(us_eastern_ts, "%Y-%m-%d %H:%M:%S")
    us_eastern = naive.replace(tzinfo=timezone(US_EASTERN_OFFSET))
    return us_eastern.astimezone(UTC).isoformat()


def _normalize_bar(row: dict[str, str]) -> dict[str, float | int]:
    """Strip ordinal prefixes and coerce string OHLCV values to numbers."""
    out: dict[str, float | int] = {}
    for k, v in row.items():
        clean = _strip_ordinal(k)
        out[clean] = int(v) if clean == "volume" else float(v)
    return out


def _extract_fetch_result(
    response_json: dict[str, Any],
    sample_date: date,
) -> FetchResult:
    """Turn a TIME_SERIES_INTRADAY response into a FetchResult.

    Raises `AlphaVantageResponseError` if the Time Series is empty; the
    caller has no observation to serialise. Sprint 023 removed the
    fill-value path that Sprint 019 shipped.
    """
    del sample_date  # reserved for future per-date filtering
    meta = response_json.get("Meta Data", {})
    series_key = next(
        (k for k in response_json if k.startswith("Time Series")),
        "Time Series (15min)",
    )
    series: dict[str, dict[str, str]] = response_json.get(series_key, {})

    if not series:
        raise AlphaVantageResponseError(
            "empty Time Series in vendor response — no observations to serialise"
        )

    ts_us = sorted(series.keys())
    earliest_utc = _to_utc_iso(ts_us[0])
    latest_utc = _to_utc_iso(ts_us[-1])
    missing = max(
        0.0, (EXPECTED_BARS_PER_TRADING_MONTH - len(series)) / EXPECTED_BARS_PER_TRADING_MONTH
    )

    return FetchResult(
        actual_frequency=meta.get("4. Interval", "15min"),
        earliest_timestamp=earliest_utc,
        latest_timestamp=latest_utc,
        missing_fraction=missing,
        timezone="UTC",  # normalised
        timestamp_semantics="bar_close",
        revision_behavior="immutable",
    )


def _check_error_payload(response_json: dict[str, Any]) -> None:
    """Raise for Alpha-Vantage error / rate-limit response bodies (200 OK still)."""
    if "Error Message" in response_json:
        raise AlphaVantageResponseError(response_json["Error Message"])
    if "Note" in response_json or "Information" in response_json:
        msg = response_json.get("Note") or response_json.get("Information") or "rate limit"
        raise AlphaVantageRateLimitError(msg)


def make_alphavantage_fetcher(
    api_key: str,
    client: httpx.Client | None = None,
) -> Fetcher:
    """Return a Fetcher closure over the httpx client + api key.

    Pass `client` to inject an `httpx.MockTransport`-backed client in tests;
    omit for production (defaults to a real httpx.Client with a 30s timeout).
    """
    http = (
        client
        if client is not None
        else httpx.Client(
            base_url=ALPHAVANTAGE_BASE_URL,
            timeout=30.0,
        )
    )

    def fetch(channel: str, symbol: str, source: str, sample_date: date) -> FetchResult:
        if channel not in {"target", "market_context"}:
            raise NotImplementedError(
                f"Sprint 019 fetcher supports channel ∈ {{target, market_context}}; "
                f"got {channel!r}. Later sprints add per-channel tools."
            )
        response = http.get(
            "/query",
            params={
                "function": "TIME_SERIES_INTRADAY",
                "symbol": symbol,
                "interval": "15min",
                "outputsize": "full",
                "month": sample_date.strftime("%Y-%m"),
                "apikey": api_key,
                "datatype": "json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        _check_error_payload(payload)
        return _extract_fetch_result(payload, sample_date)

    return fetch


def make_alphavantage_raw_fetcher(
    api_key: str,
    client: httpx.Client | None = None,
) -> RawFetcher:
    """Return a `RawFetcher` closure that returns the raw Alpha-Vantage JSON dict.

    Distinct from `make_alphavantage_fetcher` (probe-shape) — this one is
    for `IngestionClient`, which needs the full response dict for caching
    and downstream feature extraction. Signature: `(tool, params) -> dict`.

    Passes `params` through to Alpha-Vantage verbatim with `function=tool`
    and `apikey` appended. The caller supplies every other param (`symbol`,
    `interval`, `month`, `datatype`, `outputsize`, etc.).
    """
    http = (
        client if client is not None else httpx.Client(base_url=ALPHAVANTAGE_BASE_URL, timeout=30.0)
    )

    def fetch(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        query_params = {"function": tool, "apikey": api_key, **params}
        response = http.get("/query", params=query_params)
        response.raise_for_status()
        payload = response.json()
        _check_error_payload(payload)
        if not isinstance(payload, dict):
            raise AlphaVantageResponseError(
                f"expected JSON object at /query, got {type(payload).__name__}"
            )
        return payload

    return fetch


def alphavantage_extract_metadata(response: dict[str, Any]) -> ObservationMetadata:
    """Extract ObservationMetadata from a TIME_SERIES_INTRADAY response.

    `value_time`: the newest bar's timestamp in UTC (batch high-watermark).
    `known_at`: `value_time + 1 minute` — a simplification for historical
        monthly pulls. Real streaming ingestion would carry the vendor's
        release-time header; this approximation holds for cached historical
        bars whose known_at is definitionally after their value_time.
    `rows_written`: the count of bars in the response's Time Series map.

    Raises `AlphaVantageResponseError` if the response has no recognisable
    Time Series (empty month, malformed response). The caller — normally
    IngestionClient.call — surfaces that up.
    """
    series_key = next(
        (k for k in response if k.startswith("Time Series")),
        None,
    )
    if series_key is None:
        raise AlphaVantageResponseError(
            "response has no 'Time Series ...' key; cannot extract metadata"
        )
    series: dict[str, dict[str, str]] = response[series_key]
    if not series:
        raise AlphaVantageResponseError(
            "empty Time Series; extractor has no observations to describe"
        )
    latest_us_eastern = max(series.keys())
    naive = datetime.strptime(latest_us_eastern, "%Y-%m-%d %H:%M:%S")
    value_time = naive.replace(tzinfo=timezone(US_EASTERN_OFFSET)).astimezone(UTC)
    known_at = value_time + timedelta(minutes=1)
    return ObservationMetadata(
        value_time=value_time,
        known_at=known_at,
        rows_written=len(series),
    )


__all__ = [
    "EXPECTED_BARS_PER_TRADING_MONTH",
    "AlphaVantageError",
    "AlphaVantageRateLimitError",
    "AlphaVantageResponseError",
    "alphavantage_extract_metadata",
    "make_alphavantage_fetcher",
    "make_alphavantage_raw_fetcher",
]
