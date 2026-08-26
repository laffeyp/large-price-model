"""Sprint 103: perf-cleanup -- vectorized prices, searchsorted, cached train_means, Literal kind."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
import torch

from price_space_llm.simulation import build_equity_curve, compute_pnl
from price_space_llm.simulation.positions import Trade, derive_prices_from_log_returns
from price_space_llm.tokenizer.bucketize import BucketRow, BucketStats

# --- vectorized prices ----------------------------------------------------


def _reference_prices_loop(raw_targets: torch.Tensor) -> torch.Tensor:
    """Sprint 096 Python-loop reference implementation."""
    n = raw_targets.shape[0]
    if n == 0:
        return torch.zeros(0, dtype=torch.float64)
    prices = torch.empty(n, dtype=torch.float64)
    running = 1.0
    for i in range(n):
        r = float(raw_targets[i].item())
        if math.isfinite(r):
            running = running * math.exp(r)
        prices[i] = running
    return prices


def test_derive_prices_from_log_returns_vectorized_matches_loop_reference():
    """100-bar mixed-NaN input: vectorized output equals loop reference bit-tight."""
    torch.manual_seed(0)
    raw = torch.randn(100, dtype=torch.float32) * 0.005
    raw[10] = float("nan")
    raw[42] = float("nan")
    raw[77] = float("nan")
    vec = derive_prices_from_log_returns(raw)
    ref = _reference_prices_loop(raw)
    assert torch.allclose(vec, ref, atol=1e-10, rtol=1e-10), \
        f"vectorized diverges from reference at max index {(vec - ref).abs().argmax()}"


def test_derive_prices_from_log_returns_first_bar_holds_running_at_exp_of_first_return():
    """`prices[0] == exp(r_0)` on finite first return; `1.0` when NaN."""
    finite = torch.tensor([0.01, 0.005, -0.002], dtype=torch.float32)
    prices_f = derive_prices_from_log_returns(finite)
    assert prices_f[0].item() == pytest.approx(math.exp(0.01), rel=1e-6)
    nan_first = torch.tensor([float("nan"), 0.005, -0.002], dtype=torch.float32)
    prices_n = derive_prices_from_log_returns(nan_first)
    assert prices_n[0].item() == pytest.approx(1.0)


# --- cached train_means property -----------------------------------------


def test_bucket_stats_train_means_tensor_property_returns_correct_shape_and_values():
    """Property yields a [V] tensor matching per_bucket.train_mean values."""
    means = [-1.0, -0.5, 0.0, 0.5, 1.0]
    per_bucket = tuple(
        BucketRow(lower=None, upper=None, train_mean=m, train_median=m, train_frequency=0.2)
        for m in means
    )
    stats = BucketStats(
        n_buckets=32,  # type: ignore[arg-type]
        target_symbol="SPY",
        training_range_start="2020-01-01",
        training_range_end="2020-12-31",
        train_partition_row_count=100,
        edges=(-0.5, 0.0, 0.5),
        per_bucket=per_bucket,
    )
    t = stats.train_means_tensor
    assert t.shape == (5,)
    assert t.dtype == torch.float32
    assert torch.allclose(t, torch.tensor(means, dtype=torch.float32))


# --- searchsorted in build_equity_curve ---------------------------------


def _trade(*, entry_epoch: int, exit_epoch: int, entry_price: float,
           exit_price: float, size: float) -> Trade:
    pnl_g, pnl_n, cs, cl = compute_pnl(size, entry_price, exit_price, 0.0, 0.0)
    return Trade(
        trade_id=f"t-{entry_epoch}", entry_ts_utc=datetime.fromtimestamp(entry_epoch, tz=UTC),
        exit_ts_utc=datetime.fromtimestamp(exit_epoch, tz=UTC),
        direction="long" if size > 0 else "short",
        size=size, entry_price=entry_price, exit_price=exit_price,
        pnl_gross=pnl_g, pnl_net=pnl_n, cost_spread=cs, cost_slippage=cl,
        hold_duration_bars=(exit_epoch - entry_epoch) // 900,
    )


def test_build_equity_curve_searchsorted_matches_hand_computed_multi_trade_ledger():
    """Three trades over 10 bars: step-function equity matches hand-computed steps."""
    base = 1_600_000_000
    bar_ts = tuple(datetime.fromtimestamp(base + i * 900, tz=UTC) for i in range(10))
    trades = (
        _trade(entry_epoch=base, exit_epoch=base + 2 * 900,
               entry_price=100.0, exit_price=101.0, size=1_000_000.0),
        _trade(entry_epoch=base + 3 * 900, exit_epoch=base + 5 * 900,
               entry_price=101.0, exit_price=100.5, size=1_000_000.0),
        _trade(entry_epoch=base + 6 * 900, exit_epoch=base + 8 * 900,
               entry_price=100.5, exit_price=102.0, size=1_000_000.0),
    )
    equity = build_equity_curve(trades, bar_ts)
    # Each exit posts at searchsorted(bar_ts, exit_epoch, "right"):
    # exit at bar 2 -> idx 3; bar 5 -> idx 6; bar 8 -> idx 9.
    # pnl_net values: +10000, -4950.4950..., +14925.3731...
    p1 = 1_000_000.0 * (101.0 / 100.0 - 1.0)
    p2 = 1_000_000.0 * (100.5 / 101.0 - 1.0)
    p3 = 1_000_000.0 * (102.0 / 100.5 - 1.0)
    assert equity[2] == pytest.approx(0.0)
    assert equity[3] == pytest.approx(p1)
    assert equity[5] == pytest.approx(p1)
    assert equity[6] == pytest.approx(p1 + p2)
    assert equity[8] == pytest.approx(p1 + p2)
    assert equity[9] == pytest.approx(p1 + p2 + p3)


# --- Literal kind field (intent, not runtime enforcement) ---------------


def test_sim_result_notes_field_is_typed_literal():
    """The Literal annotation is a checker-time discriminator; runtime accepts strings."""
    from price_space_llm.simulation.skeleton import SimResult
    r = SimResult(n_bars_processed=100, notes="skeleton")
    assert r.notes == "skeleton"
    # The typing is the contract; runtime does not police Literal.
    # A mypy pass would reject `notes="wrong"`; this test pins that the
    # four declared values remain valid at construction time.
    valid_notes = (
        "skeleton", "predictions-only",
        "predictions+policy", "predictions+policy+trades",
    )
    for valid in valid_notes:
        SimResult(n_bars_processed=0, notes=valid)  # type: ignore[arg-type]
