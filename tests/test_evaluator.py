"""Tests for the evaluator: regime fit, deterministic windows, end-to-end emit sequence."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from price_space_llm.evaluation.evaluate import (
    _deterministic_windows,
    _partition_positions_by_regime,
    run_evaluation,
)
from price_space_llm.evaluation.regimes import (
    assign_regime,
    fit_regime_thresholds,
)
from price_space_llm.model.trainer import TrainerConfig, run_training
from price_space_llm.model.transformer import TransformerConfig
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary


def _fresh_emitter(max_buffer: int = 16384) -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


# Regime label fit --------------------------------------------------------


def test_regime_thresholds_are_terciles_of_training_volatility():
    vols = [0.001 * i for i in range(1, 100)]  # 99 sorted values
    th = fit_regime_thresholds(list(vols))
    assert th.low_threshold < th.mid_threshold
    # 33rd percentile of 99 sorted values ≈ index 32 -> 0.033.
    assert th.low_threshold == pytest.approx(0.033, abs=0.005)
    assert th.mid_threshold == pytest.approx(0.066, abs=0.005)


def test_fit_regime_thresholds_ignores_nulls():
    vols: list[float | None] = [0.01, None, 0.02, 0.03, None, 0.04, 0.05]
    th = fit_regime_thresholds(vols)
    assert th.low_threshold < th.mid_threshold


def test_fit_regime_thresholds_rejects_too_few_values():
    with pytest.raises(ValueError, match="at least 3"):
        fit_regime_thresholds([0.01, None])


def test_assign_regime_maps_boundary_values():
    th = fit_regime_thresholds([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])
    # 33rd pct of [1..9] = 3.64; 66th = 6.36. Anything < 3.64 -> low.
    assert assign_regime(1.0, th) == "low"
    assert assign_regime(5.0, th) == "mid"
    assert assign_regime(9.0, th) == "high"
    assert assign_regime(None, th) == "mid"


# Deterministic windows ---------------------------------------------------


def test_deterministic_windows_produces_every_valid_start():
    tokens = list(range(10))
    inputs, targets = _deterministic_windows(tokens, context_len=4)
    # n = len - context_len - 1 = 5; loop is range(n+1) = range(6) -> 6 windows.
    assert inputs.shape == (6, 4)
    assert targets.shape == (6, 4)
    # First window: inputs = tokens[0:4], targets = tokens[1:5]
    assert inputs[0].tolist() == [0, 1, 2, 3]
    assert targets[0].tolist() == [1, 2, 3, 4]
    # Last window shifts by 5.
    assert inputs[-1].tolist() == [5, 6, 7, 8]
    assert targets[-1].tolist() == [6, 7, 8, 9]


def test_deterministic_windows_returns_empty_when_too_few_tokens():
    inputs, _ = _deterministic_windows([1, 2, 3], context_len=10)
    assert inputs.shape[0] == 0


# End-to-end evaluator ----------------------------------------------------


def _synthetic_features(n_rows: int) -> pl.DataFrame:
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n_rows)]
    log_returns = [-0.02 + 0.04 * (i / max(1, n_rows - 1)) for i in range(n_rows)]
    rolling_std = [0.001 + 0.0001 * (i % 30) for i in range(n_rows)]
    return pl.DataFrame(
        {
            "grid_ts": grid_ts,
            "target__SPY__log_return": log_returns,
            "target__SPY__rolling_std_20": rolling_std,
        }
    )


def _write_tokens(tmp_path: Path, n: int) -> Path:
    base = datetime(2024, 6, 3, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n)]
    bucket_ids = [i % 32 for i in range(n)]
    df = pl.DataFrame({"grid_ts": grid_ts, "target__SPY__bucket_id": bucket_ids})
    path = tmp_path / "tokens.parquet"
    df.write_parquet(path)
    return path


def _write_features(tmp_path: Path, n: int) -> Path:
    df = _synthetic_features(n)
    path = tmp_path / "features.parquet"
    df.write_parquet(path)
    return path


def _write_toy_checkpoint(tmp_path: Path, vocab_size: int = 32, context_len: int = 64) -> Path:
    """Train a tiny model for 2 steps to get a real checkpoint file on disk."""
    e = _fresh_emitter()
    tokens = [i % vocab_size for i in range(800)]
    ckpt_dir = tmp_path / "ckpt"
    run_training(
        tokens=tokens,
        trainer_cfg=TrainerConfig(n_steps=2, batch_size=4, lr=1e-3, eval_every=2, seed=0),
        model_cfg=TransformerConfig(
            vocab_size=vocab_size,
            context_len=context_len,
            d_model=16,
            n_layers=2,
            n_heads=2,
            dropout=0.0,
        ),
        emitter=e,
        run_id="toy",
        checkpoint_dir=ckpt_dir,
    )
    ckpts = list(ckpt_dir.glob("*.pt"))
    assert ckpts
    return ckpts[0]


def test_run_evaluation_emits_full_tag_sequence(tmp_path: Path):
    features_path = _write_features(tmp_path, n=800)
    tokens_path = _write_tokens(tmp_path, n=800)
    checkpoint = _write_toy_checkpoint(tmp_path)
    e = _fresh_emitter()
    result = run_evaluation(
        checkpoint_path=checkpoint,
        features_path=features_path,
        tokens_path=tokens_path,
        target_symbol="SPY",
        train_frac=0.8,
        output_dir=tmp_path / "artifacts",
        emitter=e,
        run_id="eval-test",
        training_range_start="2024-06-03",
        training_range_end="2024-06-28",
    )
    tags = [s.tag for s in e.snapshot()]
    assert tags.count("REGIME_LABELS_FROZEN") == 1
    # 7 metrics x 2 splits x 3 regimes = 42.
    assert tags.count("METRIC_COMPUTED") == 42
    assert tags.count("BUCKET_FREQUENCY_DRIFT_MEASURED") == 1
    # METRIC_SNAPSHOT_WRITTEN fires once per split (2).
    assert tags.count("METRIC_SNAPSHOT_WRITTEN") == 2
    assert result.n_metric_emits == 42
    assert (tmp_path / "artifacts" / "metrics.json").exists()


def test_partition_positions_by_regime_covers_all_valid_starts():
    """Every valid start position (0..n_valid) must end up in exactly one regime bucket."""
    context_len = 4
    # 20 volatilities; window target is at position s+context_len; n_valid = 20-4-1 = 15 starts.
    vols: list[float | None] = [float(i) for i in range(20)]
    from price_space_llm.evaluation.regimes import RegimeThresholds

    th = RegimeThresholds(low_threshold=7.0, mid_threshold=13.0)
    parts = _partition_positions_by_regime(vols, context_len, th)
    total = sum(len(positions) for positions in parts.values())
    assert total == 16  # loop is range(n+1) where n = 15 -> 16 iterations
    # No overlap.
    seen: set[int] = set()
    for positions in parts.values():
        for p in positions:
            assert p not in seen
            seen.add(p)


def test_metric_snapshot_json_carries_deterministic_hash(tmp_path: Path):
    features_path = _write_features(tmp_path, n=800)
    tokens_path = _write_tokens(tmp_path, n=800)
    checkpoint = _write_toy_checkpoint(tmp_path)

    def _run() -> str:
        e = _fresh_emitter()
        run_evaluation(
            checkpoint_path=checkpoint,
            features_path=features_path,
            tokens_path=tokens_path,
            target_symbol="SPY",
            train_frac=0.8,
            output_dir=tmp_path / "artifacts",
            emitter=e,
            run_id="det",
            training_range_start="2024-06-03",
            training_range_end="2024-06-28",
        )
        snap = next(s for s in e.snapshot() if s.tag == "METRIC_SNAPSHOT_WRITTEN")
        return str(snap.payload["sha256"])

    assert _run() == _run()


# Sprint 067: regime evaluator VIX switch ---------------------------------


def test_load_features_prefers_vix_when_column_present(tmp_path: Path):
    """Sprint 067: _load_features_and_tokens prefers market_context__VIX__close."""
    import polars as pl

    from price_space_llm.evaluation.evaluate import _load_features_and_tokens

    features = pl.DataFrame(
        {
            "grid_ts": [1, 2, 3],
            "target__SPY__rolling_std_20": [0.5, 0.6, 0.7],
            "market_context__VIX__close": [14.0, 15.0, 22.0],
        }
    )
    tokens = pl.DataFrame(
        {
            "grid_ts": [1, 2, 3],
            "target__SPY__bucket_id": [0, 1, 2],
        }
    )
    fpath = tmp_path / "features.parquet"
    tpath = tmp_path / "tokens.parquet"
    features.write_parquet(fpath)
    tokens.write_parquet(tpath)
    _, _, vols = _load_features_and_tokens(fpath, tpath, "SPY")
    # VIX values, not rolling_std_20.
    assert vols == [14.0, 15.0, 22.0]


def test_load_features_falls_back_to_rolling_std_when_no_vix(tmp_path: Path):
    """Sprint 067 back-compat: pre-Sprint-038 features parquets still evaluate."""
    import polars as pl

    from price_space_llm.evaluation.evaluate import _load_features_and_tokens

    features = pl.DataFrame(
        {
            "grid_ts": [1, 2, 3],
            "target__SPY__rolling_std_20": [0.5, 0.6, 0.7],
        }
    )
    tokens = pl.DataFrame(
        {
            "grid_ts": [1, 2, 3],
            "target__SPY__bucket_id": [0, 1, 2],
        }
    )
    fpath = tmp_path / "features.parquet"
    tpath = tmp_path / "tokens.parquet"
    features.write_parquet(fpath)
    tokens.write_parquet(tpath)
    _, _, vols = _load_features_and_tokens(fpath, tpath, "SPY")
    assert vols == [0.5, 0.6, 0.7]


def test_load_features_raises_when_no_vol_column(tmp_path: Path):
    import polars as pl
    import pytest

    from price_space_llm.evaluation.evaluate import _load_features_and_tokens

    features = pl.DataFrame({"grid_ts": [1, 2, 3]})
    tokens = pl.DataFrame({"grid_ts": [1, 2, 3], "target__SPY__bucket_id": [0, 1, 2]})
    fpath = tmp_path / "features.parquet"
    tpath = tmp_path / "tokens.parquet"
    features.write_parquet(fpath)
    tokens.write_parquet(tpath)
    with pytest.raises(ValueError, match="lacks both"):
        _load_features_and_tokens(fpath, tpath, "SPY")


# Sprint 068: MarketStateTransformer evaluator path ------------------------


def test_checkpoint_is_market_state_detects_channel_dims(tmp_path: Path):
    """Sprint 068: presence of channel_dims in the .pt payload's config marks the kind."""
    import torch

    from price_space_llm.evaluation.evaluate import _checkpoint_is_market_state

    ms_ckpt = tmp_path / "ms.pt"
    bucket_ckpt = tmp_path / "bucket.pt"
    torch.save(
        {"model_state_dict": {}, "config": {"channel_dims": {"target__SPY": 4}}}, ms_ckpt
    )
    torch.save(
        {"model_state_dict": {}, "config": {"vocab_size": 32, "context_len": 64}}, bucket_ckpt
    )
    assert _checkpoint_is_market_state(ms_ckpt)
    assert not _checkpoint_is_market_state(bucket_ckpt)


def test_run_evaluation_feats_end_to_end(tmp_path: Path):
    """Sprint 068: run_evaluation_feats loads a MarketStateTransformer + .pt artifact,
    computes per-regime metrics, writes metrics.json with checkpoint_kind=market_state."""
    import json

    import polars as pl
    import torch

    from price_space_llm.evaluation.evaluate import run_evaluation_feats
    from price_space_llm.model import MarketStateTransformerConfig
    from price_space_llm.model.transformer import MarketStateTransformer

    n_rows = 400
    context_len = 64
    channel_dims = {"target__SPY": 4}

    # Build a checkpoint.
    cfg = MarketStateTransformerConfig(
        vocab_size=32,
        context_len=context_len,
        channel_dims=channel_dims,
    )
    model = MarketStateTransformer(cfg)
    ckpt_path = tmp_path / "market_state.pt"
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "step": 0,
            "val_nll": 3.5,
            "config": {
                "vocab_size": 32,
                "context_len": context_len,
                "d_model": 64,
                "n_layers": 4,
                "n_heads": 4,
                "channel_dims": channel_dims,
            },
        },
        ckpt_path,
    )

    # Build a Sprint 052 .pt artifact.
    torch.manual_seed(0)
    artifact_payload = {
        "features": {"target__SPY": torch.randn(n_rows, 4)},
        "targets": torch.randint(0, 32, (n_rows,), dtype=torch.int64),
        "vol": torch.zeros(n_rows, dtype=torch.float32),
        "timestamps": torch.arange(n_rows, dtype=torch.int64),
        "is_overnight_gap": None,
        "mask": torch.ones(n_rows, dtype=torch.bool),
        "channel_names": ("target__SPY",),
        "meta": {"run_id": "test"},
    }
    tokens_pt = tmp_path / "tokens.pt"
    torch.save(artifact_payload, tokens_pt)

    # Build a features parquet with VIX + rolling_std for regime partitioning.
    features_df = pl.DataFrame(
        {
            "grid_ts": list(range(n_rows)),
            "market_context__VIX__close": [14.0 + 0.05 * i for i in range(n_rows)],
        }
    )
    features_path = tmp_path / "features.parquet"
    features_df.write_parquet(features_path)

    e = _fresh_emitter()
    result = run_evaluation_feats(
        checkpoint_path=ckpt_path,
        features_path=features_path,
        tokens_pt_path=tokens_pt,
        target_symbol="SPY",
        train_frac=0.8,
        output_dir=tmp_path / "artifacts",
        emitter=e,
        run_id="feats-eval",
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
    )
    assert result.n_metric_emits > 0
    metrics = json.loads(Path(result.metrics_path).read_text())
    assert metrics["checkpoint_kind"] == "market_state"
    tags = [s.tag for s in e.snapshot()]
    assert "REGIME_LABELS_FROZEN" in tags
    assert "METRIC_COMPUTED" in tags
    assert "BUCKET_FREQUENCY_DRIFT_MEASURED" in tags
    assert "METRIC_SNAPSHOT_WRITTEN" in tags
