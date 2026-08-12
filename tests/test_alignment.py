"""Tests for the alignment pipeline (Polars join_asof on `known_at`)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest

from price_space_llm.alignment.join import (
    align_channels,
    build_rth_grid,
    load_channel_bars,
    run_alignment,
)
from price_space_llm.ingestion import cache as _cache
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary


def _fresh_emitter(max_buffer: int = 8192) -> StrictSignalEmitter:
    """Alignment runs emit many signals; default buffer of 500 overflows on a month of grid bars.

    Bump the buffer for tests that inspect the full sequence via snapshot().
    """
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


def _write_cache(tmp_path: Path, channel: str, symbol: str, month: str, bars: dict) -> Path:
    """Write a minimal AV-shaped cache entry and return its path."""
    params = {
        "symbol": symbol,
        "interval": "15min",
        "month": month,
        "outputsize": "full",
        "datatype": "json",
    }
    key = _cache.cache_key("TIME_SERIES_INTRADAY", channel, symbol, params)
    path = _cache.cache_path(tmp_path, "mcp_av", "TIME_SERIES_INTRADAY", key)
    payload = {
        "Meta Data": {"4. Interval": "15min", "6. Time Zone": "US/Eastern"},
        "Time Series (15min)": bars,
    }
    _cache.write(path, payload)
    return path


def _bar(close: float = 100.0) -> dict:
    return {
        "1. open": str(close - 0.5),
        "2. high": str(close + 0.5),
        "3. low": str(close - 1.0),
        "4. close": str(close),
        "5. volume": "1000",
    }


# build_rth_grid ------------------------------------------------------------


def test_grid_has_26_bars_per_weekday():
    grid = build_rth_grid(date(2024, 6, 3), date(2024, 6, 3))  # Monday
    assert grid.height == 26


def test_grid_skips_weekends():
    # Sat + Sun should contribute 0 bars.
    grid_weekend = build_rth_grid(date(2024, 6, 1), date(2024, 6, 2))
    assert grid_weekend.height == 0


def test_grid_spans_multiple_weekdays():
    # Mon 2024-06-03 through Fri 2024-06-07 = 5 weekdays * 26 = 130
    grid = build_rth_grid(date(2024, 6, 3), date(2024, 6, 7))
    assert grid.height == 130


def test_grid_bars_are_utc_aware():
    grid = build_rth_grid(date(2024, 6, 3), date(2024, 6, 3))
    first_ts = grid["grid_ts"][0]
    assert first_ts.tzinfo is not None
    # 09:45 US/Eastern with fixed -5 offset → 14:45 UTC
    assert first_ts.hour == 14
    assert first_ts.minute == 45


# load_channel_bars ---------------------------------------------------------


def test_load_channel_bars_parses_cache(tmp_path: Path):
    _write_cache(
        tmp_path,
        "target",
        "SPY",
        "2024-06",
        {
            "2024-06-03 09:45:00": _bar(540.0),
            "2024-06-03 10:00:00": _bar(541.0),
        },
    )
    df = load_channel_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        tool="TIME_SERIES_INTRADAY",
        channel="target",
        symbol="SPY",
        params={
            "symbol": "SPY",
            "interval": "15min",
            "month": "2024-06",
            "outputsize": "full",
            "datatype": "json",
        },
    )
    assert df.height == 2
    assert set(df.columns) == {"known_at", "close", "channel", "symbol"}
    assert df["close"].to_list() == [540.0, 541.0]


def test_load_channel_bars_raises_on_missing_cache(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_channel_bars(
            cache_dir=tmp_path,
            source="mcp_av",
            tool="TIME_SERIES_INTRADAY",
            channel="target",
            symbol="SPY",
            params={"symbol": "SPY"},
        )


# align_channels ------------------------------------------------------------


def test_align_channels_backward_join_takes_latest_prior_bar():
    """A grid bar at T pulls the observation whose known_at <= T (strict causality).

    Grid times are 14:45, 15:00, 15:15 UTC. Bars are known at 14:31 (first) and 15:01
    (second). Backward-join semantics:
      grid=14:45 → 14:31 available → 540.0
      grid=15:00 → 14:31 available; 15:01 NOT yet visible → 540.0 (the causality gate)
      grid=15:15 → 15:01 now available → 541.0
    """
    e = _fresh_emitter()
    grid = pl.DataFrame(
        {
            "grid_ts": [
                datetime.fromisoformat("2024-06-03T14:45:00+00:00"),
                datetime.fromisoformat("2024-06-03T15:00:00+00:00"),
                datetime.fromisoformat("2024-06-03T15:15:00+00:00"),
            ]
        }
    )
    bars = pl.DataFrame(
        {
            "known_at": [
                datetime.fromisoformat("2024-06-03T14:31:00+00:00"),
                datetime.fromisoformat("2024-06-03T15:01:00+00:00"),
            ],
            "close": [540.0, 541.0],
            "channel": ["target", "target"],
            "symbol": ["SPY", "SPY"],
        }
    )
    aligned = align_channels(grid, {"target__SPY": bars}, e)
    assert aligned["target__SPY__close"].to_list() == [540.0, 540.0, 541.0]


def test_align_channels_emits_as_of_join_miss_on_null():
    """Grid bar before any observation → AS_OF_JOIN_MISS + null close."""
    e = _fresh_emitter()
    grid = pl.DataFrame({"grid_ts": [datetime.fromisoformat("2024-06-03T14:45:00+00:00")]})
    bars = pl.DataFrame(
        {
            "known_at": [datetime.fromisoformat("2024-06-04T14:31:00+00:00")],
            "close": [540.0],
            "channel": ["target"],
            "symbol": ["SPY"],
        }
    )
    align_channels(grid, {"target__SPY": bars}, e)
    tags = [s.tag for s in e.snapshot()]
    assert tags.count("AS_OF_JOIN_MISS") == 1
    assert tags.count("ALIGNMENT_ROW_EMITTED") == 1
    miss = next(s for s in e.snapshot() if s.tag == "AS_OF_JOIN_MISS")
    assert miss.payload["reason"] == "no_history_yet"
    assert miss.payload["channel"] == "target"


def test_align_channels_missing_channels_count_is_correct():
    """Two channels; only one has a prior observation at grid_ts → count=1."""
    e = _fresh_emitter()
    grid = pl.DataFrame({"grid_ts": [datetime.fromisoformat("2024-06-03T14:45:00+00:00")]})
    spy = pl.DataFrame(
        {
            "known_at": [datetime.fromisoformat("2024-06-03T14:31:00+00:00")],
            "close": [540.0],
            "channel": ["target"],
            "symbol": ["SPY"],
        }
    )
    uso = pl.DataFrame(
        {
            "known_at": [datetime.fromisoformat("2024-06-04T14:31:00+00:00")],
            "close": [80.0],
            "channel": ["market_context"],
            "symbol": ["USO"],
        }
    )
    align_channels(grid, {"target__SPY": spy, "market_context__USO": uso}, e)
    row_emit = next(s for s in e.snapshot() if s.tag == "ALIGNMENT_ROW_EMITTED")
    assert row_emit.payload["missing_channels_count"] == 1


# run_alignment (end-to-end) -----------------------------------------------


def test_run_alignment_writes_parquet_and_emits_summary(tmp_path: Path):
    _write_cache(
        tmp_path / "cache",
        "target",
        "SPY",
        "2024-06",
        {
            "2024-06-03 09:45:00": _bar(540.0),
            "2024-06-03 10:00:00": _bar(541.0),
        },
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "channels": {
                    "target__SPY": {
                        "channel": "target",
                        "symbol": "SPY",
                        "source": "mcp_av",
                        "verdict": "accepted",
                    }
                }
            }
        )
    )
    output = tmp_path / "aligned.parquet"
    e = _fresh_emitter()
    result = run_alignment(
        manifest_path=manifest_path,
        cache_dir=tmp_path / "cache",
        month="2024-06",
        output_path=output,
        emitter=e,
        run_id="test-align",
    )
    assert output.exists()
    assert result.total_rows > 0
    tags = [s.tag for s in e.snapshot()]
    assert tags[0] == "ALIGNMENT_RUN_STARTED"
    assert tags[-1] == "ALIGNMENT_RUN_COMPLETED"


def test_run_alignment_rejects_manifest_without_target(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "channels": {
                    "market_context__USO": {
                        "channel": "market_context",
                        "symbol": "USO",
                        "source": "mcp_av",
                        "verdict": "accepted",
                    }
                }
            }
        )
    )
    with pytest.raises(ValueError, match="no accepted target channel"):
        run_alignment(
            manifest_path=manifest_path,
            cache_dir=tmp_path,
            month="2024-06",
            output_path=tmp_path / "out.parquet",
            emitter=_fresh_emitter(),
            run_id="test",
        )
