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
    """One-channel aligned DataFrame with monotonic timestamps and given closes."""
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n_rows)]
    known_at = [t + timedelta(seconds=1) for t in grid_ts]
    if closes is None:
        closes = [540.0 + i * 0.1 for i in range(n_rows)]
    return pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__close": closes,
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
    assert result["n_failures"] > 0  # rolling windows produce failures on early rows
    assert result["n_features_emitted"] > 0


def test_two_channels_produce_eight_feature_columns():
    """Two channels x four features = eight feature columns in the output."""
    aligned = _synthetic_aligned(n_rows=5)
    aligned = aligned.with_columns(
        [
            pl.lit(80.0).alias("market_context__USO__close"),
            pl.col("target__SPY__known_at").alias("market_context__USO__known_at"),
        ]
    )
    e = _fresh_emitter()
    features, _ = compute_features(aligned, e)
    feature_cols = [c for c in features.columns if c != "grid_ts"]
    assert len(feature_cols) == 8


def pytest_approx(val: float, tol: float = 1e-9):
    """Local approx helper (pytest.approx isn't imported here to keep this test module thin)."""
    import pytest

    return pytest.approx(val, abs=tol)
