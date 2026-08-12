"""Tests for the Phase 0 channel-coverage probe."""

import json
from datetime import date
from pathlib import Path

from price_space_llm.ingestion.probe import (
    DEFAULT_SAMPLE_DATES,
    ChannelSpec,
    FetchResult,
    probe_channel,
    run_phase_zero_probe,
)
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary


def _clean_result() -> FetchResult:
    return FetchResult(
        actual_frequency="15min",
        earliest_timestamp="2015-01-05T13:30:00+00:00",
        latest_timestamp="2025-06-30T20:00:00+00:00",
        missing_fraction=0.001,
        timezone="UTC",
        timestamp_semantics="bar_close",
        revision_behavior="immutable",
    )


def _short_history_result() -> FetchResult:
    return FetchResult(
        actual_frequency="15min",
        earliest_timestamp="2019-01-02T13:30:00+00:00",  # after 2015-06-15
        latest_timestamp="2025-06-30T20:00:00+00:00",
        missing_fraction=0.01,
        timezone="UTC",
        timestamp_semantics="bar_close",
        revision_behavior="immutable",
    )


def _high_missing_result() -> FetchResult:
    r = _clean_result()
    r["missing_fraction"] = 0.20
    return r


def _fresh_emitter() -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary())


def _spec(channel: str = "target", symbol: str = "SPY") -> ChannelSpec:
    return ChannelSpec(channel=channel, symbol=symbol, source="mcp_av")


def test_probe_channel_emits_probed_per_date():
    e = _fresh_emitter()
    fetcher = lambda *args: _clean_result()  # noqa: E731
    probe_channel(_spec(), DEFAULT_SAMPLE_DATES, fetcher, e)
    tags = [s.tag for s in e.snapshot()]
    assert tags.count("CHANNEL_PROBED") == 5
    assert tags.count("CHANNEL_COVERAGE_ASSESSED") == 1
    assert tags.count("CHANNEL_REJECTED") == 0


def test_probe_channel_accepts_clean_channel():
    e = _fresh_emitter()
    fetcher = lambda *args: _clean_result()  # noqa: E731
    coverage = probe_channel(_spec(), DEFAULT_SAMPLE_DATES, fetcher, e)
    assert coverage["verdict"] == "accepted"
    assert coverage["reason"] is None
    last = e.snapshot()[-1]
    assert last.tag == "CHANNEL_COVERAGE_ASSESSED"
    assert last.payload["verdict"] == "accepted"


def test_probe_channel_rejects_high_missing_fraction():
    e = _fresh_emitter()
    fetcher = lambda *args: _high_missing_result()  # noqa: E731
    coverage = probe_channel(_spec(), DEFAULT_SAMPLE_DATES, fetcher, e)
    assert coverage["verdict"] == "dropped"
    assert coverage["reason"] == "missing_fraction_high"
    tags = [s.tag for s in e.snapshot()]
    assert tags.count("CHANNEL_REJECTED") == 1
    reject = next(s for s in e.snapshot() if s.tag == "CHANNEL_REJECTED")
    assert reject.payload["reason"] == "missing_fraction_high"


def test_probe_channel_rejects_history_too_short():
    e = _fresh_emitter()
    fetcher = lambda *args: _short_history_result()  # noqa: E731
    coverage = probe_channel(_spec(), DEFAULT_SAMPLE_DATES, fetcher, e)
    assert coverage["verdict"] == "dropped"
    assert coverage["reason"] == "history_too_short"


def test_probe_channel_emits_channel_fetch_failed_on_exception():
    """One failed date → CHANNEL_FETCH_FAILED; other dates still emit CHANNEL_PROBED."""
    e = _fresh_emitter()
    fail_on = date(2018, 6, 15)

    def fetcher(channel: str, symbol: str, source: str, sample_date: date) -> FetchResult:
        if sample_date == fail_on:
            raise RuntimeError("vendor said no")
        return _clean_result()

    coverage = probe_channel(_spec(), DEFAULT_SAMPLE_DATES, fetcher, e)
    tags = [s.tag for s in e.snapshot()]
    assert tags.count("CHANNEL_PROBED") == 4
    assert tags.count("CHANNEL_FETCH_FAILED") == 1
    assert tags.count("CHANNEL_COVERAGE_ASSESSED") == 1
    failed = next(s for s in e.snapshot() if s.tag == "CHANNEL_FETCH_FAILED")
    assert failed.payload["exception_class"] == "RuntimeError"
    assert failed.payload["error_message"] == "vendor said no"
    assert failed.payload["sample_date"] == fail_on.isoformat()
    assert coverage["verdict"] == "accepted"


def test_probe_channel_all_fetches_failed_skips_coverage_assessed():
    """All fetches fail → no CHANNEL_COVERAGE_ASSESSED fires; no earliest_timestamp exists."""
    e = _fresh_emitter()

    def fetcher(channel: str, symbol: str, source: str, sample_date: date) -> FetchResult:
        raise RuntimeError("total failure")

    coverage = probe_channel(_spec(), DEFAULT_SAMPLE_DATES, fetcher, e)
    tags = [s.tag for s in e.snapshot()]
    assert tags.count("CHANNEL_FETCH_FAILED") == 5
    assert tags.count("CHANNEL_PROBED") == 0
    assert tags.count("CHANNEL_COVERAGE_ASSESSED") == 0
    assert tags.count("CHANNEL_REJECTED") == 0
    assert coverage["verdict"] == "dropped"
    assert coverage["reason"] == "all_fetches_failed"
    assert coverage["earliest_timestamp"] is None
    assert coverage["overall_missing_fraction"] is None


def test_probe_channel_truncates_long_error_message():
    """error_message is capped so a malicious/verbose vendor can't flood the trace."""
    e = _fresh_emitter()
    huge = "x" * 5000

    def fetcher(channel: str, symbol: str, source: str, sample_date: date) -> FetchResult:
        raise RuntimeError(huge)

    probe_channel(_spec(), DEFAULT_SAMPLE_DATES, fetcher, e)
    failed = next(s for s in e.snapshot() if s.tag == "CHANNEL_FETCH_FAILED")
    assert len(failed.payload["error_message"]) == 1000


def test_run_phase_zero_probe_writes_manifest_json(tmp_path: Path):
    e = _fresh_emitter()

    def fetcher(channel: str, symbol: str, source: str, sample_date: date) -> FetchResult:
        if channel == "market_context" and symbol == "USO":
            return _high_missing_result()
        return _clean_result()

    channels = [
        _spec("target", "SPY"),
        _spec("market_context", "VIX"),
        _spec("market_context", "USO"),
    ]
    output = tmp_path / "channel_coverage.json"
    coverages = run_phase_zero_probe(channels, DEFAULT_SAMPLE_DATES, fetcher, e, output)

    assert output.exists()
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert set(manifest["channels"].keys()) == {
        "target__SPY",
        "market_context__VIX",
        "market_context__USO",
    }
    assert manifest["channels"]["target__SPY"]["verdict"] == "accepted"
    assert manifest["channels"]["market_context__USO"]["verdict"] == "dropped"
    assert manifest["channels"]["market_context__USO"]["reason"] == "missing_fraction_high"
    assert len(coverages) == 3
