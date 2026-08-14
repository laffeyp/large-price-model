"""Tests for the alignment pipeline (Polars join_asof on `known_at`)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest

from price_space_llm.alignment.join import (
    _third_friday_of_month,
    align_channels,
    build_rth_grid,
    enumerate_months,
    load_channel_bars,
    load_cpi_release_bars,
    load_earnings_density_bars,
    load_fomc_bars,
    load_index_daily_bars,
    load_macro_bars,
    load_options_expiry_bars,
    load_options_volume_bars,
    load_put_call_ratio_bars,
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


def test_grid_bars_are_utc_aware_edt():
    """Sprint 043: June sits in EDT (UTC-4). 09:45 EDT = 13:45 UTC."""
    grid = build_rth_grid(date(2024, 6, 3), date(2024, 6, 3))
    first_ts = grid["grid_ts"][0]
    assert first_ts.tzinfo is not None
    assert first_ts.hour == 13
    assert first_ts.minute == 45


def test_grid_bars_are_utc_aware_est():
    """Sprint 043: November after the DST change sits in EST (UTC-5). 09:45 EST = 14:45 UTC."""
    grid = build_rth_grid(date(2024, 11, 4), date(2024, 11, 4))
    first_ts = grid["grid_ts"][0]
    assert first_ts.tzinfo is not None
    assert first_ts.hour == 14
    assert first_ts.minute == 45


def test_load_channel_bars_dst_roundtrip(tmp_path: Path):
    """Sprint 043: a March EDT bar and a November EST bar both round-trip to correct UTC."""
    _write_cache(
        tmp_path,
        "target",
        "SPY",
        "2024-03",
        {
            "2024-03-15 09:45:00": _bar(510.0),  # EDT: 13:45 UTC
        },
    )
    edt = load_channel_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        tool="TIME_SERIES_INTRADAY",
        channel="target",
        symbol="SPY",
        params={
            "symbol": "SPY",
            "interval": "15min",
            "month": "2024-03",
            "outputsize": "full",
            "datatype": "json",
        },
    )
    edt_known = edt["known_at"][0]
    assert edt_known.hour == 13
    assert edt_known.minute == 46  # bar_close + 1 minute per Sprint 024
    assert edt_known.date() == datetime(2024, 3, 15).date()

    _write_cache(
        tmp_path,
        "target",
        "SPY",
        "2024-11",
        {
            "2024-11-15 09:45:00": _bar(590.0),  # EST: 14:45 UTC
        },
    )
    est = load_channel_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        tool="TIME_SERIES_INTRADAY",
        channel="target",
        symbol="SPY",
        params={
            "symbol": "SPY",
            "interval": "15min",
            "month": "2024-11",
            "outputsize": "full",
            "datatype": "json",
        },
    )
    est_known = est["known_at"][0]
    assert est_known.hour == 14
    assert est_known.minute == 46
    assert est_known.date() == datetime(2024, 11, 15).date()


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
        True,
        False,
        False,
        False,
        True,
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


def test_load_index_daily_bars_stamps_known_at_at_market_close(tmp_path: Path):
    """VIX daily close at 16:00 US/Eastern under real DST rules.
    June (EDT, UTC-4): 16:00 US/Eastern = 20:00 UTC; known_at = 20:01 UTC.
    November (EST, UTC-5): 16:00 US/Eastern = 21:00 UTC; known_at = 21:01 UTC.
    """
    _write_index_cache(
        tmp_path,
        "market_context",
        "VIX",
        [
            {"date": "2024-06-28", "open": "12.5", "high": "13.0", "low": "12.4", "close": "12.55"},
            {"date": "2024-06-27", "open": "12.6", "high": "12.9", "low": "12.5", "close": "12.60"},
            {"date": "2024-11-15", "open": "14.0", "high": "14.5", "low": "13.9", "close": "14.20"},
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
    assert bars.height == 3
    # Bars are sorted by known_at; June (EDT) rows precede the November (EST) row.
    edt_known = bars.filter(pl.col("close") == 12.60)["known_at"][0]
    assert edt_known.hour == 20
    assert edt_known.minute == 1
    assert edt_known.date() == datetime(2024, 6, 27).date()
    est_known = bars.filter(pl.col("close") == 14.20)["known_at"][0]
    assert est_known.hour == 21
    assert est_known.minute == 1
    assert est_known.date() == datetime(2024, 11, 15).date()


# load_macro_bars (Sprint 045) ---------------------------------------------


def _write_macro_cache(
    tmp_path: Path, tool: str, channel: str, symbol: str, rows: list[dict]
) -> Path:
    """Write a cached macro response (CPI/FEDFUNDS/DGS10/UNRATE/NFP)."""
    from price_space_llm.alignment.join import _default_macro_params

    params = _default_macro_params(tool)
    key = _cache.cache_key(tool, channel, symbol, params)
    path = _cache.cache_path(tmp_path, "mcp_av", tool, key)
    payload = {
        "name": f"{symbol} test",
        "interval": params.get("interval", "monthly"),
        "unit": "test",
        "data": rows,
    }
    _cache.write(path, payload)
    return path


def test_load_macro_bars_applies_known_at_lag_days(tmp_path: Path):
    """Sprint 045: known_at = value_time + known_at_lag_days at known_at_hour_utc.
    A CPI April 2024 reference-month value with 45-day lag should stamp known_at
    at 2024-05-16 12:00 UTC (April 1 + 45 days = May 16)."""
    _write_macro_cache(
        tmp_path,
        "CPI",
        "macro",
        "CPI",
        [{"date": "2024-04-01", "value": "313.548"}],
    )
    from price_space_llm.alignment.join import _default_macro_params

    bars = load_macro_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        tool="CPI",
        channel="macro",
        symbol="CPI",
        params=_default_macro_params("CPI"),
        known_at_lag_days=45,
        known_at_hour_utc=12,
    )
    assert bars.height == 1
    known = bars["known_at"][0]
    assert known.year == 2024
    assert known.month == 5
    assert known.day == 16
    assert known.hour == 16  # 04:00 UTC (00:00 EDT) + 12 hours = 16:00 UTC
    assert bars["close"][0] == 313.548
    # Macro rows fill OHLCV with value + 0 for uniform schema.
    assert bars["open"][0] == bars["close"][0]
    assert bars["high"][0] == bars["close"][0]
    assert bars["low"][0] == bars["close"][0]
    assert bars["volume"][0] == 0


def test_load_macro_bars_skips_rows_with_dot_value(tmp_path: Path):
    """Sprint 045: FRED convention writes '.' for missing macro observations."""
    _write_macro_cache(
        tmp_path,
        "FEDERAL_FUNDS_RATE",
        "macro",
        "FEDFUNDS",
        [
            {"date": "2024-06-03", "value": "5.33"},
            {"date": "2024-06-04", "value": "."},
            {"date": "2024-06-05", "value": "5.33"},
        ],
    )
    from price_space_llm.alignment.join import _default_macro_params

    bars = load_macro_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        tool="FEDERAL_FUNDS_RATE",
        channel="macro",
        symbol="FEDFUNDS",
        params=_default_macro_params("FEDERAL_FUNDS_RATE"),
        known_at_lag_days=2,
        known_at_hour_utc=13,
    )
    assert bars.height == 2  # dot-value row skipped


# load_put_call_ratio_bars (Sprint 046) -----------------------------------


def _write_pcr_cache(tmp_path: Path, symbol: str, date_str: str, value: str | None) -> Path:
    """Write a per-date HISTORICAL_PUT_CALL_RATIO cache entry."""
    from price_space_llm.ingestion import cache as _cache_mod

    params = {"symbol": symbol, "date": date_str, "datatype": "json"}
    key = _cache_mod.cache_key("HISTORICAL_PUT_CALL_RATIO", "options", symbol, params)
    path = _cache_mod.cache_path(tmp_path, "mcp_av", "HISTORICAL_PUT_CALL_RATIO", key)
    payload = {
        "symbol": symbol,
        "date": date_str,
        "put_call_ratio_full_chain": value,
        "put_call_ratio_by_expiration": [],
    }
    _cache_mod.write(path, payload)
    return path


def test_load_put_call_ratio_bars_walks_per_date_caches(tmp_path: Path):
    """Sprint 046: loader walks the tool directory and builds a time series
    from many single-date cache files."""
    _write_pcr_cache(tmp_path, "SPY", "2024-06-03", "1.11")
    _write_pcr_cache(tmp_path, "SPY", "2024-06-04", "1.12")
    _write_pcr_cache(tmp_path, "SPY", "2024-06-05", "1.27")
    # Holiday-shaped null row: loader must skip.
    _write_pcr_cache(tmp_path, "SPY", "2024-06-19", None)
    bars = load_put_call_ratio_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        symbol="SPY",
        channel="options",
        known_at_lag_days=1,
        known_at_hour_utc=13,
    )
    assert bars.height == 3  # null row skipped
    assert bars["close"].to_list() == [1.11, 1.12, 1.27]
    # known_at = value_time (2024-06-03 04:00 UTC EDT midnight) + 1d + 13h
    # = 2024-06-04 17:00 UTC.
    first_known = bars["known_at"][0]
    assert first_known.year == 2024
    assert first_known.month == 6
    assert first_known.day == 4
    assert first_known.hour == 17


def test_load_put_call_ratio_bars_ignores_other_symbols(tmp_path: Path):
    """Loader filters to `symbol`; caches for other symbols do not leak in."""
    _write_pcr_cache(tmp_path, "SPY", "2024-06-03", "1.11")
    _write_pcr_cache(tmp_path, "QQQ", "2024-06-03", "0.88")
    bars = load_put_call_ratio_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        symbol="SPY",
        channel="options",
        known_at_lag_days=1,
        known_at_hour_utc=13,
    )
    assert bars.height == 1
    assert bars["close"][0] == 1.11


# load_options_volume_bars (Sprint 047) -----------------------------------


def _write_options_cache(
    tmp_path: Path, av_symbol: str, date_str: str, contract_volumes: list[int]
) -> Path:
    """Write a per-date HISTORICAL_OPTIONS cache entry with the given per-contract
    volume values. Each row carries the underlying symbol in its `symbol` field."""
    from price_space_llm.ingestion import cache as _cache_mod

    params = {"symbol": av_symbol, "date": date_str, "datatype": "json"}
    key = _cache_mod.cache_key("HISTORICAL_OPTIONS", "options", av_symbol, params)
    path = _cache_mod.cache_path(tmp_path, "mcp_av", "HISTORICAL_OPTIONS", key)
    payload = {
        "message": "success",
        "endpoint": "HISTORICAL_OPTIONS",
        "data": [
            {
                "contractID": f"CID{i}",
                "symbol": av_symbol,
                "expiration": "2024-06-21",
                "strike": "500.00",
                "type": "call" if i % 2 == 0 else "put",
                "date": date_str,
                "volume": str(v),
                "open_interest": "100",
            }
            for i, v in enumerate(contract_volumes)
        ],
    }
    _cache_mod.write(path, payload)
    return path


def test_load_options_volume_bars_sums_across_contracts(tmp_path: Path):
    """Sprint 047: aggregate volume = sum of per-contract volume."""
    _write_options_cache(tmp_path, "SPY", "2024-06-03", [100, 200, 300, 400])
    _write_options_cache(tmp_path, "SPY", "2024-06-04", [50, 50, 50])
    bars = load_options_volume_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        symbol="VOL_SPY",
        channel="options",
        known_at_lag_days=1,
        known_at_hour_utc=13,
        av_symbol="SPY",
    )
    assert bars.height == 2
    # DataFrame's `symbol` field carries the manifest-visible identifier, not the AV underlying.
    assert bars["symbol"].unique().to_list() == ["VOL_SPY"]
    assert bars["close"].to_list() == [1000.0, 150.0]


def test_load_options_volume_bars_filters_by_av_symbol(tmp_path: Path):
    """Cached files for other underlyings do not leak in."""
    _write_options_cache(tmp_path, "SPY", "2024-06-03", [1000])
    _write_options_cache(tmp_path, "QQQ", "2024-06-03", [9999])
    bars = load_options_volume_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        symbol="VOL_SPY",
        channel="options",
        known_at_lag_days=1,
        known_at_hour_utc=13,
        av_symbol="SPY",
    )
    assert bars.height == 1
    assert bars["close"][0] == 1000.0


def test_load_options_volume_bars_raises_on_empty_directory(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="no HISTORICAL_OPTIONS cache"):
        load_options_volume_bars(
            cache_dir=tmp_path,
            source="mcp_av",
            symbol="VOL_SPY",
            channel="options",
            known_at_lag_days=1,
            known_at_hour_utc=13,
            av_symbol="SPY",
        )


def test_load_put_call_ratio_bars_av_symbol_split(tmp_path: Path):
    """Sprint 047: av_symbol lets manifest identity (symbol='PCR_SPY') differ from
    AV underlying (av_symbol='SPY'). The returned DataFrame uses `symbol` for
    aligned-column identity but filters cache by `av_symbol`."""
    _write_pcr_cache(tmp_path, "SPY", "2024-06-03", "1.11")
    bars = load_put_call_ratio_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        symbol="PCR_SPY",
        channel="options",
        known_at_lag_days=1,
        known_at_hour_utc=13,
        av_symbol="SPY",
    )
    assert bars.height == 1
    assert bars["symbol"][0] == "PCR_SPY"
    assert bars["close"][0] == 1.11


def test_load_put_call_ratio_bars_raises_on_empty_directory(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="no HISTORICAL_PUT_CALL_RATIO cache"):
        load_put_call_ratio_bars(
            cache_dir=tmp_path,
            source="mcp_av",
            symbol="SPY",
            channel="options",
            known_at_lag_days=1,
            known_at_hour_utc=13,
        )


def test_run_alignment_dispatches_macro_channel(tmp_path: Path):
    """Sprint 045: manifest tool=CPI routes to load_macro_bars via run_alignment
    dispatch, and the macro value forward-fills onto every RTH grid bar with
    known_at <= grid_ts."""
    _write_cache(
        tmp_path / "cache",
        "target",
        "SPY",
        "2024-06",
        {"2024-06-03 09:45:00": _bar(540.0)},
    )
    _write_macro_cache(
        tmp_path / "cache",
        "CPI",
        "macro",
        "CPI",
        [
            {"date": "2024-04-01", "value": "313.548"},  # known_at = 2024-05-16 16:00 UTC
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
                    "macro__CPI": {
                        "channel": "macro",
                        "symbol": "CPI",
                        "source": "mcp_av",
                        "tool": "CPI",
                        "verdict": "accepted",
                        "known_at_lag_days": 45,
                        "known_at_hour_utc": 12,
                    },
                }
            }
        )
    )
    output = tmp_path / "aligned.parquet"
    e = _fresh_emitter(max_buffer=32768)
    run_alignment(
        manifest_path=manifest_path,
        cache_dir=tmp_path / "cache",
        months=["2024-06"],
        output_path=output,
        emitter=e,
        run_id="test-align-macro",
    )
    aligned = pl.read_parquet(output)
    # The April 2024 CPI value (known_at May 16) is visible on every June 2024 RTH bar.
    non_null = aligned.filter(pl.col("macro__CPI__close").is_not_null())
    assert non_null.height > 0
    assert non_null["macro__CPI__close"].unique().to_list() == [313.548]


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


# event channels (Sprint 048) --------------------------------------------


def _write_earnings_cache(tmp_path: Path, ticker: str, reported_dates: list[str]) -> Path:
    """Write a per-symbol EARNINGS cache entry with the given reportedDate list."""
    from price_space_llm.ingestion import cache as _cache_mod

    params = {"symbol": ticker, "datatype": "json"}
    key = _cache_mod.cache_key("EARNINGS", "event", ticker, params)
    path = _cache_mod.cache_path(tmp_path, "mcp_av", "EARNINGS", key)
    payload = {
        "symbol": ticker,
        "annualEarnings": [],
        "quarterlyEarnings": [
            {"fiscalDateEnding": d, "reportedDate": d, "reportedEPS": "1.00"}
            for d in reported_dates
        ],
    }
    _cache_mod.write(path, payload)
    return path


def test_load_earnings_density_bars_counts_across_tickers(tmp_path: Path):
    """Sprint 048: two tickers reporting the same date produce close=2 on that date."""
    _write_earnings_cache(tmp_path, "AAPL", ["2023-01-25", "2023-04-27"])
    _write_earnings_cache(tmp_path, "MSFT", ["2023-01-25", "2023-04-25"])
    _write_earnings_cache(tmp_path, "GOOG", ["2023-04-25"])
    bars = load_earnings_density_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        channel="event",
        symbol="EARNINGS_DENSITY_SPX",
    )
    assert bars.height == 3  # 01-25, 04-25, 04-27
    by_date = {b["known_at"].date(): b["close"] for b in bars.iter_rows(named=True)}
    assert by_date[date(2023, 1, 25)] == 2.0
    assert by_date[date(2023, 4, 25)] == 2.0
    assert by_date[date(2023, 4, 27)] == 1.0


def test_load_earnings_density_bars_ignores_missing_reported_dates(tmp_path: Path):
    """Rows with no reportedDate get skipped, not counted as null."""
    from price_space_llm.ingestion import cache as _cache_mod

    params = {"symbol": "AAPL", "datatype": "json"}
    key = _cache_mod.cache_key("EARNINGS", "event", "AAPL", params)
    path = _cache_mod.cache_path(tmp_path, "mcp_av", "EARNINGS", key)
    payload = {
        "symbol": "AAPL",
        "quarterlyEarnings": [
            {"fiscalDateEnding": "2023-01-25", "reportedDate": "2023-01-25"},
            {"fiscalDateEnding": "2023-04-27", "reportedDate": None},
        ],
    }
    _cache_mod.write(path, payload)
    bars = load_earnings_density_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        channel="event",
        symbol="EARNINGS_DENSITY_SPX",
    )
    assert bars.height == 1
    assert bars["close"][0] == 1.0


def test_load_earnings_density_bars_raises_on_missing_cache_dir(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="no EARNINGS cache"):
        load_earnings_density_bars(
            cache_dir=tmp_path,
            source="mcp_av",
            channel="event",
            symbol="EARNINGS_DENSITY_SPX",
        )


def test_load_fomc_bars_loads_curated_dates(tmp_path: Path):
    """Sprint 048: FOMC static table produces one row per meeting date."""
    static_path = tmp_path / "fomc.json"
    static_path.write_text(json.dumps({"dates": ["2023-03-22", "2023-05-03", "2023-06-14"]}))
    bars = load_fomc_bars(static_path=static_path, channel="event", symbol="FOMC")
    assert bars.height == 3
    assert bars["close"].to_list() == [1.0, 1.0, 1.0]
    # 2023-03-22 midnight ET = 04:00 UTC (EDT, UTC-4).
    first = bars["known_at"][0]
    assert first.date() == date(2023, 3, 22)
    assert first.hour == 4


def test_load_options_expiry_bars_third_friday(tmp_path: Path):
    """Sprint 048: options expiry = third Friday of the month, deterministic.
    January 2023 third Friday = 2023-01-20."""
    bars = load_options_expiry_bars(
        start=date(2023, 1, 1),
        end=date(2023, 1, 31),
        channel="event",
        symbol="OPTIONS_EXPIRY",
    )
    assert bars.height == 1
    assert bars["known_at"][0].date() == date(2023, 1, 20)


def test_load_options_expiry_bars_rolls_forward_on_good_friday(tmp_path: Path):
    """Sprint 048: 2022-04-15 was Good Friday; SPY monthly options rolled to
    Thursday 2022-04-14 per CBOE convention."""
    bars = load_options_expiry_bars(
        start=date(2022, 4, 1),
        end=date(2022, 4, 30),
        channel="event",
        symbol="OPTIONS_EXPIRY",
    )
    assert bars.height == 1
    assert bars["known_at"][0].date() == date(2022, 4, 14)


def test_load_options_expiry_bars_spans_year(tmp_path: Path):
    """A full 2023 range produces 12 expiries, one per month."""
    bars = load_options_expiry_bars(
        start=date(2023, 1, 1),
        end=date(2023, 12, 31),
        channel="event",
        symbol="OPTIONS_EXPIRY",
    )
    assert bars.height == 12


def test_third_friday_arithmetic():
    """Direct sanity checks against known third Fridays."""
    assert _third_friday_of_month(2023, 1) == date(2023, 1, 20)
    assert _third_friday_of_month(2023, 6) == date(2023, 6, 16)
    assert _third_friday_of_month(2024, 3) == date(2024, 3, 15)
    # 2022-04-15 is the raw third Friday; rollback lookup lives in the loader.
    assert _third_friday_of_month(2022, 4) == date(2022, 4, 15)


def test_load_cpi_release_bars_stamps_from_macro_cpi_cache(tmp_path: Path):
    """Sprint 048: CPI release event dates derive from the macro__CPI cache using
    the Sprint 045 known-at rule (reference_month + 45 days at 12 UTC)."""
    _write_macro_cache(
        tmp_path,
        "CPI",
        "macro",
        "CPI",
        [
            {"date": "2024-04-01", "value": "313.548"},
            {"date": "2024-03-01", "value": "312.332"},
        ],
    )
    bars = load_cpi_release_bars(
        cache_dir=tmp_path,
        source="mcp_av",
        channel="event",
        symbol="CPI_RELEASE",
        known_at_lag_days=45,
        known_at_hour_utc=12,
    )
    assert bars.height == 2
    assert bars["close"].to_list() == [1.0, 1.0]
    # April 2024 + 45 days = May 16 2024; + 12 UTC = 2024-05-16 16:00 UTC (04:00 EDT + 12h).
    april_row = bars.filter(pl.col("known_at").dt.month() == 5).head(1)
    known = april_row["known_at"][0]
    assert known.day == 16


def test_load_cpi_release_bars_raises_on_missing_cache(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="cache miss for macro__CPI"):
        load_cpi_release_bars(
            cache_dir=tmp_path,
            source="mcp_av",
            channel="event",
            symbol="CPI_RELEASE",
            known_at_lag_days=45,
            known_at_hour_utc=12,
        )


def test_run_alignment_dispatches_event_channels(tmp_path: Path):
    """Sprint 048: the four event tools each route through their own loader
    branch and land in the aligned parquet as event__{symbol}__close columns."""
    _write_cache(
        tmp_path / "cache",
        "target",
        "SPY",
        "2023-01",
        {"2023-01-20 09:45:00": _bar(400.0)},
    )
    _write_earnings_cache(tmp_path / "cache", "AAPL", ["2023-01-20"])
    _write_macro_cache(
        tmp_path / "cache",
        "CPI",
        "macro",
        "CPI",
        [{"date": "2022-12-01", "value": "300.0"}],
    )
    fomc_path = tmp_path / "fomc.json"
    fomc_path.write_text(json.dumps({"dates": ["2023-01-20"]}))
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
                    "event__EARNINGS_DENSITY_SPX": {
                        "channel": "event",
                        "symbol": "EARNINGS_DENSITY_SPX",
                        "source": "mcp_av",
                        "tool": "EARNINGS",
                        "verdict": "accepted",
                    },
                    "event__FOMC": {
                        "channel": "event",
                        "symbol": "FOMC",
                        "source": "static",
                        "tool": "STATIC_FOMC",
                        "verdict": "accepted",
                        "static_path": str(fomc_path),
                    },
                    "event__CPI_RELEASE": {
                        "channel": "event",
                        "symbol": "CPI_RELEASE",
                        "source": "mcp_av",
                        "tool": "STATIC_CPI_RELEASE",
                        "verdict": "accepted",
                        "known_at_lag_days": 45,
                        "known_at_hour_utc": 12,
                    },
                    "event__OPTIONS_EXPIRY": {
                        "channel": "event",
                        "symbol": "OPTIONS_EXPIRY",
                        "source": "deterministic",
                        "tool": "DETERMINISTIC_OPTIONS_EXPIRY",
                        "verdict": "accepted",
                    },
                }
            }
        )
    )
    output = tmp_path / "aligned.parquet"
    e = _fresh_emitter(max_buffer=32768)
    run_alignment(
        manifest_path=manifest_path,
        cache_dir=tmp_path / "cache",
        months=["2023-01"],
        output_path=output,
        emitter=e,
        run_id="test-align-events",
    )
    aligned = pl.read_parquet(output)
    for col in (
        "event__EARNINGS_DENSITY_SPX__close",
        "event__FOMC__close",
        "event__CPI_RELEASE__close",
        "event__OPTIONS_EXPIRY__close",
    ):
        assert col in aligned.columns, f"missing {col}"
    # January 2023 has exactly one options expiry (2023-01-20). Every RTH bar
    # at or after 2023-01-20 04:00 UTC forward-fills to close=1.
    expiry_visible = aligned.filter(pl.col("event__OPTIONS_EXPIRY__close") == 1.0)
    assert expiry_visible.height > 0


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
