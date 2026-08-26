"""Sprint 104: shared axis-sweep helper (review §6.2)."""

from __future__ import annotations

from unittest.mock import patch

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
from price_space_llm.simulation.sweeps import run_axis_sweep
from price_space_llm.tokenizer.bucketize import BucketRow, BucketStats


def _stats(v: int = 32) -> BucketStats:
    means = [(-1.0 + 2.0 * i / (v - 1)) for i in range(v)]
    per_bucket = tuple(
        BucketRow(lower=None if i == 0 else (i - 1) / v,
                  upper=None if i == v - 1 else i / v,
                  train_mean=means[i], train_median=means[i],
                  train_frequency=1.0 / v)
        for i in range(v)
    )
    return BucketStats(
        n_buckets=v,  # type: ignore[arg-type]
        target_symbol="SPY", training_range_start="2020-01-01",
        training_range_end="2020-12-31", train_partition_row_count=1000,
        edges=tuple(sorted(means[1:])), per_bucket=per_bucket,
    )


class _AlwaysLongModel(torch.nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.config = cfg
        self.dummy = torch.nn.Parameter(torch.zeros(1))

    def forward(self, feats):
        v = self.config.vocab_size
        logits = torch.full((1, 1, v), -100.0)
        logits[0, 0, v - 1] = 100.0
        return logits


def _art(n: int = 32, v: int = 32) -> TokenizedArtifact:
    return TokenizedArtifact(
        features={"target__SPY": torch.zeros(n, 4)},
        targets=torch.zeros(n, dtype=torch.int64),
        raw_targets=torch.linspace(-0.001, 0.001, n, dtype=torch.float32),
        vol=torch.full((n,), 0.01, dtype=torch.float32),
        timestamps=torch.arange(n, dtype=torch.int64) * 900 + 1_600_000_000,
        is_overnight_gap=None, mask=torch.ones(n, dtype=torch.bool),
        channel_names=("target__SPY",),
        meta={"normalized": True, "mask_semantics": "target_valid_v075"},
    )


def _policy():
    return PolicyConfig(threshold=1e-6, hysteresis=0.0, lambda_risk=0.0,
                        spread_cost_frac=0.0, slippage_frac=1e-4,
                        position_size_usd=1_000_000.0)


def _cfg():
    return MarketStateTransformerConfig(
        vocab_size=32, context_len=4,
        channel_dims={"target__SPY": 4}, d_model=16, n_heads=2,
    )


def _stub_metrics() -> SimResult:
    m = SimMetrics(sharpe_point=0.3, sharpe_se=0.05,
                   block_bootstrap_positive_fraction=0.7, max_drawdown=0.1,
                   time_to_recovery_bars=5, hit_rate=0.6, n_bars=100, n_trades=2)
    return SimResult(
        n_bars_processed=100, n_bars_skipped_undefined_vol=0, n_trades=2,
        trades=(), pnl_total=200.0, metrics=m, notes="stub",
    )


def test_run_axis_sweep_writes_expected_field_on_policy_and_calls_walker_per_value():
    """`value_to_policy` and `policy_field` land on the walker's PolicyConfig."""
    captured_policies: list[PolicyConfig] = []

    def _stub(artifact, model, bucket_stats, policy, **kw):
        captured_policies.append(policy)
        return _stub_metrics()

    e = StrictSignalEmitter(load_vocabulary(), max_buffer=65536)
    art = _art()
    model = _AlwaysLongModel(_cfg())
    stats = _stats()
    with patch("price_space_llm.simulation.sweeps.run_simulation_with_trades",
               side_effect=_stub):
        result = run_axis_sweep(
            art, model, stats, _policy(), values=(0.5, 1.0, 2.0),
            policy_field="slippage_frac",
            value_to_policy=lambda v, tpl: tpl.slippage_frac * v,
            sub_run_id=lambda parent, v: f"{parent}-x-{v}",
            target_symbol="SPY", emitter=e, run_id="axis-run",
            checkpoint_step=1, checkpoint_run_id="ckpt", cost_calibration_run_id="cal",
            split="train",
            date_range_start=__import__("datetime").date(2020, 1, 1),
            date_range_end=__import__("datetime").date(2020, 12, 31),
        )
    assert len(result) == 3
    assert len(captured_policies) == 3
    # slippage_frac was 1e-4; multipliers scale it
    assert captured_policies[0].slippage_frac == 0.5e-4
    assert captured_policies[1].slippage_frac == 1.0e-4
    assert captured_policies[2].slippage_frac == 2.0e-4


def test_capacity_and_sensitivity_delegate_to_shared_helper_preserving_output_shape():
    """Post-refactor: both sweeps produce the same result-dataclass shape as before."""
    art = _art()
    model = _AlwaysLongModel(_cfg())
    stats = _stats()
    e1 = StrictSignalEmitter(load_vocabulary(), max_buffer=65536)
    e2 = StrictSignalEmitter(load_vocabulary(), max_buffer=65536)
    with patch("price_space_llm.simulation.sweeps.run_simulation_with_trades",
               side_effect=lambda *a, **kw: _stub_metrics()):
        cap = run_capacity_sweep(
            art, model, stats, _policy(), sizes_usd=(1e6, 3e6),
            target_symbol="SPY", emitter=e1, run_id="cap-104",
            checkpoint_step=0, checkpoint_run_id="c", cost_calibration_run_id="c",
        )
        sens = run_kappa_sensitivity(
            art, model, stats, _policy(), kappa_multipliers=(0.5, 1.0, 2.0),
            target_symbol="SPY", emitter=e2, run_id="sens-104",
            checkpoint_step=0, checkpoint_run_id="c", cost_calibration_run_id="c",
        )
    assert len(cap.points) == 2
    assert cap.points[0].size_usd == 1e6
    assert len(sens.points) == 3
    assert sens.points[0].kappa_multiplier == 0.5
