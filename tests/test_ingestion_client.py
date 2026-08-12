"""Tests for IngestionClient — the five emit sites and the fallback flow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from price_space_llm.ingestion import cache as _cache
from price_space_llm.ingestion.client import (
    IngestionCallFailed,
    IngestionClient,
)
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary

VALUE_TIME = datetime(2024, 6, 15, 14, 0, tzinfo=UTC)
KNOWN_AT = datetime(2024, 6, 15, 14, 0, 30, tzinfo=UTC)


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _make_emitter(tmp_path: Path) -> tuple[StrictSignalEmitter, Path]:
    sink = tmp_path / "logs" / "signals.jsonl"
    e = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink)
    e.emit(
        "SESSION_INIT",
        run_id="test-run",
        run_kind="probe",
        vocab_version="0.2",
        config_hash="0" * 64,
        git_sha="0" * 40,
        data_hash="0" * 64,
        seed=0,
    )
    return e, sink


def _read_trace(sink: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines()]


def _tags(sink: Path) -> list[str]:
    return [s["tag"] for s in _read_trace(sink)]


def _call(client: IngestionClient, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "channel": "target",
        "symbol": "SPY",
        "tool": "TIME_SERIES_INTRADAY",
        "params": {"interval": "15min", "month": "2024-06"},
        "value_time": VALUE_TIME,
        "known_at": KNOWN_AT,
        "rows_written": 100,
    }
    kwargs.update(overrides)
    return client.call(**kwargs)


def test_cache_miss_emits_issued_and_written(tmp_path: Path):
    emitter, sink = _make_emitter(tmp_path)
    response = {"data": [1, 2, 3]}
    primary_calls = []

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        primary_calls.append((tool, params))
        return response

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=FakeClock(),
    )
    out = _call(client)
    assert out == response
    assert len(primary_calls) == 1
    tags = _tags(sink)
    assert "INGESTION_CALL_ISSUED" in tags
    assert "RAW_OBSERVATION_WRITTEN" in tags
    assert "INGESTION_CALL_CACHED" not in tags


def test_cache_hit_emits_cached_and_skips_fetch(tmp_path: Path):
    emitter, sink = _make_emitter(tmp_path)
    calls = 0

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"data": [1]}

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=FakeClock(),
    )
    _call(client)
    _call(client)
    assert calls == 1
    tags = _tags(sink)
    assert tags.count("INGESTION_CALL_ISSUED") == 1
    assert tags.count("INGESTION_CALL_CACHED") == 1


def test_cache_hit_returns_cached_payload_verbatim(tmp_path: Path):
    emitter, _ = _make_emitter(tmp_path)
    payload = {"data": [1, 2, 3], "nested": {"x": "y"}}

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        return payload

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=FakeClock(),
    )
    _call(client)
    out2 = _call(client)
    assert out2 == payload


def test_fallback_fires_source_fallback_triggered(tmp_path: Path):
    emitter, sink = _make_emitter(tmp_path)

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("primary boom")

    def fallback(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"data": [42]}

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        fallback=fallback,
        fallback_source="polygon",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=FakeClock(),
    )
    out = _call(client)
    assert out == {"data": [42]}
    trace = _read_trace(sink)
    fb = [s for s in trace if s["tag"] == "SOURCE_FALLBACK_TRIGGERED"]
    assert len(fb) == 1
    assert fb[0]["from_source"] == "mcp_av"
    assert fb[0]["to_source"] == "polygon"
    assert fb[0]["reason"] == "response_invalid"
    issued = [s for s in trace if s["tag"] == "INGESTION_CALL_ISSUED"]
    assert [s["source"] for s in issued] == ["mcp_av", "polygon"]


def test_rate_limit_exhausted_maps_to_rate_limit_reason(tmp_path: Path):
    emitter, sink = _make_emitter(tmp_path)
    clock = FakeClock()

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"data": [1]}

    def fallback(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"data": [2]}

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        fallback=fallback,
        fallback_source="polygon",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=clock,
        rate_limit_per_minute=1,
    )
    _call(client, symbol="SPY")
    _call(client, symbol="QQQ")  # different cache key
    trace = _read_trace(sink)
    fb = [s for s in trace if s["tag"] == "SOURCE_FALLBACK_TRIGGERED"]
    assert len(fb) == 1
    assert fb[0]["reason"] == "rate_limit_exhausted"


def test_primary_failure_without_fallback_raises(tmp_path: Path):
    emitter, sink = _make_emitter(tmp_path)

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("primary boom")

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=FakeClock(),
    )
    with pytest.raises(IngestionCallFailed):
        _call(client)
    assert "SOURCE_FALLBACK_TRIGGERED" not in _tags(sink)


def test_both_primary_and_fallback_fail_raises_with_chain(tmp_path: Path):
    emitter, _ = _make_emitter(tmp_path)

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("primary boom")

    def fallback(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("fallback boom")

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        fallback=fallback,
        fallback_source="polygon",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=FakeClock(),
    )
    with pytest.raises(IngestionCallFailed, match="both failed"):
        _call(client)


def test_revision_landed_when_prior_payload_differs_from_fetched(tmp_path: Path):
    """A prior cached payload plus a bypass of the cache-hit path emits REVISION_LANDED.

    The current IngestionClient checks the cache before fetch; a mismatch
    surfaces only when the cache write happens against a pre-existing file
    with different bytes AND the cache read returned None. This test
    exercises the second condition by using a stale/corrupt marker.

    Implementation detail: `_fetch_with_fallback` re-reads prior_path AFTER
    the fetch to compute prior_hash. If the initial cache-check read None
    but a prior payload exists at prior_path (race, or manual seed after
    the check), REVISION_LANDED fires. This test seeds it after the read
    by using a fetcher that plants a file mid-call.
    """
    emitter, sink = _make_emitter(tmp_path)

    key = _cache.cache_key(
        "TIME_SERIES_INTRADAY",
        "target",
        "SPY",
        {"interval": "15min", "month": "2024-06"},
    )
    prior_path = _cache.cache_path(tmp_path / "cache", "mcp_av", "TIME_SERIES_INTRADAY", key)

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        # Plant a prior payload after the client's cache-check returned None,
        # so the post-fetch prior-read finds a mismatched prior.
        _cache.write(prior_path, {"data": [1]})
        return {"data": [2]}

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=FakeClock(),
    )
    _call(client)
    assert "REVISION_LANDED" in _tags(sink)


def test_all_emitted_payloads_are_vocabulary_valid(tmp_path: Path):
    """Every emit in this suite passes the strict vocabulary validator.

    StrictSignalEmitter validates at emit time; if any test above emitted
    an invalid payload, that test would have raised. This test is the
    explicit check that the trace's tag categories all belong to
    'ingest' or 'session'.
    """
    emitter, sink = _make_emitter(tmp_path)

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"data": [1]}

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=FakeClock(),
    )
    _call(client)
    _call(client)  # cache hit
    trace = _read_trace(sink)
    for entry in trace:
        assert entry["category"] in {"ingest", "session"}


def test_fallback_requires_both_source_and_fetcher():
    with pytest.raises(ValueError, match="fallback"):
        IngestionClient(
            primary=lambda tool, params: {},
            primary_source="mcp_av",
            fallback=lambda tool, params: {},
            fallback_source=None,
            cache_dir=Path("/tmp"),
            emitter=StrictSignalEmitter(load_vocabulary()),
            clock=FakeClock(),
        )


def test_rate_limit_exhausted_without_fallback_raises(tmp_path: Path):
    emitter, _ = _make_emitter(tmp_path)

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"data": [1]}

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=FakeClock(),
        rate_limit_per_minute=1,
    )
    _call(client, symbol="SPY")
    with pytest.raises(IngestionCallFailed):
        _call(client, symbol="QQQ")


def test_rate_limit_bucket_is_per_source(tmp_path: Path):
    """Primary and fallback each have their own bucket; primary exhaustion falls to fallback."""
    emitter, sink = _make_emitter(tmp_path)

    def primary(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"data": [1]}

    def fallback(tool: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"data": [2]}

    client = IngestionClient(
        primary=primary,
        primary_source="mcp_av",
        fallback=fallback,
        fallback_source="polygon",
        cache_dir=tmp_path / "cache",
        emitter=emitter,
        clock=FakeClock(),
        rate_limit_per_minute=1,
    )
    _call(client, symbol="SPY")
    _call(client, symbol="QQQ")
    trace = _read_trace(sink)
    fb = [s for s in trace if s["tag"] == "SOURCE_FALLBACK_TRIGGERED"]
    assert len(fb) == 1
    assert fb[0]["reason"] == "rate_limit_exhausted"
