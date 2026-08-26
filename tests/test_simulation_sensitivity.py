"""Sprint 099: kappa sensitivity plot -- SENSITIVITY_PLOT_GENERATED emit + zero-crossing math."""

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
    run_kappa_sensitivity,
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


def _base_policy() -> PolicyConfig:
    return PolicyConfig(
        threshold=1e-6,
        hysteresis=0.0,
        lambda_risk=0.0,
        spread_cost_frac=0.0,
        slippage_frac=1e-4,
        position_size_usd=1_000_000.0,
    )


def _base_config(v: int = 32, context_len: int = 4) -> MarketStateTransformerConfig:
    return MarketStateTransformerConfig(
        vocab_size=v,
        context_len=context_len,
        channel_dims={"target__SPY": 4},
        d_model=16,
        n_heads=2,
    )


def _make_metrics(sharpe: float) -> SimMetrics:
    return SimMetrics(
        sharpe_point=sharpe,
        sharpe_se=0.05,
        block_bootstrap_positive_fraction=0.8 if sharpe > 0 else 0.2,
        max_drawdown=0.1,
        time_to_recovery_bars=10,
        hit_rate=0.55,
        n_bars=100,
        n_trades=5,
    )


def _make_sim_result(sharpe: float) -> SimResult:
    return SimResult(
        n_bars_processed=100,
        n_bars_skipped_undefined_vol=0,
        n_trades=5,
        trades=(),
        pnl_total=100.0,
        metrics=_make_metrics(sharpe),
        notes="stub",
    )


# --- shape ----------------------------------------------------------------


def test_sensitivity_result_has_one_point_per_multiplier():
    artifact = _tiny_artifact()
    model = _AlwaysLongModel(_base_config())
    stats = _tiny_bucket_stats()
    e = _fresh_emitter()
    result = run_kappa_sensitivity(
        artifact, model, stats, _base_policy(),
        kappa_multipliers=(0.5, 0.75, 1.0, 1.25, 1.5),
        target_symbol="SPY", emitter=e, run_id="test-sens-5pts",
            checkpoint_step=0,
            checkpoint_run_id="test-ckpt",
            cost_calibration_run_id="test-cal",
    )
    assert len(result.points) == 5
    assert [p.kappa_multiplier for p in result.points] == [0.5, 0.75, 1.0, 1.25, 1.5]


# --- zero-crossing --------------------------------------------------------


def test_sensitivity_crosses_zero_true_when_positive_and_negative():
    """Some multipliers profit, some lose -> flag True."""
    call_i = {"n": 0}
    sharpe_schedule = [0.4, 0.2, 0.05, -0.1, -0.3]

    def _stub(*a, **kw):
        s = sharpe_schedule[call_i["n"]]
        call_i["n"] += 1
        return _make_sim_result(s)

    artifact = _tiny_artifact()
    model = _AlwaysLongModel(_base_config())
    stats = _tiny_bucket_stats()
    e = _fresh_emitter()
    with patch(
        "price_space_llm.simulation.sweeps.run_simulation_with_trades",
        side_effect=_stub,
    ):
        result = run_kappa_sensitivity(
            artifact, model, stats, _base_policy(),
            kappa_multipliers=(0.5, 0.75, 1.0, 1.5, 2.0),
            target_symbol="SPY", emitter=e, run_id="test-sens-cross",
                checkpoint_step=0,
                checkpoint_run_id="test-ckpt",
                cost_calibration_run_id="test-cal",
        )
    assert result.sharpe_crosses_zero_in_range is True
    assert result.min_sharpe == pytest.approx(-0.3)
    assert result.max_sharpe == pytest.approx(0.4)


def test_sensitivity_crosses_zero_false_when_all_positive():
    def _stub(*a, **kw):
        return _make_sim_result(0.5)

    artifact = _tiny_artifact()
    model = _AlwaysLongModel(_base_config())
    stats = _tiny_bucket_stats()
    e = _fresh_emitter()
    with patch(
        "price_space_llm.simulation.sweeps.run_simulation_with_trades",
        side_effect=_stub,
    ):
        result = run_kappa_sensitivity(
            artifact, model, stats, _base_policy(),
            kappa_multipliers=(0.5, 1.0, 2.0),
            target_symbol="SPY", emitter=e, run_id="test-sens-allpos",
                checkpoint_step=0,
                checkpoint_run_id="test-ckpt",
                cost_calibration_run_id="test-cal",
        )
    assert result.sharpe_crosses_zero_in_range is False


def test_sensitivity_crosses_zero_false_when_all_negative():
    def _stub(*a, **kw):
        return _make_sim_result(-0.4)

    artifact = _tiny_artifact()
    model = _AlwaysLongModel(_base_config())
    stats = _tiny_bucket_stats()
    e = _fresh_emitter()
    with patch(
        "price_space_llm.simulation.sweeps.run_simulation_with_trades",
        side_effect=_stub,
    ):
        result = run_kappa_sensitivity(
            artifact, model, stats, _base_policy(),
            kappa_multipliers=(0.5, 1.0, 2.0),
            target_symbol="SPY", emitter=e, run_id="test-sens-allneg",
                checkpoint_step=0,
                checkpoint_run_id="test-ckpt",
                cost_calibration_run_id="test-cal",
        )
    assert result.sharpe_crosses_zero_in_range is False


# --- emits ----------------------------------------------------------------


def test_sensitivity_emits_generated_tag_once():
    artifact = _tiny_artifact()
    model = _AlwaysLongModel(_base_config())
    stats = _tiny_bucket_stats()
    e = _fresh_emitter()
    run_kappa_sensitivity(
        artifact, model, stats, _base_policy(),
        kappa_multipliers=(0.5, 1.0, 2.0),
        target_symbol="SPY", emitter=e, run_id="test-sens-emit",
            checkpoint_step=0,
            checkpoint_run_id="test-ckpt",
            cost_calibration_run_id="test-cal",
    )
    generated = [s for s in e.snapshot() if s.tag == "SENSITIVITY_PLOT_GENERATED"]
    assert len(generated) == 1
    payload = generated[0].payload
    assert payload["run_id"] == "test-sens-emit"
    assert payload["kappa_multipliers"] == [0.5, 1.0, 2.0]
    assert len(payload["sharpe_by_multiplier"]) == 3
    assert set(payload.keys()) >= {
        "run_id", "kappa_multipliers", "sharpe_by_multiplier",
        "min_sharpe", "max_sharpe", "sharpe_crosses_zero_in_range",
    }


def test_sensitivity_emits_one_sim_run_pair_per_multiplier():
    artifact = _tiny_artifact()
    model = _AlwaysLongModel(_base_config())
    stats = _tiny_bucket_stats()
    e = _fresh_emitter()
    run_kappa_sensitivity(
        artifact, model, stats, _base_policy(),
        kappa_multipliers=(0.5, 1.0, 1.5, 2.0),
        target_symbol="SPY", emitter=e, run_id="test-sens-pairs",
            checkpoint_step=0,
            checkpoint_run_id="test-ckpt",
            cost_calibration_run_id="test-cal",
    )
    tags = [s.tag for s in e.snapshot()]
    assert tags.count("SIM_RUN_STARTED") == 4
    assert tags.count("SIM_RUN_COMPLETED") == 4


# --- empty guard ----------------------------------------------------------


def test_sensitivity_rejects_empty_multipliers():
    artifact = _tiny_artifact()
    model = _AlwaysLongModel(_base_config())
    stats = _tiny_bucket_stats()
    e = _fresh_emitter()
    with pytest.raises(ValueError, match="at least one multiplier"):
        run_kappa_sensitivity(
            artifact, model, stats, _base_policy(),
            kappa_multipliers=(),
            target_symbol="SPY", emitter=e, run_id="test-sens-empty",
                checkpoint_step=0,
                checkpoint_run_id="test-ckpt",
                cost_calibration_run_id="test-cal",
        )
