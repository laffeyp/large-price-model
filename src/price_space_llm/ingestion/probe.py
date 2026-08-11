"""Phase 0 channel-coverage probe.

Walks a channel manifest and, for each (channel, symbol), asks the vendor
what it actually returns at five sample dates. Records the result in
`data/manifests/channel_coverage.json` and emits the probe signals.

The vendor call is injected as a `fetcher` callable so the probe is
testable offline and provider-agnostic. Sprint 018 supplies the real
Alpha-Vantage MCP fetcher; other providers plug in with the same
signature.

Verdict logic per `technical-architecture-v4.md §4.1`:
- `dropped` if `missing_fraction > 0.05` at any sample date OR
  `earliest_timestamp` (from any sample date) is later than 2015-06-15.
- `accepted` otherwise.
- `renegotiate` reserved for future policy.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from typing import Any, TypedDict

from price_space_llm.signals import StrictSignalEmitter

DEFAULT_SAMPLE_DATES: tuple[date, ...] = (
    date(2015, 6, 15),
    date(2018, 6, 15),
    date(2020, 6, 15),
    date(2022, 6, 15),
    date(2025, 1, 15),
)

MISSING_FRACTION_THRESHOLD = 0.05
EARLIEST_HISTORY_REQUIRED = date(2015, 6, 15)


class ChannelSpec(TypedDict):
    channel: str
    symbol: str
    source: str


class FetchResult(TypedDict):
    """What a fetcher returns per (channel, symbol, sample_date) call."""

    actual_frequency: str
    earliest_timestamp: str
    latest_timestamp: str
    missing_fraction: float
    timezone: str
    timestamp_semantics: str
    revision_behavior: str


Fetcher = Callable[[str, str, str, date], FetchResult]


class ChannelCoverage(TypedDict):
    channel: str
    symbol: str
    source: str
    overall_missing_fraction: float
    earliest_timestamp: str
    latest_timestamp: str
    verdict: str
    reason: str | None


def _verdict_for(
    per_date_results: list[FetchResult],
) -> tuple[str, str | None]:
    """Return (verdict, reason) per tech-arch verdict rules."""
    if not per_date_results:
        return "dropped", "no_probe_results"
    max_missing = max(r["missing_fraction"] for r in per_date_results)
    if max_missing > MISSING_FRACTION_THRESHOLD:
        return "dropped", "missing_fraction_high"
    earliest = min(r["earliest_timestamp"] for r in per_date_results)
    if _iso_date_str(earliest) > EARLIEST_HISTORY_REQUIRED:
        return "dropped", "history_too_short"
    return "accepted", None


def _iso_date_str(ts: str) -> date:
    """Extract the date portion of an ISO-8601 timestamp string."""
    return date.fromisoformat(ts[:10])


def probe_channel(
    channel_spec: ChannelSpec,
    sample_dates: Iterable[date],
    fetcher: Fetcher,
    emitter: StrictSignalEmitter,
) -> ChannelCoverage:
    """Probe one (channel, symbol) at the sample dates. Emits per-date + summary."""
    per_date: list[FetchResult] = []
    dates = list(sample_dates)
    for sample_date in dates:
        result = fetcher(
            channel_spec["channel"],
            channel_spec["symbol"],
            channel_spec["source"],
            sample_date,
        )
        per_date.append(result)
        emitter.emit(
            "CHANNEL_PROBED",
            channel=channel_spec["channel"],
            symbol=channel_spec["symbol"],
            source=channel_spec["source"],
            sample_date=sample_date.isoformat(),
            actual_frequency=result["actual_frequency"],
            earliest_timestamp=result["earliest_timestamp"],
            latest_timestamp=result["latest_timestamp"],
            missing_fraction=result["missing_fraction"],
            timezone=result["timezone"],
            timestamp_semantics=result["timestamp_semantics"],
            revision_behavior=result["revision_behavior"],
        )

    verdict, reason = _verdict_for(per_date)
    max_missing = max((r["missing_fraction"] for r in per_date), default=1.0)
    earliest = min((r["earliest_timestamp"] for r in per_date), default="")
    latest = max((r["latest_timestamp"] for r in per_date), default="")

    if verdict == "dropped" and reason is not None:
        emitter.emit(
            "CHANNEL_REJECTED",
            channel=channel_spec["channel"],
            symbol=channel_spec["symbol"],
            source=channel_spec["source"],
            reason=reason,
            missing_fraction=max_missing,
            earliest_timestamp=earliest,
        )

    emitter.emit(
        "CHANNEL_COVERAGE_ASSESSED",
        channel=channel_spec["channel"],
        symbol=channel_spec["symbol"],
        source=channel_spec["source"],
        overall_missing_fraction=max_missing,
        earliest_timestamp=earliest,
        latest_timestamp=latest,
        verdict=verdict,
    )

    return ChannelCoverage(
        channel=channel_spec["channel"],
        symbol=channel_spec["symbol"],
        source=channel_spec["source"],
        overall_missing_fraction=max_missing,
        earliest_timestamp=earliest,
        latest_timestamp=latest,
        verdict=verdict,
        reason=reason,
    )


def run_phase_zero_probe(
    channels: Iterable[ChannelSpec],
    sample_dates: Iterable[date],
    fetcher: Fetcher,
    emitter: StrictSignalEmitter,
    output_path: Path,
) -> list[ChannelCoverage]:
    """Probe every channel in the manifest; write aggregated result to output_path."""
    dates_list = list(sample_dates)
    coverages: list[ChannelCoverage] = []
    for spec in channels:
        coverages.append(probe_channel(spec, dates_list, fetcher, emitter))

    manifest: dict[str, Any] = {
        "generated_at": None,  # caller stamps if desired; deterministic-by-default here
        "channels": {f"{c['channel']}__{c['symbol']}": dict(c) for c in coverages},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return coverages
