"""Sprint 096: position state machine + trades — three new emit sites."""

from __future__ import annotations

from dataclasses import replace as dataclass_replace
from datetime import date

import pytest
import torch

from price_space_llm.model import (
    MarketStateTransformer,
    MarketStateTransformerConfig,
    TokenizedArtifact,
)
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary
from price_space_llm.simulation import (
    PolicyConfig,
    compute_pnl,
    derive_prices_from_log_returns,
    run_simulation_with_trades,
)
from price_space_llm.tokenizer.bucketize import BucketRow, BucketStats


def _fresh_emitter(max_buffer: int = 16384) -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


# --- compute_pnl -----------------------------------------------------------


def test_compute_pnl_long_profit_no_costs():
    """size=+1M, entry=100, exit=101 -> pnl_gross = +10_000; zero costs -> pnl_net = pnl_gross."""
    gross, net, cost_spread, cost_slippage = compute_pnl(
        size=1_000_000.0,
        entry_price=100.0,
        exit_price=101.0,
        spread_cost_frac=0.0,
        slippage_frac=0.0,
    )
    assert gross == pytest.approx(10_000.0)
    assert net == pytest.approx(10_000.0)
    assert cost_spread == 0.0
    assert cost_slippage == 0.0


def test_compute_pnl_short_profit_when_price_falls():
    """size=-1M, entry=100, exit=99 -> pnl_gross = +10_000 (short profits on drop)."""
    gross, net, _cs, _csl = compute_pnl(
        size=-1_000_000.0,
        entry_price=100.0,
        exit_price=99.0,
        spread_cost_frac=0.0,
        slippage_frac=0.0,
    )
    assert gross == pytest.approx(10_000.0)
    assert net == pytest.approx(10_000.0)


def test_compute_pnl_long_loss_when_price_falls():
    """size=+1M, entry=100, exit=99 -> pnl_gross = -10_000."""
    gross, _net, _cs, _csl = compute_pnl(
        size=1_000_000.0,
        entry_price=100.0,
        exit_price=99.0,
        spread_cost_frac=0.0,
        slippage_frac=0.0,
    )
    assert gross == pytest.approx(-10_000.0)


def test_compute_pnl_subtracts_costs():
    """pnl_net = pnl_gross - cost_spread - cost_slippage."""
    gross, net, cost_spread, cost_slippage = compute_pnl(
        size=1_000_000.0,
        entry_price=100.0,
        exit_price=101.0,
        spread_cost_frac=0.001,   # 10 bps round trip
        slippage_frac=0.0005,     # 5 bps
    )
    assert gross == pytest.approx(10_000.0)
    assert cost_spread == pytest.approx(1_000.0)     # 0.001 * 1M
    assert cost_slippage == pytest.approx(500.0)     # 0.0005 * 1M
    assert net == pytest.approx(10_000.0 - 1_000.0 - 500.0)


def test_compute_pnl_rejects_non_positive_entry_price():
    with pytest.raises(ValueError, match="entry_price"):
        compute_pnl(1.0, 0.0, 1.0, 0.0, 0.0)


# --- derive_prices_from_log_returns ---------------------------------------


def test_derive_prices_anchor_at_one_and_step_by_exp():
    raw = torch.tensor([0.01, -0.005, 0.02], dtype=torch.float32)
    p = derive_prices_from_log_returns(raw)
    assert p.shape == (3,)
    assert p[0].item() == pytest.approx(1.0 * torch.exp(torch.tensor(0.01)).item())
    assert p[1].item() == pytest.approx(p[0].item() * torch.exp(torch.tensor(-0.005)).item())
    assert p[2].item() == pytest.approx(p[1].item() * torch.exp(torch.tensor(0.02)).item())


def test_derive_prices_nan_holds_last_valid():
    raw = torch.tensor([0.01, float("nan"), 0.02], dtype=torch.float32)
    p = derive_prices_from_log_returns(raw)
    # Row 1 NaN: price stays at p[0].
    assert p[1].item() == pytest.approx(p[0].item())
    # Row 2 advances from p[1] (== p[0]) by exp(0.02).
    assert p[2].item() == pytest.approx(p[0].item() * torch.exp(torch.tensor(0.02)).item())


def test_derive_prices_empty_returns_empty():
    p = derive_prices_from_log_returns(torch.zeros(0, dtype=torch.float32))
    assert p.shape == (0,)


# --- run_simulation_with_trades end-to-end --------------------------------


def _tiny_artifact(n_rows: int = 128, v: int = 32) -> TokenizedArtifact:
    torch.manual_seed(0)
    # Deterministic small log_returns so prices stay near 1.0.
    raw = torch.linspace(-0.01, 0.01, n_rows, dtype=torch.float32)
    return TokenizedArtifact(
        features={"target__SPY": torch.randn(n_rows, 4) * 0.1},
        targets=torch.randint(0, v, (n_rows,), dtype=torch.int64),
        raw_targets=raw,
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


class _AlternatingLogitsModel(torch.nn.Module):
    """Sprint 094 fixture — even calls return top-bucket mass, odd calls bottom-bucket mass."""

    def __init__(self, cfg: MarketStateTransformerConfig) -> None:
        super().__init__()
        self.config = cfg
        self._call_count = 0
        self.dummy = torch.nn.Parameter(torch.zeros(1))

    def forward(self, feats: dict[str, torch.Tensor]) -> torch.Tensor:
        v = self.config.vocab_size
        logits = torch.full((1, 1, v), -100.0)
        if self._call_count % 2 == 0:
            logits[0, 0, v - 1] = 100.0
        else:
            logits[0, 0, 0] = 100.0
        self._call_count += 1
        return logits

    def eval(self) -> _AlternatingLogitsModel:  # type: ignore[override]
        return self


def test_run_simulation_with_trades_refuses_without_raw_targets():
    """Sprint 088 field is a hard requirement for the trades walker."""
    n_rows = 128
    v = 32
    artifact = _tiny_artifact(n_rows=n_rows, v=v)
    artifact = dataclass_replace(artifact, raw_targets=None)
    cfg = MarketStateTransformerConfig(
        vocab_size=v, context_len=32, channel_dims={"target__SPY": 4}, d_model=64, n_heads=4,
    )
    model = MarketStateTransformer(cfg)
    stats = _tiny_bucket_stats(v=v)
    policy = PolicyConfig(
        threshold=0.01, hysteresis=0.5, lambda_risk=0.0,
        spread_cost_frac=0.0, slippage_frac=0.0, position_size_usd=1_000_000.0,
    )
    e = _fresh_emitter()
    with pytest.raises(ValueError, match="raw_targets"):
        run_simulation_with_trades(
            artifact, model, stats, policy,
            target_symbol="SPY", emitter=e, run_id="test-trade-refuse",
                checkpoint_step=0,
                checkpoint_run_id="test-ckpt",
                cost_calibration_run_id="test-cal",
        )


def test_run_simulation_with_trades_scripted_flip_ledgers_trades():
    """Alternating logits + tight threshold -> repeated open/close/ledger events."""
    n_rows = 96
    v = 32
    context_len = 4
    artifact = _tiny_artifact(n_rows=n_rows, v=v)
    cfg = MarketStateTransformerConfig(
        vocab_size=v, context_len=context_len, channel_dims={"target__SPY": 4},
        d_model=16, n_heads=2,
    )
    model = _AlternatingLogitsModel(cfg)
    stats = _tiny_bucket_stats(v=v)
    policy = PolicyConfig(
        threshold=1e-6, hysteresis=0.0, lambda_risk=0.0,
        spread_cost_frac=0.0, slippage_frac=0.0, position_size_usd=1_000_000.0,
    )
    e = _fresh_emitter()
    result = run_simulation_with_trades(
        artifact, model, stats, policy,
        target_symbol="SPY", emitter=e, run_id="test-trade-flips",
            checkpoint_step=0,
            checkpoint_run_id="test-ckpt",
            cost_calibration_run_id="test-cal",
        split="train",
        date_range_start=date(2020, 1, 1), date_range_end=date(2020, 12, 31),
    )
    tags = [s.tag for s in e.snapshot()]
    assert "POSITION_OPENED" in tags
    assert "POSITION_CLOSED" in tags
    assert "TRADE_LEDGERED" in tags
    # Trade count equals the count of TRADE_LEDGERED emits, which equals the
    # count of POSITION_CLOSED emits, which equals ledger length.
    n_ledgered = tags.count("TRADE_LEDGERED")
    n_closed = tags.count("POSITION_CLOSED")
    assert n_ledgered == n_closed
    assert n_ledgered == len(result.trades)
    assert result.n_trades == n_ledgered
    # pnl_total sums the ledger.
    assert result.pnl_total == pytest.approx(sum(t.pnl_net for t in result.trades))


def test_run_simulation_with_trades_end_of_range_flush():
    """A position still open at the last valid bar force-closes with close_kind=sim_range_end."""

    # Model that always predicts strong-long (never flips).
    class _AlwaysLongModel(torch.nn.Module):
        def __init__(self, cfg_inner: MarketStateTransformerConfig) -> None:
            super().__init__()
            self.config = cfg_inner
            self.dummy = torch.nn.Parameter(torch.zeros(1))

        def forward(
            self, feats: dict[str, torch.Tensor]
        ) -> torch.Tensor:
            v = self.config.vocab_size
            logits = torch.full((1, 1, v), -100.0)
            logits[0, 0, v - 1] = 100.0
            return logits

        def eval(self) -> _AlwaysLongModel:  # type: ignore[override]
            return self

    n_rows = 32
    v = 32
    context_len = 4
    artifact = _tiny_artifact(n_rows=n_rows, v=v)
    cfg = MarketStateTransformerConfig(
        vocab_size=v, context_len=context_len, channel_dims={"target__SPY": 4},
        d_model=16, n_heads=2,
    )
    model = _AlwaysLongModel(cfg)
    stats = _tiny_bucket_stats(v=v)
    policy = PolicyConfig(
        threshold=1e-6, hysteresis=0.0, lambda_risk=0.0,
        spread_cost_frac=0.0, slippage_frac=0.0, position_size_usd=1_000_000.0,
    )
    e = _fresh_emitter()
    result = run_simulation_with_trades(
        artifact, model, stats, policy,
        target_symbol="SPY", emitter=e, run_id="test-trade-flush",
            checkpoint_step=0,
            checkpoint_run_id="test-ckpt",
            cost_calibration_run_id="test-cal",
    )
    closes = [s for s in e.snapshot() if s.tag == "POSITION_CLOSED"]
    # Exactly one close, at the end-of-range flush.
    assert len(closes) == 1
    assert closes[-1].payload["close_kind"] == "sim_range_end"
    assert len(result.trades) == 1
    # Ledger's exit_ts_utc matches the last bar's timestamp.
    last_ts = int(artifact.timestamps[-1].item())
    from datetime import UTC, datetime
    expected_last_iso = datetime.fromtimestamp(last_ts, tz=UTC).isoformat()
    assert closes[-1].payload["fill_bar_ts"] == expected_last_iso
