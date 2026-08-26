"""Tests for the return bucketizer + token emitter."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
import torch
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from price_space_llm.signals import StrictSignalEmitter, load_vocabulary
from price_space_llm.tokenizer.bucketize import (
    BucketRow,
    assign_buckets,
    fit_bucketizer,
    load_bucket_stats,
    run_tokenizer,
    run_tokenizer_pt,
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


# run_tokenizer_pt (Sprint 052) --------------------------------------------


def _multichannel_features(n_rows: int, log_returns: list[float] | None = None) -> pl.DataFrame:
    """Two-channel synthetic features frame with real per-channel columns."""
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n_rows)]
    if log_returns is None:
        log_returns = [-0.02 + 0.04 * (i / max(1, n_rows - 1)) for i in range(n_rows)]
    known_at = [base + timedelta(minutes=15 * i, seconds=1) for i in range(n_rows)]
    return pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__log_return": log_returns,
            "target__SPY__rolling_mean_20": [0.0] * n_rows,
            "target__SPY__rolling_std_20": [0.01] * n_rows,
            "target__SPY__rolling_z_score_20": log_returns,
            "target__SPY__realized_vol_30": [0.005] * n_rows,
            "market_context__QQQ__known_at": known_at,
            "market_context__QQQ__log_return": [0.001 * i for i in range(n_rows)],
            "market_context__QQQ__rolling_mean_20": [0.0] * n_rows,
            "market_context__QQQ__rolling_std_20": [0.02] * n_rows,
            "market_context__QQQ__rolling_z_score_20": [0.0] * n_rows,
        }
    )


def _write_features(tmp_path: Path, df: pl.DataFrame) -> Path:
    p = tmp_path / "features.parquet"
    df.write_parquet(p)
    return p


def test_run_tokenizer_pt_writes_valid_artifact(tmp_path: Path):
    """Sprint 052: produces a .pt loadable via torch.load with every required key."""
    import torch

    features = _multichannel_features(n_rows=200)
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="test-run-pt",
    )
    assert output.exists()
    payload = torch.load(output, weights_only=False)
    for k in ("features", "targets", "vol", "timestamps", "mask", "channel_names", "meta"):
        assert k in payload
    assert "target__SPY" in payload["features"]
    assert "market_context__QQQ" in payload["features"]


def test_run_tokenizer_pt_per_channel_shapes_match(tmp_path: Path):
    """Sprint 052: per-channel tensor shape is [n_rows, F_c]."""
    features = _multichannel_features(n_rows=100)
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="test-shapes",
    )
    import torch

    payload = torch.load(output, weights_only=False)
    # target__SPY has 5 feature columns (log_return + 3 rolling + realized_vol_30).
    assert payload["features"]["target__SPY"].shape == (100, 5)
    # market_context__QQQ has 4 feature columns (log_return + 3 rolling).
    assert payload["features"]["market_context__QQQ"].shape == (100, 4)
    assert payload["targets"].shape == (100,)
    assert payload["vol"].shape == (100,)
    assert payload["timestamps"].shape == (100,)
    assert payload["mask"].shape == (100,)


def test_run_tokenizer_pt_targets_use_ignore_index_for_nulls(tmp_path: Path):
    """Sprint 052: targets[t] = -100 (PyTorch CE ignore_index) where log_return is null."""
    n_rows = 200
    log_returns: list[float | None] = [
        -0.02 + 0.04 * (i / max(1, n_rows - 1)) for i in range(n_rows)
    ]
    log_returns[5] = None
    log_returns[42] = None
    features = _multichannel_features(n_rows=n_rows, log_returns=log_returns)  # type: ignore[arg-type]
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="test-ignore-index",
    )
    import torch

    payload = torch.load(output, weights_only=False)
    targets = payload["targets"]
    assert int(targets[5]) == -100
    assert int(targets[42]) == -100
    assert 0 <= int(targets[0]) < 32


def test_run_tokenizer_pt_meta_carries_run_id_and_target(tmp_path: Path):
    """Sprint 052: meta dict carries run_id, target_symbol, and other hashes."""
    features = _multichannel_features(n_rows=100)
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="test-meta",
        config_hash="deadbeef",
        data_hash="cafebabe",
        git_sha_value="abc123",
    )
    import torch

    payload = torch.load(output, weights_only=False)
    meta = payload["meta"]
    assert meta["run_id"] == "test-meta"
    assert meta["target_symbol"] == "SPY"
    assert meta["config_hash"] == "deadbeef"
    assert meta["data_hash"] == "cafebabe"
    assert meta["git_sha"] == "abc123"


# Sprint 078: tokenized .pt through write_versioned -----------------------


def test_run_tokenizer_pt_writes_raw_targets(tmp_path: Path):
    """Sprint 088: raw_targets carries float log_return with NaN where the source was null."""
    n_rows = 200
    log_returns: list[float | None] = [
        -0.02 + 0.04 * (i / max(1, n_rows - 1)) for i in range(n_rows)
    ]
    log_returns[5] = None
    log_returns[42] = None
    features = _multichannel_features(n_rows=n_rows, log_returns=log_returns)  # type: ignore[arg-type]
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="v088-raw",
    )
    payload = torch.load(output, weights_only=False)
    raw = payload["raw_targets"]
    assert raw.dtype == torch.float32
    assert raw.shape == (n_rows,)
    # Null positions become NaN; valid positions match log_returns.
    assert torch.isnan(raw[5])
    assert torch.isnan(raw[42])
    assert float(raw[0]) == pytest.approx(-0.02, abs=1e-6)
    assert payload["meta"]["raw_targets_stamped"] == "v088"


def test_run_tokenizer_pt_stamps_normalized_false_without_normalizer(tmp_path: Path):
    """Sprint 084 (v0.7): un-normalized write stamps meta['normalized'] = False + emit."""
    features = _multichannel_features(n_rows=100)
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="v07-unnorm",
    )
    payload = torch.load(output, weights_only=False)
    assert payload["meta"]["normalized"] is False
    emit = next(s for s in e.snapshot() if s.tag == "TOKENIZED_ARTIFACT_WRITTEN")
    assert emit.payload["normalized"] is False


def test_run_tokenizer_pt_emits_tokenized_artifact_written(tmp_path: Path):
    """Sprint 080 (v0.6): run_tokenizer_pt emits TOKENIZED_ARTIFACT_WRITTEN once."""
    features = _multichannel_features(n_rows=100)
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="v080-emit",
    )
    emits = [s for s in e.snapshot() if s.tag == "TOKENIZED_ARTIFACT_WRITTEN"]
    assert len(emits) == 1
    payload = emits[0].payload
    assert payload["run_id"] == "v080-emit"
    assert payload["path"] == str(output)
    assert payload["mask_semantics"] == "target_valid_v075"
    assert payload["n_rows"] == 100
    assert payload["n_channels"] >= 2  # target + market_context + session__flags


def test_run_tokenizer_pt_writes_versioned_with_sidecar(tmp_path: Path):
    """Sprint 078: write lands at `tokens.{run_id}.pt` + `.sha256` sidecar
    + `tokens.latest.pt` symlink."""
    import hashlib

    features = _multichannel_features(n_rows=100)
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output_dir = tmp_path / "tokenized"
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=output_dir,
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="v078-test",
    )
    versioned = output_dir / "tokens.v078-test.pt"
    sidecar = output_dir / "tokens.v078-test.pt.sha256"
    latest = output_dir / "tokens.latest.pt"
    assert versioned.exists()
    assert sidecar.exists()
    assert latest.is_symlink()
    assert output == versioned
    # Sidecar content == sha256 of the .pt file bytes.
    sha_written = sidecar.read_text(encoding="utf-8").strip()
    sha_actual = hashlib.sha256(versioned.read_bytes()).hexdigest()
    assert sha_written == sha_actual


def test_run_tokenizer_pt_returns_versioned_path(tmp_path: Path):
    """Return value is the versioned path, not the bare `tokens.pt` base."""
    features = _multichannel_features(n_rows=100)
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="v078-return",
    )
    assert output.name == "tokens.v078-return.pt"


def test_run_tokenizer_pt_second_write_flips_symlink_and_preserves_prior(tmp_path: Path):
    """Two writes with distinct run_ids: both .pt files land on disk;
    `tokens.latest.pt` resolves to the second one. Hard rule 12 preserved."""
    features = _multichannel_features(n_rows=100)
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output_dir = tmp_path / "tokenized"
    first = run_tokenizer_pt(
        features_path=features_path,
        output_dir=output_dir,
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="first",
    )
    second = run_tokenizer_pt(
        features_path=features_path,
        output_dir=output_dir,
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="second",
    )
    # Both files present.
    assert first.exists()
    assert second.exists()
    assert first != second
    # Symlink resolves to the second write.
    latest = output_dir / "tokens.latest.pt"
    assert latest.is_symlink()
    assert latest.resolve() == second.resolve()


# Sprint 075: mask redefinition (target-valid semantics) -------------------


def test_mask_target_valid_on_synthetic_frame(tmp_path: Path):
    """Mask reads True iff target features non-null AND target label present.

    Truth table across 4 rows:
      row 0: target features valid, target label valid  → True
      row 1: target features null,  target label valid  → False (feature null)
      row 2: target features valid, target label null   → False (target -100)
      row 3: target features null,  target label null   → False
    """
    n_rows = 4
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n_rows)]
    known_at = [base + timedelta(minutes=15 * i, seconds=1) for i in range(n_rows)]
    # log_return in-range for rows 0 and 1; null for rows 2 and 3 (targets->-100).
    log_returns: list[float | None] = [0.001, 0.002, None, None]
    # Feature rolling_mean_20 null on row 1 and row 3 to break target-feature validity.
    rolling_mean: list[float | None] = [0.0, None, 0.0, None]
    features = pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__log_return": log_returns,
            "target__SPY__rolling_mean_20": rolling_mean,
            "target__SPY__rolling_std_20": [0.01] * n_rows,
            "target__SPY__rolling_z_score_20": [0.0] * n_rows,
            "target__SPY__realized_vol_30": [0.005] * n_rows,
        }
    )
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        pl.DataFrame(
            {
                "grid_ts": [datetime(2024, 6, 3, tzinfo=UTC) + timedelta(minutes=15 * i)
                            for i in range(200)],
                "target__SPY__log_return": [0.001 * (i - 100) for i in range(200)],
            }
        ),
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="test-mask-truth-table",
    )
    payload = torch.load(output, weights_only=False)
    mask = payload["mask"]
    assert mask.dtype == torch.bool
    assert mask.tolist() == [True, False, False, False]


def test_mask_ignores_non_target_null_columns(tmp_path: Path):
    """Non-target null columns must NOT depress mask.

    A 3-row frame where target features + label are all valid but
    `market_context__QQQ__log_return` is all-null. Mask should be all-True.
    Pre-Sprint-075 semantic would collapse to all-False here.
    """
    n_rows = 3
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n_rows)]
    known_at = [base + timedelta(minutes=15 * i, seconds=1) for i in range(n_rows)]
    features = pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__known_at": known_at,
            "target__SPY__log_return": [0.001, 0.002, 0.003],
            "target__SPY__rolling_mean_20": [0.0] * n_rows,
            "target__SPY__rolling_std_20": [0.01] * n_rows,
            "target__SPY__rolling_z_score_20": [0.0] * n_rows,
            "target__SPY__realized_vol_30": [0.005] * n_rows,
            "market_context__QQQ__known_at": known_at,
            "market_context__QQQ__log_return": [None, None, None],
            "market_context__QQQ__rolling_mean_20": [0.0] * n_rows,
            "market_context__QQQ__rolling_std_20": [0.02] * n_rows,
            "market_context__QQQ__rolling_z_score_20": [0.0] * n_rows,
        }
    )
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        pl.DataFrame(
            {
                "grid_ts": [datetime(2024, 6, 3, tzinfo=UTC) + timedelta(minutes=15 * i)
                            for i in range(200)],
                "target__SPY__log_return": [0.001 * (i - 100) for i in range(200)],
            }
        ),
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 7, 3),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="test-mask-non-target-null",
    )
    payload = torch.load(output, weights_only=False)
    mask = payload["mask"]
    assert mask.tolist() == [True, True, True]


REPO_ROOT_FOR_MASK = Path(__file__).resolve().parents[1]


def test_mask_present_on_regenerated_real_corpus():
    """Regenerated 2015-2022 training .pt reports mask.sum() > 0 and the new marker.

    Skips if the training .pt artifact isn't on disk. Sprint 075's success
    criterion — pre-fix `mask.sum() == 0` on this exact file.
    """
    # Sprint 078: writes now land at `tokens.{run_id}.pt` + `tokens.latest.pt`
    # symlink. Prefer the symlink; fall back to the pre-Sprint-078 bare-path
    # file if the symlink isn't present yet.
    versioned_symlink = REPO_ROOT_FOR_MASK / "data" / "tokenized" / "tokens.latest.pt"
    bare_legacy = REPO_ROOT_FOR_MASK / "data" / "tokenized" / (
        "tokenize-features-align-2015-01-2022-12-"
        "0000000000000000-0000000000000000-0000000000000000.pt"
    )
    if versioned_symlink.exists():
        training_pt = versioned_symlink
    elif bare_legacy.exists():
        training_pt = bare_legacy
    else:
        pytest.skip(f".pt not on disk (neither {versioned_symlink} nor {bare_legacy})")
    payload = torch.load(training_pt, weights_only=False)
    marker = payload["meta"].get("mask_semantics")
    if marker != "target_valid_v075":
        pytest.skip(
            "training .pt was written pre-Sprint-075; regenerate via scripts/bucketize.py "
            "before this test asserts."
        )
    assert int(payload["mask"].sum()) > 0


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


# Sprint 056: extended bucket_stats.json schema ---------------------------


def test_fit_bucketizer_populates_per_bucket_shape():
    """Sprint 056: per_bucket has exactly n_buckets entries."""
    features = _synthetic_features(n_rows=500)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 12, 31),
        emitter=e,
    )
    assert len(stats.per_bucket) == 32
    assert all(isinstance(r, BucketRow) for r in stats.per_bucket)


def test_per_bucket_open_tails_and_interior_bounds_match_edges():
    features = _synthetic_features(n_rows=500)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 12, 31),
        emitter=e,
    )
    assert stats.per_bucket[0].lower is None
    assert stats.per_bucket[-1].upper is None
    for i in range(1, 31):
        assert stats.per_bucket[i].lower == stats.edges[i - 1]
        assert stats.per_bucket[i].upper == stats.edges[i]


def test_per_bucket_frequency_sums_to_one():
    features = _synthetic_features(n_rows=500)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 12, 31),
        emitter=e,
    )
    total_freq = sum(r.train_frequency for r in stats.per_bucket)
    assert abs(total_freq - 1.0) < 1e-9


def test_per_bucket_train_mean_monotone_across_buckets():
    features = _synthetic_features(n_rows=1000)  # uniform spread
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 12, 31),
        emitter=e,
    )
    from itertools import pairwise

    means = [r.train_mean for r in stats.per_bucket]
    for a, b in pairwise(means):
        assert a <= b


def test_write_bucket_stats_json_is_strict(tmp_path: Path):
    """Sprint 056: JSON output rejects Infinity; open-tail bounds are `null`."""
    features = _synthetic_features(n_rows=500)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 12, 31),
        emitter=e,
    )
    base_path = tmp_path / "bucket_stats.json"
    write_bucket_stats(stats, base_path, e, run_id="strict-json")
    written = tmp_path / "bucket_stats.strict-json.json"
    text = written.read_text(encoding="utf-8")
    assert "Infinity" not in text
    import json as _json

    doc = _json.loads(text)
    assert len(doc["per_bucket"]) == 32
    assert doc["per_bucket"][0]["lower"] is None
    assert doc["per_bucket"][-1]["upper"] is None


def test_write_load_roundtrip_preserves_per_bucket(tmp_path: Path):
    features = _synthetic_features(n_rows=500)
    e = _fresh_emitter()
    original = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 12, 31),
        emitter=e,
    )
    base_path = tmp_path / "bucket_stats.json"
    write_bucket_stats(original, base_path, e, run_id="roundtrip")
    written = tmp_path / "bucket_stats.roundtrip.json"
    loaded = load_bucket_stats(written)
    assert len(loaded.per_bucket) == 32
    import math

    for orig_row, load_row in zip(original.per_bucket, loaded.per_bucket, strict=True):
        assert orig_row.lower == load_row.lower
        assert orig_row.upper == load_row.upper
        assert abs(orig_row.train_frequency - load_row.train_frequency) < 1e-9
        if math.isnan(orig_row.train_mean):
            assert math.isnan(load_row.train_mean)
        else:
            assert abs(orig_row.train_mean - load_row.train_mean) < 1e-9


# Sprint 062: session flags ------------------------------------------------


def test_session_features_shape_and_columns():
    """Sprint 062: shape [T, 4]; is_overnight_gap [T]."""
    from price_space_llm.tokenizer.session import compute_session_features

    # 4 bars, 15 min apart.
    ts = torch.tensor(
        [0, 15 * 60, 30 * 60, 45 * 60],
        dtype=torch.int64,
    )
    feats, gap = compute_session_features(ts)
    assert feats.shape == (4, 4)
    assert gap.shape == (4,)
    # sin/cos should be in [-1, 1].
    assert (feats >= -1).all()
    assert (feats <= 1).all()


def test_session_features_detects_overnight_gap():
    """Sprint 062: gap > 15 min → is_overnight_gap=1 on that bar."""
    from price_space_llm.tokenizer.session import compute_session_features

    # Two bars 15 min apart, then a big gap (overnight = ~17 hours), then two more.
    ts = torch.tensor(
        [
            0,
            15 * 60,
            15 * 60 + 17 * 3600,
            15 * 60 + 17 * 3600 + 15 * 60,
        ],
        dtype=torch.int64,
    )
    _, gap = compute_session_features(ts)
    # Bar 0 = session start; bar 1 same day; bar 2 next day; bar 3 same day.
    assert list(gap.tolist()) == [1, 0, 1, 0]


def test_session_features_cyclic_encoding_of_time():
    """Sprint 062: minute-of-day sin+cos at midnight = (0, 1); at noon = (0, -1)."""
    from price_space_llm.tokenizer.session import compute_session_features

    midnight = 0
    noon = 12 * 3600
    ts = torch.tensor([midnight, noon], dtype=torch.int64)
    feats, _ = compute_session_features(ts)
    assert abs(float(feats[0, 0]) - 0.0) < 1e-6  # sin(0) = 0
    assert abs(float(feats[0, 1]) - 1.0) < 1e-6  # cos(0) = 1
    assert abs(float(feats[1, 0]) - 0.0) < 1e-5  # sin(π) = 0
    assert abs(float(feats[1, 1]) - (-1.0)) < 1e-6  # cos(π) = -1


def test_session_features_empty_timestamps():
    from price_space_llm.tokenizer.session import compute_session_features

    ts = torch.zeros(0, dtype=torch.int64)
    feats, gap = compute_session_features(ts)
    assert feats.shape == (0, 4)
    assert gap.shape == (0,)


def test_run_tokenizer_pt_adds_session_channel_and_gap_tensor(tmp_path: Path):
    """Sprint 062: run_tokenizer_pt writes session__flags channel + populated
    is_overnight_gap (not None)."""
    import torch

    features = _multichannel_features(n_rows=200)
    features_path = _write_features(tmp_path, features)
    e = _fresh_emitter()
    stats = fit_bucketizer(
        features,
        target_symbol="SPY",
        n_buckets=32,
        training_range_start=date(2024, 6, 3),
        training_range_end=date(2024, 12, 31),
        emitter=e,
    )
    output = run_tokenizer_pt(
        features_path=features_path,
        output_dir=tmp_path / "tokenized",
        stats=stats,
        target_symbol="SPY",
        emitter=e,
        run_id="session-smoke",
    )
    payload = torch.load(output, weights_only=False)
    assert "session__flags" in payload["features"]
    assert payload["features"]["session__flags"].shape == (200, 4)
    assert payload["is_overnight_gap"] is not None
    assert payload["is_overnight_gap"].shape == (200,)
