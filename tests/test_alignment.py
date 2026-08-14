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
    enumerate_months,
    load_channel_bars,
    load_index_daily_bars,
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
    # Sprint 042: bars carry full OHLCV, not close-only, so downstream features can read them.
    assert set(df.columns) == {
        "known_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "channel",
        "symbol",
    }
    assert df["close"].to_list() == [540.0, 541.0]


def test_align_channels_emits_ohlcv_columns_per_channel():
    """Sprint 042 §5: aligned parquet carries {open, high, low, close, volume} per channel."""
    e = _fresh_emitter()
    grid = pl.DataFrame(
        {
            "grid_ts": [
                datetime.fromisoformat("2024-06-03T14:45:00+00:00"),
                datetime.fromisoformat("2024-06-03T15:00:00+00:00"),
            ]
        }
    )
    bars = pl.DataFrame(
        {
            "known_at": [datetime.fromisoformat("2024-06-03T14:31:00+00:00")],
            "open": [539.5],
            "high": [540.5],
            "low": [539.0],
            "close": [540.0],
            "volume": [1000000],
            "channel": ["target"],
            "symbol": ["SPY"],
        }
    )
    aligned = align_channels(grid, {"target__SPY": bars}, e)
    for field in ("open", "high", "low", "close", "volume"):
        col = f"target__SPY__{field}"
        assert col in aligned.columns, f"missing {col}"
    assert aligned["target__SPY__open"].to_list() == [539.5, 539.5]
    assert aligned["target__SPY__high"].to_list() == [540.5, 540.5]
    assert aligned["target__SPY__low"].to_list() == [539.0, 539.0]
    assert aligned["target__SPY__volume"].to_list() == [1000000, 1000000]


def test_align_channels_missing_mask_true_when_no_prior_observation():
    """Sprint 042 §5: missing_mask__{key} is True at any grid_ts before the channel's
    first known_at."""
    e = _fresh_emitter()
    grid = pl.DataFrame(
        {
            "grid_ts": [
                datetime.fromisoformat("2024-06-03T14:45:00+00:00"),
                datetime.fromisoformat("2024-06-03T15:00:00+00:00"),
            ]
        }
    )
    bars = pl.DataFrame(
        {
            # First observation lands AFTER the first grid_ts.
            "known_at": [datetime.fromisoformat("2024-06-03T14:50:00+00:00")],
            "close": [540.0],
            "channel": ["target"],
            "symbol": ["SPY"],
        }
    )
    aligned = align_channels(grid, {"target__SPY": bars}, e)
    assert aligned["missing_mask__target__SPY"].to_list() == [True, False]


def test_align_channels_observed_at_this_grid_step_and_age_since_known_at():
    """Sprint 042 §5: observed_at_this_grid_step flips True when the picked known_at
    differs from the previous grid step's; age_since_known_at counts up between
    fresh observations and resets to 0 on each fresh one.
    """
    e = _fresh_emitter()
    grid = pl.DataFrame(
        {
            "grid_ts": [
                datetime.fromisoformat("2024-06-03T14:45:00+00:00"),
                datetime.fromisoformat("2024-06-03T15:00:00+00:00"),
                datetime.fromisoformat("2024-06-03T15:15:00+00:00"),
                datetime.fromisoformat("2024-06-03T15:30:00+00:00"),
                datetime.fromisoformat("2024-06-03T15:45:00+00:00"),
            ]
        }
    )
    # Bars known at 14:31 and 15:31 UTC. Grid 14:45 sees the 14:31 bar; 15:00 and 15:15
    # still see 14:31 (backward-fill); 15:30 sees 14:31; 15:45 sees the new 15:31 bar.
    bars = pl.DataFrame(
        {
            "known_at": [
                datetime.fromisoformat("2024-06-03T14:31:00+00:00"),
                datetime.fromisoformat("2024-06-03T15:31:00+00:00"),
            ],
            "close": [540.0, 541.0],
            "channel": ["target", "target"],
            "symbol": ["SPY", "SPY"],
        }
    )
    aligned = align_channels(grid, {"target__SPY": bars}, e)
    # 14:45 = first-ever observation (fresh); 15:00, 15:15, 15:30 = same known_at as prior
    # (not fresh); 15:45 = new known_at (fresh again).
    assert aligned["observed_at_this_grid_step__target__SPY"].to_list() == [
        True, False, False, False, True,
    ]
    # age counter: 0 at 14:45 (fresh), 1 at 15:00, 2 at 15:15, 3 at 15:30, 0 at 15:45.
    assert aligned["age_since_known_at__target__SPY"].to_list() == [0, 1, 2, 3, 0]


def test_align_channels_age_stays_zero_while_missing_mask_true():
    """Sprint 042 §5: age_since_known_at is 0 (and observed=False) while the channel
    has produced no observations yet."""
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
            # First observation lands after every grid row.
            "known_at": [datetime.fromisoformat("2024-06-03T16:00:00+00:00")],
            "close": [540.0],
            "channel": ["target"],
            "symbol": ["SPY"],
        }
    )
    aligned = align_channels(grid, {"target__SPY": bars}, e)
    assert aligned["missing_mask__target__SPY"].to_list() == [True, True, True]
    assert aligned["observed_at_this_grid_step__target__SPY"].to_list() == [False, False, False]
    assert aligned["age_since_known_at__target__SPY"].to_list() == [0, 0, 0]


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
        months=["2024-06"],
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
            months=["2024-06"],
            output_path=tmp_path / "out.parquet",
            emitter=_fresh_emitter(),
            run_id="test",
        )


# enumerate_months ---------------------------------------------------------


def test_enumerate_months_single():
    assert enumerate_months("2024-06", "2024-06") == ["2024-06"]


def test_enumerate_months_within_year():
    assert enumerate_months("2024-06", "2024-08") == ["2024-06", "2024-07", "2024-08"]


def test_enumerate_months_crosses_year():
    got = enumerate_months("2022-11", "2023-02")
    assert got == ["2022-11", "2022-12", "2023-01", "2023-02"]


def test_enumerate_months_rejects_reverse():
    with pytest.raises(ValueError, match=r"start_month .* > end_month"):
        enumerate_months("2024-08", "2024-06")


def test_enumerate_months_rejects_malformed():
    with pytest.raises(ValueError, match="YYYY-MM"):
        enumerate_months("2024/06", "2024-08")


def test_enumerate_months_rejects_out_of_range_index():
    with pytest.raises(ValueError, match="out of range"):
        enumerate_months("2024-13", "2024-14")


# run_alignment multi-month -------------------------------------------------


def test_run_alignment_concatenates_across_months(tmp_path: Path):
    """Two months of cached bars → one aligned parquet spanning both months."""
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
    _write_cache(
        tmp_path / "cache",
        "target",
        "SPY",
        "2024-07",
        {
            "2024-07-01 09:45:00": _bar(550.0),
            "2024-07-01 10:00:00": _bar(551.0),
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
    e = _fresh_emitter(max_buffer=32768)
    result = run_alignment(
        manifest_path=manifest_path,
        cache_dir=tmp_path / "cache",
        months=["2024-06", "2024-07"],
        output_path=output,
        emitter=e,
        run_id="test-align-range",
    )
    assert output.exists()
    # Grid spans 2024-06-01 through 2024-07-31: 43 weekdays * 26 bars = 1118 rows.
    assert result.total_rows == 1118

    started = next(s for s in e.snapshot() if s.tag == "ALIGNMENT_RUN_STARTED")
    assert started.payload["date_range_start"] == "2024-06-01"
    assert started.payload["date_range_end"] == "2024-07-31"


# load_index_daily_bars (Sprint 038) ---------------------------------------


def _write_index_cache(tmp_path: Path, channel: str, symbol: str, rows: list[dict]) -> Path:
    """Write a cached INDEX_DATA response with the given daily rows."""
    params = {"symbol": symbol, "interval": "daily", "datatype": "json"}
    key = _cache.cache_key("INDEX_DATA", channel, symbol, params)
    path = _cache.cache_path(tmp_path, "mcp_av", "INDEX_DATA", key)
    payload = {
        "symbol": symbol,
        "name": f"{symbol} test",
        "interval": "daily",
        "data": rows,
    }
    _cache.write(path, payload)
    return path


def test_load_index_daily_bars_stamps_known_at_at_21_utc(tmp_path: Path):
    """VIX daily close at 16:00 US/Eastern (fixed -5) → 21:00 UTC; known_at = +1min."""
    _write_index_cache(
        tmp_path,
        "market_context",
        "VIX",
        [
            {"date": "2024-06-28", "open": "12.5", "high": "13.0", "low": "12.4", "close": "12.55"},
            {"date": "2024-06-27", "open": "12.6", "high": "12.9", "low": "12.5", "close": "12.60"},
        ],
    )
    bars = load_index_daily_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        tool="INDEX_DATA",
        channel="market_context",
        symbol="VIX",
        params={"symbol": "VIX", "interval": "daily", "datatype": "json"},
    )
    assert bars.height == 2
    assert bars["close"].to_list() == [12.60, 12.55]  # sorted by known_at ascending
    first_known = bars["known_at"][0]
    assert first_known.hour == 21
    assert first_known.minute == 1
    assert first_known.date() == datetime(2024, 6, 27).date()


def test_load_index_daily_bars_raises_on_empty_data(tmp_path: Path):
    _write_index_cache(tmp_path, "market_context", "VIX", [])
    with pytest.raises(ValueError, match="no non-empty 'data' list"):
        load_index_daily_bars(
            cache_dir=tmp_path,
            source="mcp_av",
            tool="INDEX_DATA",
            channel="market_context",
            symbol="VIX",
            params={"symbol": "VIX", "interval": "daily", "datatype": "json"},
        )


def test_run_alignment_dispatches_index_data_channel(tmp_path: Path):
    """One INDEX_DATA channel + one TIME_SERIES_INTRADAY channel align together;
    the daily VIX close forward-fills onto every 15-min RTH bar after it."""
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
    _write_index_cache(
        tmp_path / "cache",
        "market_context",
        "VIX",
        [
            {"date": "2024-05-31", "open": "12.5", "high": "13.0", "low": "12.4", "close": "12.92"},
        ],
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
                        "tool": "TIME_SERIES_INTRADAY",
                        "verdict": "accepted",
                    },
                    "market_context__VIX": {
                        "channel": "market_context",
                        "symbol": "VIX",
                        "source": "mcp_av",
                        "tool": "INDEX_DATA",
                        "verdict": "accepted",
                    },
                }
            }
        )
    )
    output = tmp_path / "aligned.parquet"
    e = _fresh_emitter(max_buffer=32768)
    result = run_alignment(
        manifest_path=manifest_path,
        cache_dir=tmp_path / "cache",
        months=["2024-06"],
        output_path=output,
        emitter=e,
        run_id="test-align-index",
    )
    aligned = pl.read_parquet(output)
    # Every RTH bar in June sees the 2024-05-31 close = 12.92 (Fri before Mon 06-03).
    non_null_vix = aligned.filter(pl.col("market_context__VIX__close").is_not_null())
    assert non_null_vix.height > 0
    assert non_null_vix["market_context__VIX__close"].unique().to_list() == [12.92]
    assert result.total_rows > 0


def test_run_alignment_rejects_unsupported_tool(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "channels": {
                    "target__SPY": {
                        "channel": "target",
                        "symbol": "SPY",
                        "source": "mcp_av",
                        "tool": "NONESUCH_ENDPOINT",
                        "verdict": "accepted",
                    }
                }
            }
        )
    )
    with pytest.raises(ValueError, match=r"unsupported tool"):
        run_alignment(
            manifest_path=manifest_path,
            cache_dir=tmp_path,
            months=["2024-06"],
            output_path=tmp_path / "out.parquet",
            emitter=_fresh_emitter(),
            run_id="test",
        )


def test_run_alignment_rejects_empty_months(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"channels": {}}))
    with pytest.raises(ValueError, match="months must not be empty"):
        run_alignment(
            manifest_path=manifest_path,
            cache_dir=tmp_path,
            months=[],
            output_path=tmp_path / "out.parquet",
            emitter=_fresh_emitter(),
            run_id="test",
        )
