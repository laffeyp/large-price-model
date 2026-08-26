"""Sprint 098: capacity sweep — CAPACITY_SWEEP_COMPLETED emit + capacity_usd math."""

from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest
import torch

from price_space_llm.model import (
    MarketStateTransformerConfig,
    TokenizedArtifact,
)
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary
from price_space_llm.simulation import (
    CapacityPoint,
    PolicyConfig,
    SimMetrics,
    SimResult,
    run_capacity_sweep,
)
from price_space_llm.tokenizer.bucketize import BucketRow, BucketStats


def _fresh_emitter(max_buffer: int = 65536) -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


def _tiny_artifact(n_rows: int = 64, v: int = 32) -> TokenizedArtifact:
    torch.manual_seed(0)
    return TokenizedArtifact(
        features={"target__SPY": torch.randn(n_rows, 4) * 0.1},
        targets=torch.randint(0, v, (n_rows,), dtype=torch.int64),
        raw_targets=torch.linspace(-0.01, 0.01, n_rows, dtype=torch.float32),
        vol=torch.full((n_rows,), 0.01, dtype=torch.float32),
        timestamps=torch.arange(n_rows, dtype=torch.int64) * 900 + 1_600_000_000,
        is_overnight_gap=None,
        mask=torch.ones(n_rows, dtype=torch.bool),
        channel_names=("target__SPY",),
        meta={"normalized": True, "mask_semantics": "target_valid_v075"},
    )


def _tiny_bucket_stats(v: int = 32) -> BucketStats:
    means = [(-1.0 + 2.0 * i / (v - 1)) for i in range(v)]
    per_bucket = tuple(
        BucketRow(
            lower=None if i == 0 else (i - 1) / v,
            upper=None if i == v - 1 else i / v,
            train_mean=means[i],
            train_median=means[i],
            train_frequency=1.0 / v,
        )
        for i in range(v)
    )
    return BucketStats(
        n_buckets=v,  # type: ignore[arg-type]
        target_symbol="SPY",
        training_range_start="2020-01-01",
        training_range_end="2020-12-31",
        train_partition_row_count=1000,
        edges=tuple(sorted(means[1:])),
        per_bucket=per_bucket,
    )


class _AlwaysLongModel(torch.nn.Module):
    def __init__(self, cfg: MarketStateTransformerConfig) -> None:
        super().__init__()
        self.config = cfg
        self.dummy = torch.nn.Parameter(torch.zeros(1))

    def forward(self, feats: dict[str, torch.Tensor]) -> torch.Tensor:
        v = self.config.vocab_size
        logits = torch.full((1, 1, v), -100.0)
        logits[0, 0, v - 1] = 100.0
        return logits

    def eval(self) -> _AlwaysLongModel:  # type: ignore[override]
        return self


def _base_policy(size_usd: float = 1_000_000.0) -> PolicyConfig:
    return PolicyConfig(
        threshold=1e-6,
        hysteresis=0.0,
        lambda_risk=0.0,
        spread_cost_frac=0.0,
        slippage_frac=0.0,
        position_size_usd=size_usd,
    )


def _base_config(v: int = 32, context_len: int = 4) -> MarketStateTransformerConfig:
    return MarketStateTransformerConfig(
        vocab_size=v,
        context_len=context_len,
        channel_dims={"target__SPY": 4},
        d_model=16,
        n_heads=2,
    )


# --- one-point-per-size --------------------------------------------------


def test_capacity_sweep_result_has_one_point_per_size():
    artifact = _tiny_artifact(n_rows=64, v=32)
    cfg = _base_config()
    model = _AlwaysLongModel(cfg)
    stats = _tiny_bucket_stats(v=32)
    e = _fresh_emitter()
    result = run_capacity_sweep(
        artifact, model, stats, _base_policy(),
        sizes_usd=(1_000_000.0, 3_000_000.0, 10_000_000.0),
        target_symbol="SPY",
        emitter=e,
        run_id="test-sweep-3pts",        checkpoint_step=0,
        checkpoint_run_id="test-ckpt",
        cost_calibration_run_id="test-cal",

    )
    assert len(result.points) == 3
    assert [p.size_usd for p in result.points] == [1_000_000.0, 3_000_000.0, 10_000_000.0]


# --- CAPACITY_SWEEP_COMPLETED emit ---------------------------------------


def test_capacity_sweep_emits_completed_tag_once():
    artifact = _tiny_artifact(n_rows=64, v=32)
    cfg = _base_config()
    model = _AlwaysLongModel(cfg)
    stats = _tiny_bucket_stats(v=32)
    e = _fresh_emitter()
    run_capacity_sweep(
        artifact, model, stats, _base_policy(),
        sizes_usd=(1_000_000.0, 3_000_000.0),
        target_symbol="SPY",
        emitter=e,
        run_id="test-sweep-emit",        checkpoint_step=0,
        checkpoint_run_id="test-ckpt",
        cost_calibration_run_id="test-cal",

    )
    completed = [s for s in e.snapshot() if s.tag == "CAPACITY_SWEEP_COMPLETED"]
    assert len(completed) == 1
    p = completed[0].payload
    assert p["run_id"] == "test-sweep-emit"
    assert len(p["points"]) == 2
    assert set(p["points"][0].keys()) == {"size_usd", "sharpe", "sharpe_se"}


def test_capacity_sweep_emits_one_sim_run_pair_per_size():
    artifact = _tiny_artifact(n_rows=64, v=32)
    cfg = _base_config()
    model = _AlwaysLongModel(cfg)
    stats = _tiny_bucket_stats(v=32)
    e = _fresh_emitter()
    run_capacity_sweep(
        artifact, model, stats, _base_policy(),
        sizes_usd=(1_000_000.0, 3_000_000.0, 10_000_000.0),
        target_symbol="SPY",
        emitter=e,
        run_id="test-sweep-pairs",        checkpoint_step=0,
        checkpoint_run_id="test-ckpt",
        cost_calibration_run_id="test-cal",

    )
    tags = [s.tag for s in e.snapshot()]
    assert tags.count("SIM_RUN_STARTED") == 3
    assert tags.count("SIM_RUN_COMPLETED") == 3


# --- capacity_usd math ---------------------------------------------------


def _stub_run_simulation_with_trades(
    artifact, model, bucket_stats, policy, **kwargs,
) -> SimResult:
    """Test stub: returns a SimResult whose metrics.sharpe_point depends on policy size."""
    size = policy.position_size_usd
    # Rule: sharpe > 0 for size <= 3M, sharpe <= 0 for size > 3M.
    sharpe = 0.5 if size <= 3_000_000.0 else -0.2
    metrics = SimMetrics(
        sharpe_point=sharpe,
        sharpe_se=0.05,
        block_bootstrap_positive_fraction=0.8 if sharpe > 0 else 0.2,
        max_drawdown=0.1,
        time_to_recovery_bars=10,
        hit_rate=0.55,
        n_bars=100,
        n_trades=5,
    )
    return SimResult(
        n_bars_processed=100,
        n_bars_skipped_undefined_vol=0,
        n_trades=5,
        trades=(),
        pnl_total=1_000.0,
        metrics=metrics,
        notes="stub",
    )


def test_capacity_sweep_capacity_usd_is_largest_positive_sharpe_size():
    """Stub scenario: sharpe positive at 1M and 3M, negative at 10M -> capacity = 3M."""
    artifact = _tiny_artifact(n_rows=64, v=32)
    cfg = _base_config()
    model = _AlwaysLongModel(cfg)
    stats = _tiny_bucket_stats(v=32)
    e = _fresh_emitter()
    with patch(
        "price_space_llm.simulation.sweeps.run_simulation_with_trades",
        side_effect=_stub_run_simulation_with_trades,
    ):
        result = run_capacity_sweep(
            artifact, model, stats, _base_policy(),
            sizes_usd=(1_000_000.0, 3_000_000.0, 10_000_000.0),
            target_symbol="SPY",
            emitter=e,
            run_id="test-sweep-capacity-math",            checkpoint_step=0,
            checkpoint_run_id="test-ckpt",
            cost_calibration_run_id="test-cal",

        )
    assert result.capacity_usd == 3_000_000.0
    assert result.sharpe_at_capacity == pytest.approx(0.5)


def test_capacity_sweep_all_negative_returns_zero_capacity():
    """Every point's sharpe <= 0 -> capacity_usd = 0.0 (honest zero, not a fabricated ceiling)."""

    def _all_negative_stub(artifact, model, bucket_stats, policy, **kwargs):
        metrics = SimMetrics(
            sharpe_point=-0.3,
            sharpe_se=0.05,
            block_bootstrap_positive_fraction=0.2,
            max_drawdown=0.2,
            time_to_recovery_bars=50,
            hit_rate=0.4,
            n_bars=100,
            n_trades=3,
        )
        return SimResult(
            n_bars_processed=100, n_bars_skipped_undefined_vol=0, n_trades=3,
            trades=(), pnl_total=-500.0, metrics=metrics, notes="stub-neg",
        )

    artifact = _tiny_artifact(n_rows=64, v=32)
    cfg = _base_config()
    model = _AlwaysLongModel(cfg)
    stats = _tiny_bucket_stats(v=32)
    e = _fresh_emitter()
    with patch(
        "price_space_llm.simulation.sweeps.run_simulation_with_trades",
        side_effect=_all_negative_stub,
    ):
        result = run_capacity_sweep(
            artifact, model, stats, _base_policy(),
            sizes_usd=(1_000_000.0, 3_000_000.0),
            target_symbol="SPY",
            emitter=e,
            run_id="test-sweep-all-neg",            checkpoint_step=0,
            checkpoint_run_id="test-ckpt",
            cost_calibration_run_id="test-cal",

        )
    assert result.capacity_usd == 0.0
    assert result.sharpe_at_capacity == 0.0


def test_capacity_sweep_all_positive_returns_max_size():
    """Every point sharpe > 0 -> capacity_usd = largest size."""

    def _all_positive_stub(artifact, model, bucket_stats, policy, **kwargs):
        metrics = SimMetrics(
            sharpe_point=1.2,
            sharpe_se=0.1,
            block_bootstrap_positive_fraction=0.9,
            max_drawdown=0.05,
            time_to_recovery_bars=5,
            hit_rate=0.7,
            n_bars=100,
            n_trades=8,
        )
        return SimResult(
            n_bars_processed=100, n_bars_skipped_undefined_vol=0, n_trades=8,
            trades=(), pnl_total=5_000.0, metrics=metrics, notes="stub-pos",
        )

    artifact = _tiny_artifact(n_rows=64, v=32)
    cfg = _base_config()
    model = _AlwaysLongModel(cfg)
    stats = _tiny_bucket_stats(v=32)
    e = _fresh_emitter()
    with patch(
        "price_space_llm.simulation.sweeps.run_simulation_with_trades",
        side_effect=_all_positive_stub,
    ):
        result = run_capacity_sweep(
            artifact, model, stats, _base_policy(),
            sizes_usd=(1_000_000.0, 3_000_000.0, 10_000_000.0),
            target_symbol="SPY",
            emitter=e,
            run_id="test-sweep-all-pos",            checkpoint_step=0,
            checkpoint_run_id="test-ckpt",
            cost_calibration_run_id="test-cal",

        )
    assert result.capacity_usd == 10_000_000.0
    assert result.sharpe_at_capacity == pytest.approx(1.2)


def test_capacity_sweep_rejects_empty_sizes():
    artifact = _tiny_artifact(n_rows=32, v=32)
    cfg = _base_config()
    model = _AlwaysLongModel(cfg)
    stats = _tiny_bucket_stats(v=32)
    e = _fresh_emitter()
    with pytest.raises(ValueError, match="at least one size"):
        run_capacity_sweep(
            artifact, model, stats, _base_policy(),
            sizes_usd=(),
            target_symbol="SPY",
            emitter=e,
            run_id="test-sweep-empty",            checkpoint_step=0,
            checkpoint_run_id="test-ckpt",
            cost_calibration_run_id="test-cal",

        )


def test_capacity_point_dataclass_is_frozen():
    p = CapacityPoint(size_usd=1e6, sharpe=0.5, sharpe_se=0.05)
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        p.sharpe = 1.0  # type: ignore[misc]
