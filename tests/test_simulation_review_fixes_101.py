"""Sprint 101: fail-loud on checkpoint kwargs (review §6.1)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import torch

from price_space_llm.model import (
    MarketStateTransformerConfig,
    TokenizedArtifact,
)
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary
from price_space_llm.simulation import (
    PolicyConfig,
    SimMetrics,
    SimResult,
    run_capacity_sweep,
    run_kappa_sensitivity,
)
from price_space_llm.simulation.skeleton import run_simulation_with_trades
from price_space_llm.tokenizer.bucketize import BucketRow, BucketStats


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

    def forward(self, feats):
        v = self.config.vocab_size
        logits = torch.full((1, 1, v), -100.0)
        logits[0, 0, v - 1] = 100.0
        return logits


def _tiny_artifact(n_rows: int = 32, v: int = 32) -> TokenizedArtifact:
    torch.manual_seed(0)
    return TokenizedArtifact(
        features={"target__SPY": torch.zeros(n_rows, 4)},
        targets=torch.zeros(n_rows, dtype=torch.int64),
        raw_targets=torch.linspace(-0.001, 0.001, n_rows, dtype=torch.float32),
        vol=torch.full((n_rows,), 0.01, dtype=torch.float32),
        timestamps=torch.arange(n_rows, dtype=torch.int64) * 900 + 1_600_000_000,
        is_overnight_gap=None,
        mask=torch.ones(n_rows, dtype=torch.bool),
        channel_names=("target__SPY",),
        meta={"normalized": True, "mask_semantics": "target_valid_v075"},
    )


def _base_policy() -> PolicyConfig:
    return PolicyConfig(threshold=1e-6, hysteresis=0.0, lambda_risk=0.0,
                        spread_cost_frac=0.0, slippage_frac=0.0,
                        position_size_usd=1_000_000.0)


def _base_config() -> MarketStateTransformerConfig:
    return MarketStateTransformerConfig(
        vocab_size=32, context_len=4,
        channel_dims={"target__SPY": 4}, d_model=16, n_heads=2,
    )


def test_run_simulation_with_trades_requires_checkpoint_kwargs():
    """The three checkpoint kwargs are required; omitting raises TypeError at call site."""
    art = _tiny_artifact()
    model = _AlwaysLongModel(_base_config())
    stats = _tiny_bucket_stats()
    e = StrictSignalEmitter(load_vocabulary(), max_buffer=65536)
    with pytest.raises(TypeError, match="checkpoint_step"):
        run_simulation_with_trades(
            art, model, stats, _base_policy(),
            target_symbol="SPY", emitter=e, run_id="test-101-missing",
        )


def _stub_captures(captured):
    def _stub(artifact, model, bucket_stats, policy, **kwargs):
        captured.append(kwargs)
        m = SimMetrics(sharpe_point=0.1, sharpe_se=0.02,
                       block_bootstrap_positive_fraction=0.6, max_drawdown=0.05,
                       time_to_recovery_bars=5, hit_rate=0.5, n_bars=100, n_trades=1)
        return SimResult(
            n_bars_processed=100, n_bars_skipped_undefined_vol=0, n_trades=1,
            trades=(), pnl_total=1.0, metrics=m, notes="stub",
        )
    return _stub


def test_run_capacity_sweep_forwards_checkpoint_kwargs():
    """The sweep threads checkpoint kwargs into every nested walker call."""
    art = _tiny_artifact()
    model = _AlwaysLongModel(_base_config())
    stats = _tiny_bucket_stats()
    e = StrictSignalEmitter(load_vocabulary(), max_buffer=65536)
    captured: list[dict] = []
    with patch(
        "price_space_llm.simulation.sweeps.run_simulation_with_trades",
        side_effect=_stub_captures(captured),
    ):
        run_capacity_sweep(
            art, model, stats, _base_policy(),
            sizes_usd=(1e6, 3e6),
            target_symbol="SPY", emitter=e, run_id="test-101-cap",
            checkpoint_step=42, checkpoint_run_id="ckpt-abc",
            cost_calibration_run_id="cal-xyz",
        )
    assert len(captured) == 2
    for call in captured:
        assert call["checkpoint_step"] == 42
        assert call["checkpoint_run_id"] == "ckpt-abc"
        assert call["cost_calibration_run_id"] == "cal-xyz"


def test_run_kappa_sensitivity_forwards_checkpoint_kwargs():
    """Symmetric with capacity."""
    art = _tiny_artifact()
    model = _AlwaysLongModel(_base_config())
    stats = _tiny_bucket_stats()
    e = StrictSignalEmitter(load_vocabulary(), max_buffer=65536)
    captured: list[dict] = []
    with patch(
        "price_space_llm.simulation.sweeps.run_simulation_with_trades",
        side_effect=_stub_captures(captured),
    ):
        run_kappa_sensitivity(
            art, model, stats, _base_policy(),
            kappa_multipliers=(0.5, 1.0, 2.0),
            target_symbol="SPY", emitter=e, run_id="test-101-kappa",
            checkpoint_step=99, checkpoint_run_id="ckpt-kappa",
            cost_calibration_run_id="cal-kappa",
        )
    assert len(captured) == 3
    for call in captured:
        assert call["checkpoint_step"] == 99
        assert call["checkpoint_run_id"] == "ckpt-kappa"
        assert call["cost_calibration_run_id"] == "cal-kappa"
