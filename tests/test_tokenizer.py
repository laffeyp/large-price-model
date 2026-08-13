"""Tests for the return bucketizer + token emitter."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from price_space_llm.signals import StrictSignalEmitter, load_vocabulary
from price_space_llm.tokenizer.bucketize import (
    assign_buckets,
    fit_bucketizer,
    load_bucket_stats,
    run_tokenizer,
    write_bucket_stats,
)


def _fresh_emitter(max_buffer: int = 16384) -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


def _synthetic_features(n_rows: int, log_returns: list[float] | None = None) -> pl.DataFrame:
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n_rows)]
    if log_returns is None:
        # Deterministic spread: -0.02 to +0.02 evenly.
        log_returns = [-0.02 + 0.04 * (i / max(1, n_rows - 1)) for i in range(n_rows)]
    return pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__log_return": log_returns,
            "target__SPY__rolling_mean_20": [None] * n_rows,
            "target__SPY__rolling_std_20": [None] * n_rows,
            "target__SPY__rolling_z_score_20": [None] * n_rows,
        }
    )


# fit_bucketizer ------------------------------------------------------------


def test_fit_bucketizer_produces_n_minus_1_edges():
    features = _synthetic_features(n_rows=200)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    assert len(stats.edges) == 31
    assert list(stats.edges) == sorted(stats.edges)


def test_fit_bucketizer_rejects_too_few_rows():
    features = _synthetic_features(n_rows=10)
    e = _fresh_emitter()
    with pytest.raises(ValueError, match="need at least 32"):
        fit_bucketizer(
            features,
            target_symbol="SPY",
            n_buckets=32,
            training_range_start=date(2024, 6, 3),
            training_range_end=date(2024, 7, 3),
            emitter=e,
        )


def test_fit_bucketizer_emits_bucketizer_fitted():
    features = _synthetic_features(n_rows=200)
    e = _fresh_emitter()
    fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    fitted = next(s for s in e.snapshot() if s.tag == "BUCKETIZER_FITTED")
    assert fitted.payload["n_buckets"] == "32"


def test_fit_bucketizer_dedupes_ties_with_epsilon_nudge():
    """Zero-return runs create tied quantiles; edges must remain strictly increasing."""
    log_returns = [0.0] * 100 + [0.001 * i for i in range(1, 101)]
    features = _synthetic_features(n_rows=200, log_returns=log_returns)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    for a, b in zip(stats.edges[:-1], stats.edges[1:], strict=True):
        assert a < b, f"edges not strictly increasing: {a} >= {b}"


# write_bucket_stats + load_bucket_stats ------------------------------------


def test_write_and_load_bucket_stats_round_trip(tmp_path: Path):
    features = _synthetic_features(n_rows=200)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    path = tmp_path / "bucket_stats.json"
    sha = write_bucket_stats(stats, path, e, run_id="unit-test")
    assert len(sha) == 64
    # Sprint 036: versioned write lands at bucket_stats.unit-test.json; latest symlink adjacent.
    versioned = tmp_path / "bucket_stats.unit-test.json"
    loaded = load_bucket_stats(versioned)
    assert loaded == stats


def test_write_bucket_stats_emits_bucket_stats_written(tmp_path: Path):
    features = _synthetic_features(n_rows=200)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    path = tmp_path / "bucket_stats.json"
    write_bucket_stats(stats, path, e, run_id="unit-test")
    written = next(s for s in e.snapshot() if s.tag == "BUCKET_STATS_WRITTEN")
    # Sprint 036: emit records the versioned path, not the logical base name.
    assert written.payload["path"] == str(tmp_path / "bucket_stats.unit-test.json")
    assert written.payload["n_buckets"] == "32"


# assign_buckets ------------------------------------------------------------


def test_assign_buckets_preserves_nulls():
    ids = assign_buckets([1.0, None, 2.0], edges=(1.5,))
    assert ids == [0, None, 1]


def test_assign_buckets_maps_below_first_edge_to_zero():
    ids = assign_buckets([-100.0], edges=(0.0, 1.0, 2.0))
    assert ids == [0]


def test_assign_buckets_maps_above_last_edge_to_last_bucket():
    """3 edges → 4 buckets → max bucket_id is 3."""
    ids = assign_buckets([100.0], edges=(0.0, 1.0, 2.0))
    assert ids == [3]


# run_tokenizer (end-to-end) -----------------------------------------------


def test_run_tokenizer_writes_bucket_stats_and_tokens_parquet(tmp_path: Path):
    features = _synthetic_features(n_rows=200)
    features_path = tmp_path / "features.parquet"
    features.write_parquet(features_path)
    output_dir = tmp_path / "tokenized"
    stats_path = tmp_path / "bucket_stats.json"
    e = _fresh_emitter()
    result = run_tokenizer(
        features_path=features_path,
        output_dir=output_dir,
        bucket_stats_path=stats_path,
        target_symbol="SPY",
        n_buckets=32,
        d_model=64,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
        run_id="test-tok",
    )
    # Sprint 036: versioned artifact at bucket_stats.test-tok.json + latest symlink.
    assert (tmp_path / "bucket_stats.test-tok.json").exists()
    assert (tmp_path / "bucket_stats.latest.json").exists()
    tokens_path = output_dir / "test-tok.parquet"
    assert tokens_path.exists()
    tokens = pl.read_parquet(tokens_path)
    assert "target__SPY__bucket_id" in tokens.columns
    assert result.n_tokens_emitted > 0
    tags = [s.tag for s in e.snapshot()]
    assert "BUCKETIZER_FITTED" in tags
    assert "BUCKET_STATS_WRITTEN" in tags
    assert "BUCKET_ASSIGNED" in tags
    assert "MARKET_STATE_TOKEN_EMITTED" in tags


# Property-based ------------------------------------------------------------


@given(
    values=st.lists(
        st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
        min_size=100,
        max_size=500,
        unique=True,
    )
)
@settings(
    max_examples=100,
    deadline=timedelta(seconds=5),
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_bucket_assignment_is_quantile_consistent(values: list[float]) -> None:
    """After fitting on `values` at n_buckets=32, each bucket holds ~1/32 of the training rows."""
    n_buckets = 32
    n_rows = len(values)
    grid_ts = [datetime(2024, 6, 3, tzinfo=UTC) + timedelta(minutes=15 * i) for i in range(n_rows)]
    features = pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__log_return": values,
        }
    )
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=n_buckets,
        training_range_start=grid_ts[0].date(),
        training_range_end=grid_ts[-1].date(),
        emitter=e,
    )
    bucket_ids = [b for b in assign_buckets(values, stats.edges) if b is not None]
    # Every bucket_id in [0, n_buckets-1].
    assert all(0 <= b < n_buckets for b in bucket_ids)
    # No bucket holds more than 3x its expected share (rough balance check on quantile fit).
    expected = n_rows / n_buckets
    for b in range(n_buckets):
        count = bucket_ids.count(b)
        assert count <= max(3 * expected, 5), (
            f"bucket {b} holds {count} rows (expected ~{expected:.1f}); quantile fit skewed"
        )


@given(
    values=st.lists(
        st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=200,
        max_size=800,
        unique=True,
    )
)
@settings(
    max_examples=100,
    deadline=timedelta(seconds=5),
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_edges_are_strictly_increasing(values: list[float]) -> None:
    """Whatever the input distribution, fit_bucketizer must produce strictly-increasing edges."""
    n_rows = len(values)
    grid_ts = [datetime(2024, 6, 3, tzinfo=UTC) + timedelta(minutes=15 * i) for i in range(n_rows)]
    features = pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__log_return": values,
        }
    )
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=grid_ts[0].date(),
        training_range_end=grid_ts[-1].date(),
        emitter=e,
    )
    for a, b in zip(stats.edges[:-1], stats.edges[1:], strict=True):
        assert a < b
