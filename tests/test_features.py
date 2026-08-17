"""Tests for the feature pipeline (strictly-causal rolling windows over aligned bars)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from price_space_llm.features.compute import (
    FEATURE_SPECS,
    ROLLING_WINDOW,
    compute_features,
    run_feature_pipeline,
)
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary


def _fresh_emitter(max_buffer: int = 16384) -> StrictSignalEmitter:
    """Feature pipeline emits N_rows x N_features x N_channels signals; bump buffer."""
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


def _synthetic_aligned(n_rows: int, closes: list[float] | None = None) -> pl.DataFrame:
    """One-channel aligned DataFrame with monotonic timestamps and given closes.

    Sprint 049: adds synthetic OHLCV columns so target-feature block has inputs.
    open=close-0.1, high=close+0.2, low=close-0.2, volume=1_000_000.
    """
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n_rows)]
    known_at = [t + timedelta(seconds=1) for t in grid_ts]
    if closes is None:
        closes = [540.0 + i * 0.1 for i in range(n_rows)]
    return pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__open": [c - 0.1 for c in closes],
            "target__SPY__high": [c + 0.2 for c in closes],
            "target__SPY__low": [c - 0.2 for c in closes],
            "target__SPY__close": closes,
            "target__SPY__volume": [1_000_000 for _ in closes],
        }
    )


def test_compute_features_shape_and_columns():
    aligned = _synthetic_aligned(n_rows=30)
    e = _fresh_emitter()
    features, _ = compute_features(aligned, e)
    assert features.height == 30
    for name in FEATURE_SPECS:
        assert f"target__SPY__{name}" in features.columns


def test_log_return_is_null_on_first_row():
    aligned = _synthetic_aligned(n_rows=5)
    e = _fresh_emitter()
    features, _ = compute_features(aligned, e)
    assert features["target__SPY__log_return"][0] is None
    assert features["target__SPY__log_return"][1] is not None


def test_log_return_matches_math_ln_of_ratio():
    closes = [100.0, 101.0, 102.0]
    aligned = _synthetic_aligned(n_rows=3, closes=closes)
    e = _fresh_emitter()
    features, _ = compute_features(aligned, e)
    expected = math.log(101.0 / 100.0)
    assert features["target__SPY__log_return"][1] == pytest_approx(expected)


def test_rolling_windows_null_before_full_window():
    aligned = _synthetic_aligned(n_rows=ROLLING_WINDOW + 2)
    e = _fresh_emitter()
    features, _ = compute_features(aligned, e)
    # Rolling mean of log_return needs 20 log_return values; log_return itself is null
    # at index 0, so rolling_mean_20 is null through index ROLLING_WINDOW - 1.
    assert features["target__SPY__rolling_mean_20"][ROLLING_WINDOW - 1] is None
    assert features["target__SPY__rolling_mean_20"][ROLLING_WINDOW] is not None


def test_feature_computed_and_failed_emits():
    aligned = _synthetic_aligned(n_rows=5)
    e = _fresh_emitter()
    compute_features(aligned, e)
    tags = [s.tag for s in e.snapshot()]
    assert "FEATURE_COMPUTED" in tags
    assert "FEATURE_COMPUTATION_FAILED" in tags


def test_failure_reason_insufficient_history_on_first_log_return():
    aligned = _synthetic_aligned(n_rows=3)
    e = _fresh_emitter()
    compute_features(aligned, e)
    fails = [s for s in e.snapshot() if s.tag == "FEATURE_COMPUTATION_FAILED"]
    first_log_ret_fail = next(s for s in fails if s.payload["feature_name"] == "log_return")
    assert first_log_ret_fail.payload["reason"] == "insufficient_history"


def test_failure_reason_nan_input_on_null_close():
    """A null close in the aligned frame → nan_input on every feature at that row."""
    aligned = _synthetic_aligned(n_rows=5)
    aligned = aligned.with_columns(
        pl.when(pl.col("grid_ts") == aligned["grid_ts"][2])
        .then(None)
        .otherwise(pl.col("target__SPY__close"))
        .alias("target__SPY__close")
    )
    e = _fresh_emitter()
    compute_features(aligned, e)
    fails = [s for s in e.snapshot() if s.tag == "FEATURE_COMPUTATION_FAILED"]
    row2_fails = [s for s in fails if s.payload["timestamp"].startswith("2024-06-03T15:15")]
    assert any(s.payload["reason"] == "nan_input" for s in row2_fails)


def test_run_feature_pipeline_writes_parquet(tmp_path: Path):
    aligned = _synthetic_aligned(n_rows=25)
    aligned_path = tmp_path / "aligned.parquet"
    aligned.write_parquet(aligned_path)
    output_path = tmp_path / "features.parquet"
    e = _fresh_emitter()
    result = run_feature_pipeline(
        aligned_path=aligned_path,
        output_path=output_path,
        emitter=e,
        run_id="test-features",
    )
    assert output_path.exists()
    df = pl.read_parquet(output_path)
    assert df.height == 25
    assert result.n_failures > 0  # rolling windows produce failures on early rows
    assert result.n_features_emitted > 0


def test_two_channels_produce_expected_feature_columns():
    """Sprint 049 + 069: target = FEATURE_SPECS (4) + TARGET_FEATURE_SPECS (6);
    market_context = FEATURE_SPECS (4) + CROSS_ASSET_FEATURE_SPECS (3)."""
    from price_space_llm.features.compute import (
        CROSS_ASSET_FEATURE_SPECS,
        TARGET_FEATURE_SPECS,
    )

    aligned = _synthetic_aligned(n_rows=5)
    aligned = aligned.with_columns(
        [
            pl.lit(80.0).alias("market_context__USO__close"),
            pl.lit(79.9).alias("market_context__USO__open"),
            pl.lit(80.2).alias("market_context__USO__high"),
            pl.lit(79.7).alias("market_context__USO__low"),
            pl.lit(500_000).alias("market_context__USO__volume"),
            pl.col("target__SPY__known_at").alias("market_context__USO__known_at"),
        ]
    )
    e = _fresh_emitter()
    features, _ = compute_features(aligned, e)
    feature_cols = [c for c in features.columns if c != "grid_ts"]
    expected = (
        len(FEATURE_SPECS)
        + len(TARGET_FEATURE_SPECS)
        + len(FEATURE_SPECS)
        + len(CROSS_ASSET_FEATURE_SPECS)
    )
    assert len(feature_cols) == expected  # 4 + 6 + 4 + 3 = 17


# target features (Sprint 049) ---------------------------------------------


def _target_frame(n_rows: int, opens, highs, lows, closes, volumes) -> pl.DataFrame:
    """Explicit-OHLCV target-only aligned frame for target-feature tests."""
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n_rows)]
    known_at = [t + timedelta(seconds=1) for t in grid_ts]
    return pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__open": opens,
            "target__SPY__high": highs,
            "target__SPY__low": lows,
            "target__SPY__close": closes,
            "target__SPY__volume": volumes,
        }
    )


def test_bar_shape_matches_formula():
    """bar_shape = (close - open) / (high - low + eps). Rising bar: positive; falling: negative."""
    df = _target_frame(
        n_rows=3,
        opens=[100.0, 100.0, 100.0],
        highs=[102.0, 102.0, 102.0],
        lows=[99.0, 99.0, 99.0],
        closes=[101.5, 99.5, 100.0],
        volumes=[1000, 1000, 1000],
    )
    features, _ = compute_features(df, _fresh_emitter())
    got = features["target__SPY__bar_shape"].to_list()
    assert got[0] == pytest_approx((101.5 - 100.0) / (102.0 - 99.0 + 1e-12))
    assert got[1] == pytest_approx((99.5 - 100.0) / (102.0 - 99.0 + 1e-12))
    assert got[2] == pytest_approx(0.0)


def test_bar_shape_survives_flat_bar():
    """A flat bar (high == low) does not raise; eps keeps the divisor positive; value = 0."""
    df = _target_frame(
        n_rows=1,
        opens=[100.0],
        highs=[100.0],
        lows=[100.0],
        closes=[100.0],
        volumes=[1000],
    )
    features, _ = compute_features(df, _fresh_emitter())
    assert features["target__SPY__bar_shape"][0] == pytest_approx(0.0)


def test_range_pct_uses_prior_close():
    """range_pct = (high - low) / close_{t-1}. Row 0 is null."""
    df = _target_frame(
        n_rows=3,
        opens=[100.0, 100.0, 100.0],
        highs=[102.0, 103.0, 101.0],
        lows=[99.0, 98.0, 99.5],
        closes=[100.0, 101.0, 100.5],
        volumes=[1000, 1000, 1000],
    )
    features, _ = compute_features(df, _fresh_emitter())
    got = features["target__SPY__range_pct"].to_list()
    assert got[0] is None
    assert got[1] == pytest_approx((103.0 - 98.0) / 100.0)
    assert got[2] == pytest_approx((101.0 - 99.5) / 101.0)


def test_dollar_volume_is_close_times_volume():
    df = _target_frame(
        n_rows=2,
        opens=[100.0, 100.0],
        highs=[101.0, 101.0],
        lows=[99.0, 99.0],
        closes=[100.5, 100.0],
        volumes=[2000, 4000],
    )
    features, _ = compute_features(df, _fresh_emitter())
    got = features["target__SPY__dollar_volume"].to_list()
    assert got[0] == pytest_approx(100.5 * 2000)
    assert got[1] == pytest_approx(100.0 * 4000)


def test_spread_proxy_matches_corwin_schultz_style():
    """spread_proxy = 2 * |high - low| / (high + low)."""
    df = _target_frame(
        n_rows=1,
        opens=[100.0],
        highs=[102.0],
        lows=[98.0],
        closes=[100.0],
        volumes=[1000],
    )
    features, _ = compute_features(df, _fresh_emitter())
    expected = 2.0 * (102.0 - 98.0) / (102.0 + 98.0)
    assert features["target__SPY__spread_proxy"][0] == pytest_approx(expected)


def test_realized_vol_30_null_before_full_window():
    """realized_vol_30 uses 30-bar rolling std of log_return; log_return itself is
    null at row 0, so realized_vol_30 is null through row 30 inclusive."""
    closes = [100.0 * (1.0 + 0.001 * ((-1) ** i)) for i in range(35)]
    df = _target_frame(
        n_rows=35,
        opens=closes,
        highs=[c * 1.001 for c in closes],
        lows=[c * 0.999 for c in closes],
        closes=closes,
        volumes=[1000] * 35,
    )
    features, _ = compute_features(df, _fresh_emitter())
    got = features["target__SPY__realized_vol_30"].to_list()
    # Row 29 sees only 29 valid log_return values (rows 1-29); the rolling_std
    # window needs 30, so it's null.
    assert got[29] is None
    assert got[30] is not None


def test_volume_z_100_null_through_row_99():
    """volume_z_100 uses 100-bar rolling stats over volume; null through row 99."""
    closes = [100.0 + 0.1 * i for i in range(105)]
    df = _target_frame(
        n_rows=105,
        opens=closes,
        highs=[c + 0.5 for c in closes],
        lows=[c - 0.5 for c in closes],
        closes=closes,
        volumes=[1000 + i for i in range(105)],
    )
    features, _ = compute_features(df, _fresh_emitter())
    got = features["target__SPY__volume_z_100"].to_list()
    assert got[98] is None
    # Row 99 has 100 volume values (indices 0-99), so rolling_std is defined.
    assert got[99] is not None


def test_target_only_features_do_not_leak_to_market_context():
    """Sprint 069: target-only features (range_pct, dollar_volume, spread_proxy) do
    not leak to market_context. Cross-asset features (bar_shape, volume_z_100,
    realized_vol_30) DO ship on market_context per spec § 6."""
    df = _target_frame(
        n_rows=5,
        opens=[100.0] * 5,
        highs=[101.0] * 5,
        lows=[99.0] * 5,
        closes=[100.0] * 5,
        volumes=[1000] * 5,
    )
    df = df.with_columns(
        [
            pl.lit(80.0).alias("market_context__USO__close"),
            pl.lit(79.9).alias("market_context__USO__open"),
            pl.lit(80.2).alias("market_context__USO__high"),
            pl.lit(79.7).alias("market_context__USO__low"),
            pl.lit(500_000).alias("market_context__USO__volume"),
            pl.col("target__SPY__known_at").alias("market_context__USO__known_at"),
        ]
    )
    features, _ = compute_features(df, _fresh_emitter())
    # Target-only features on target, absent on market_context.
    assert "target__SPY__range_pct" in features.columns
    assert "target__SPY__dollar_volume" in features.columns
    assert "target__SPY__spread_proxy" in features.columns
    assert "market_context__USO__range_pct" not in features.columns
    assert "market_context__USO__dollar_volume" not in features.columns
    assert "market_context__USO__spread_proxy" not in features.columns
    # Cross-asset features on both.
    assert "target__SPY__bar_shape" in features.columns
    assert "market_context__USO__bar_shape" in features.columns
    assert "market_context__USO__realized_vol_30" in features.columns
    assert "market_context__USO__log_return" in features.columns


def test_vix_gets_vix_level_and_vix_change():
    """Sprint 069: VIX-only vix_level (=close) + vix_change (=close - close.shift(1))."""
    n = 3
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n)]
    known_at = [t + timedelta(seconds=1) for t in grid_ts]
    df = pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__open": [100.0] * n,
            "target__SPY__high": [101.0] * n,
            "target__SPY__low": [99.0] * n,
            "target__SPY__close": [100.0] * n,
            "target__SPY__volume": [1000] * n,
            "market_context__VIX__known_at": known_at,
            "market_context__VIX__open": [15.2, 18.5, 16.0],
            "market_context__VIX__high": [15.2, 18.5, 16.0],
            "market_context__VIX__low": [15.2, 18.5, 16.0],
            "market_context__VIX__close": [15.2, 18.5, 16.0],
            "market_context__VIX__volume": [0, 0, 0],
        }
    )
    features, _ = compute_features(df, _fresh_emitter())
    assert "market_context__VIX__vix_level" in features.columns
    assert "market_context__VIX__vix_change" in features.columns
    level = features["market_context__VIX__vix_level"].to_list()
    change = features["market_context__VIX__vix_change"].to_list()
    assert level == [15.2, 18.5, 16.0]
    assert change[0] is None
    assert change[1] == pytest_approx(18.5 - 15.2)
    assert change[2] == pytest_approx(16.0 - 18.5)


def test_non_vix_market_context_has_no_vix_features():
    """QQQ (market_context but not VIX) does not get vix_level / vix_change."""
    df = _target_frame(
        n_rows=3,
        opens=[100.0] * 3,
        highs=[101.0] * 3,
        lows=[99.0] * 3,
        closes=[100.0] * 3,
        volumes=[1000] * 3,
    )
    df = df.with_columns(
        [
            pl.lit(400.0).alias("market_context__QQQ__close"),
            pl.lit(399.9).alias("market_context__QQQ__open"),
            pl.lit(400.5).alias("market_context__QQQ__high"),
            pl.lit(399.5).alias("market_context__QQQ__low"),
            pl.lit(1_000_000).alias("market_context__QQQ__volume"),
            pl.col("target__SPY__known_at").alias("market_context__QQQ__known_at"),
        ]
    )
    features, _ = compute_features(df, _fresh_emitter())
    assert "market_context__QQQ__vix_level" not in features.columns
    assert "market_context__QQQ__vix_change" not in features.columns


def test_failure_reason_insufficient_history_on_realized_vol_30():
    df = _target_frame(
        n_rows=3,
        opens=[100.0, 100.0, 100.0],
        highs=[101.0, 101.0, 101.0],
        lows=[99.0, 99.0, 99.0],
        closes=[100.0, 100.5, 100.2],
        volumes=[1000, 1000, 1000],
    )
    e = _fresh_emitter()
    compute_features(df, e)
    fails = [
        s
        for s in e.snapshot()
        if s.tag == "FEATURE_COMPUTATION_FAILED" and s.payload["feature_name"] == "realized_vol_30"
    ]
    assert fails
    assert all(s.payload["reason"] == "insufficient_history" for s in fails)


def pytest_approx(val: float, tol: float = 1e-9):
    """Local approx helper (pytest.approx isn't imported here to keep this test module thin)."""
    import pytest

    return pytest.approx(val, abs=tol)


# Sprint 070: macro features ---------------------------------------------


def test_macro_delta_and_days_since_release():
    """Sprint 070: delta = value-at-release-day, carried forward; days from age_since_known_at."""
    n = 10
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n)]
    known_at = [t + timedelta(seconds=1) for t in grid_ts]
    # macro__CPI close: 300 for 5 bars, then 305 for 5 bars → one release with delta +5.
    macro_close = [300.0] * 5 + [305.0] * 5
    # age_since_known_at: 0 on release; increments after.
    age = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
    df = pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__open": [100.0] * n,
            "target__SPY__high": [101.0] * n,
            "target__SPY__low": [99.0] * n,
            "target__SPY__close": [100.0] * n,
            "target__SPY__volume": [1000] * n,
            "macro__CPI__known_at": known_at,
            "macro__CPI__close": macro_close,
            "age_since_known_at__macro__CPI": age,
        }
    )
    features, _ = compute_features(df, _fresh_emitter())
    delta = features["macro__CPI__delta_since_last_release"].to_list()
    days = features["macro__CPI__days_since_release"].to_list()
    # Rows 0-4 pre-release: delta = 0. Row 5 release: +5. Rows 6-9 post-release: +5.
    assert delta[0] == 0.0
    assert delta[4] == 0.0
    assert delta[5] == pytest_approx(5.0)
    assert delta[9] == pytest_approx(5.0)
    # days = age / 26.
    assert abs(days[0] - 0.0) < 1e-6
    assert abs(days[4] - 4 / 26) < 1e-6
    assert abs(days[5] - 0.0) < 1e-6


def test_macro_features_do_not_leak_to_non_macro():
    """target + market_context channels should not carry macro features."""
    n = 5
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n)]
    known_at = [t + timedelta(seconds=1) for t in grid_ts]
    df = pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__open": [100.0] * n,
            "target__SPY__high": [101.0] * n,
            "target__SPY__low": [99.0] * n,
            "target__SPY__close": [100.0] * n,
            "target__SPY__volume": [1000] * n,
        }
    )
    features, _ = compute_features(df, _fresh_emitter())
    for name in ("delta_since_last_release", "days_since_release"):
        assert f"target__SPY__{name}" not in features.columns


# Sprint 071: options features -------------------------------------------


def test_options_z_score_20d_uses_rolling_window():
    """Sprint 071: z_score_20d is null through OPTIONS_ROLLING_WINDOW - 2 (rolling
    window at position i covers rows i-W+1..i, so full window fills at position
    W-1 with W rows in view)."""
    from price_space_llm.features.compute import OPTIONS_ROLLING_WINDOW

    n = OPTIONS_ROLLING_WINDOW + 5
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n)]
    known_at = [t + timedelta(seconds=1) for t in grid_ts]
    # Drifting PCR values so rolling std is nonzero.
    close = [1.0 + 0.001 * i for i in range(n)]
    df = pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__open": [100.0] * n,
            "target__SPY__high": [101.0] * n,
            "target__SPY__low": [99.0] * n,
            "target__SPY__close": [100.0] * n,
            "target__SPY__volume": [1000] * n,
            "options__PCR_SPY__known_at": known_at,
            "options__PCR_SPY__close": close,
        }
    )
    features, _ = compute_features(df, _fresh_emitter())
    z = features["options__PCR_SPY__z_score_20d"].to_list()
    assert z[OPTIONS_ROLLING_WINDOW - 2] is None
    assert z[OPTIONS_ROLLING_WINDOW - 1] is not None


def test_options_z_score_20d_constant_run_is_null():
    """Sprint 071: constant close series → std=0 → z-score null with divide_by_zero reason."""
    from price_space_llm.features.compute import OPTIONS_ROLLING_WINDOW

    n = OPTIONS_ROLLING_WINDOW + 3
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n)]
    known_at = [t + timedelta(seconds=1) for t in grid_ts]
    df = pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__open": [100.0] * n,
            "target__SPY__high": [101.0] * n,
            "target__SPY__low": [99.0] * n,
            "target__SPY__close": [100.0] * n,
            "target__SPY__volume": [1000] * n,
            "options__VOL_SPY__known_at": known_at,
            "options__VOL_SPY__close": [5_000_000.0] * n,
        }
    )
    e = _fresh_emitter(max_buffer=131072)
    features, _ = compute_features(df, e)
    z = features["options__VOL_SPY__z_score_20d"].to_list()
    for row_idx in range(OPTIONS_ROLLING_WINDOW - 1, n):
        assert z[row_idx] is None
    fails = [
        s
        for s in e.snapshot()
        if s.tag == "FEATURE_COMPUTATION_FAILED"
        and s.payload["feature_name"] == "z_score_20d"
        and s.payload["reason"] == "divide_by_zero"
    ]
    assert len(fails) == n - (OPTIONS_ROLLING_WINDOW - 1)
