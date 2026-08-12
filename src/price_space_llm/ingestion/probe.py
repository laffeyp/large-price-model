"""Phase 0 channel-coverage probe.

Walks a channel manifest and, for each (channel, symbol), asks the vendor
what it actually returns at five sample dates. Records the result in
`data/manifests/channel_coverage.json` and emits the probe signals.

The vendor call is injected as a `fetcher` callable so the probe is
testable offline and provider-agnostic.

Verdict logic per `technical-architecture-v4.md §4.1`:
- `dropped` if `missing_fraction > 0.05` at any sample date OR
  `earliest_timestamp` (from any sample date) is later than 2015-06-15
  OR the fetcher raised on every sample date (all_fetches_failed).
- `accepted` otherwise.
- `renegotiate` reserved for future policy.

Failed-fetch policy (per v0.3 vocabulary + Sprint 023 correction):
- On fetcher exception the probe emits `CHANNEL_FETCH_FAILED` with the
  exception class + message. No `CHANNEL_PROBED` fires for that date --
  no observation was made.
- If at least one sample date succeeded, aggregates run over the
  successful subset and `CHANNEL_COVERAGE_ASSESSED` closes the channel.
- If every sample date failed, no `CHANNEL_COVERAGE_ASSESSED` fires
  (the vocabulary requires `earliest_timestamp`, which does not exist).
  The returned `ChannelCoverage` carries `verdict="dropped"`,
  `reason="all_fetches_failed"`, `earliest_timestamp=None`.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

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
MAX_ERROR_MESSAGE_CHARS = 1000


@dataclass(slots=True, frozen=True, kw_only=True)
class ChannelSpec:
    channel: str
    symbol: str
    source: str


@dataclass(slots=True, frozen=True, kw_only=True)
class FetchResult:
    """What a fetcher returns per (channel, symbol, sample_date) call."""

    actual_frequency: str
    earliest_timestamp: str
    latest_timestamp: str
    missing_fraction: float
    timezone: str
    timestamp_semantics: str
    revision_behavior: str


Fetcher = Callable[[str, str, str, date], FetchResult]


@dataclass(slots=True, frozen=True, kw_only=True)
class ChannelCoverage:
    channel: str
    symbol: str
    source: str
    overall_missing_fraction: float | None
    earliest_timestamp: str | None
    latest_timestamp: str | None
    verdict: str
    reason: str | None


def _verdict_for(
    per_date_results: list[FetchResult],
) -> tuple[str, str | None]:
    """Return (verdict, reason) per tech-arch verdict rules over the successful subset."""
    if not per_date_results:
        return "dropped", "all_fetches_failed"
    max_missing = max(r.missing_fraction for r in per_date_results)
    if max_missing > MISSING_FRACTION_THRESHOLD:
        return "dropped", "missing_fraction_high"
    earliest = min(r.earliest_timestamp for r in per_date_results)
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
        try:
            result = fetcher(
                channel_spec.channel,
                channel_spec.symbol,
                channel_spec.source,
                sample_date,
            )
        except Exception as exc:
            emitter.emit(
                "CHANNEL_FETCH_FAILED",
                channel=channel_spec.channel,
                symbol=channel_spec.symbol,
                source=channel_spec.source,
                sample_date=sample_date.isoformat(),
                exception_class=type(exc).__name__,
                error_message=str(exc)[:MAX_ERROR_MESSAGE_CHARS],
            )
            continue
        per_date.append(result)
        emitter.emit(
            "CHANNEL_PROBED",
            channel=channel_spec.channel,
            symbol=channel_spec.symbol,
            source=channel_spec.source,
            sample_date=sample_date.isoformat(),
            actual_frequency=result.actual_frequency,
            earliest_timestamp=result.earliest_timestamp,
            latest_timestamp=result.latest_timestamp,
            missing_fraction=result.missing_fraction,
            timezone=result.timezone,
            timestamp_semantics=result.timestamp_semantics,
            revision_behavior=result.revision_behavior,
        )

    verdict, reason = _verdict_for(per_date)

    if not per_date:
        return ChannelCoverage(
            channel=channel_spec.channel,
            symbol=channel_spec.symbol,
            source=channel_spec.source,
            overall_missing_fraction=None,
            earliest_timestamp=None,
            latest_timestamp=None,
            verdict=verdict,
            reason=reason,
        )

    max_missing = max(r.missing_fraction for r in per_date)
    earliest = min(r.earliest_timestamp for r in per_date)
    latest = max(r.latest_timestamp for r in per_date)

    if verdict == "dropped" and reason is not None and reason != "all_fetches_failed":
        emitter.emit(
            "CHANNEL_REJECTED",
            channel=channel_spec.channel,
            symbol=channel_spec.symbol,
            source=channel_spec.source,
            reason=reason,
            missing_fraction=max_missing,
            earliest_timestamp=earliest,
        )

    emitter.emit(
        "CHANNEL_COVERAGE_ASSESSED",
        channel=channel_spec.channel,
        symbol=channel_spec.symbol,
        source=channel_spec.source,
        overall_missing_fraction=max_missing,
        earliest_timestamp=earliest,
        latest_timestamp=latest,
        verdict=verdict,
    )

    return ChannelCoverage(
        channel=channel_spec.channel,
        symbol=channel_spec.symbol,
        source=channel_spec.source,
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
        "generated_at": None,
        "channels": {f"{c.channel}__{c.symbol}": asdict(c) for c in coverages},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return coverages
