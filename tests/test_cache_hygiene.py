"""Tests for the cache provenance sidecar + index + freshness policy (Sprint 036)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from price_space_llm.ingestion.cache import (
    CACHE_INDEX_FILENAME,
    FRESHNESS_POLICY,
    META_SUFFIX,
    cache_key,
    cache_path,
    meta_path,
    read_meta,
    read_with_freshness,
    write_with_meta,
)


def _params() -> dict[str, object]:
    return {"symbol": "SPY", "interval": "15min", "month": "2024-06"}


def _write(tmp_path: Path, tool: str = "TIME_SERIES_INTRADAY", now: datetime | None = None):
    """Helper: perform a write_with_meta and return (data_path, meta)."""
    params = _params()
    key = cache_key(tool, "target", "SPY", params)
    data_path = cache_path(tmp_path, "mcp_av", tool, key)
    payload = {"Meta Data": {"1. Info": "SPY"}, "Time Series (15min)": {"2024-06-03 09:45:00": {}}}
    meta = write_with_meta(
        data_path,
        payload,
        cache_dir=tmp_path,
        tool=tool,
        channel="target",
        symbol="SPY",
        params=params,
        key=key,
        pulled_by_run_id="test-run",
        git_sha="a" * 40,
        now=now,
    )
    return data_path, meta


# Sidecar + provenance ----------------------------------------------------


def test_write_with_meta_creates_sidecar(tmp_path: Path):
    data_path, _meta = _write(tmp_path)
    sidecar = meta_path(data_path)
    assert sidecar.exists()
    assert sidecar.name.endswith(META_SUFFIX)


def test_read_meta_returns_provenance(tmp_path: Path):
    data_path, expected = _write(tmp_path)
    meta = read_meta(data_path)
    assert meta is not None
    assert meta.tool == "TIME_SERIES_INTRADAY"
    assert meta.channel == "target"
    assert meta.symbol == "SPY"
    assert meta.pulled_by_run_id == "test-run"
    assert meta.git_sha == "a" * 40
    assert meta.size_bytes > 0
    assert len(meta.response_schema_hash) == 64
    assert meta == expected


def test_read_meta_returns_none_when_missing(tmp_path: Path):
    assert read_meta(tmp_path / "does-not-exist.json") is None


# Cache index -------------------------------------------------------------


def test_write_with_meta_appends_index_row(tmp_path: Path):
    _write(tmp_path)
    index = tmp_path / CACHE_INDEX_FILENAME
    assert index.exists()
    lines = index.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["tool"] == "TIME_SERIES_INTRADAY"
    assert row["symbol"] == "SPY"
    assert "pulled_at_utc" in row
    assert row["data_path"].endswith(".json")


def test_multiple_writes_accumulate_index_rows(tmp_path: Path):
    _write(tmp_path)
    # Second write with different params → different key → different row.
    params = {"symbol": "SPY", "interval": "15min", "month": "2024-07"}
    key = cache_key("TIME_SERIES_INTRADAY", "target", "SPY", params)
    data_path = cache_path(tmp_path, "mcp_av", "TIME_SERIES_INTRADAY", key)
    write_with_meta(
        data_path,
        {"Meta Data": {}, "Time Series (15min)": {}},
        cache_dir=tmp_path,
        tool="TIME_SERIES_INTRADAY",
        channel="target",
        symbol="SPY",
        params=params,
        key=key,
        pulled_by_run_id="test-run-2",
        git_sha="b" * 40,
    )
    lines = (tmp_path / CACHE_INDEX_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


# Freshness ---------------------------------------------------------------


def test_read_with_freshness_returns_payload_for_immutable_tool(tmp_path: Path):
    data_path, _ = _write(tmp_path, tool="TIME_SERIES_INTRADAY")
    result = read_with_freshness(data_path, "TIME_SERIES_INTRADAY")
    assert result is not None
    assert "Time Series (15min)" in result


def test_read_with_freshness_returns_none_when_stale(tmp_path: Path):
    """A REALTIME_BULK_BID_ASK_PRICES entry pulled 60s ago exceeds its 5s freshness window."""
    old = datetime.now(UTC) - timedelta(seconds=60)
    data_path, _ = _write(tmp_path, tool="REALTIME_BULK_BID_ASK_PRICES", now=old)
    result = read_with_freshness(data_path, "REALTIME_BULK_BID_ASK_PRICES")
    assert result is None


def test_read_with_freshness_returns_payload_when_fresh(tmp_path: Path):
    now = datetime.now(UTC)
    data_path, _ = _write(tmp_path, tool="REALTIME_BULK_BID_ASK_PRICES", now=now)
    # Ask again 1 second later; under the 5s window.
    result = read_with_freshness(
        data_path,
        "REALTIME_BULK_BID_ASK_PRICES",
        now=now + timedelta(seconds=1),
    )
    assert result is not None


def test_read_with_freshness_returns_none_when_no_sidecar_and_policy_non_infinite(tmp_path: Path):
    """Legacy pre-Sprint-036 caches (no sidecar) refuse to serve as fresh under a bounded policy."""
    key = cache_key("REALTIME_BULK_BID_ASK_PRICES", "target", "SPY", _params())
    data_path = cache_path(tmp_path, "mcp_av", "REALTIME_BULK_BID_ASK_PRICES", key)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps({"data": [{"symbol": "SPY"}]}), encoding="utf-8")
    # No sidecar written.
    assert read_with_freshness(data_path, "REALTIME_BULK_BID_ASK_PRICES") is None


def test_read_with_freshness_returns_payload_for_immutable_without_sidecar(tmp_path: Path):
    """Legacy caches under an immutable policy DO serve (max_age=inf skips the freshness check)."""
    key = cache_key("TIME_SERIES_INTRADAY", "target", "SPY", _params())
    data_path = cache_path(tmp_path, "mcp_av", "TIME_SERIES_INTRADAY", key)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"Meta Data": {}, "Time Series (15min)": {}}
    data_path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_with_freshness(data_path, "TIME_SERIES_INTRADAY") is not None


def test_freshness_policy_has_expected_entries():
    assert FRESHNESS_POLICY["TIME_SERIES_INTRADAY"] == float("inf")
    assert FRESHNESS_POLICY["HISTORICAL_OPTIONS"] == float("inf")
    assert FRESHNESS_POLICY["REALTIME_BULK_BID_ASK_PRICES"] == pytest.approx(5.0)


# Schema-hash fingerprint -------------------------------------------------


def test_response_schema_hash_changes_when_keys_change(tmp_path: Path):
    _data_path_a, meta_a = _write(tmp_path)
    # Now write a DIFFERENT payload (different top-level keys) at a different cache key.
    params = {"symbol": "SPY", "interval": "15min", "month": "2024-07"}
    key = cache_key("TIME_SERIES_INTRADAY", "target", "SPY", params)
    _data_path_b = cache_path(tmp_path, "mcp_av", "TIME_SERIES_INTRADAY", key)
    meta_b = write_with_meta(
        _data_path_b,
        {"OTHER_KEY": {}, "Renamed Series": {}},
        cache_dir=tmp_path,
        tool="TIME_SERIES_INTRADAY",
        channel="target",
        symbol="SPY",
        params=params,
        key=key,
        pulled_by_run_id="test",
        git_sha="c" * 40,
    )
    assert meta_a.response_schema_hash != meta_b.response_schema_hash
