"""Sprint 097: simulator metrics + block bootstrap on the trade ledger."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from price_space_llm.simulation import (
    Trade,
    block_bootstrap_sharpe,
    build_equity_curve,
    compute_sharpe,
    compute_sim_metrics,
    max_drawdown_from_equity,
    time_to_recovery_bars_from_equity,
)


def _mk_trade(exit_offset_seconds: int, pnl_net: float) -> Trade:
    base = datetime(2020, 1, 1, tzinfo=UTC)
    return Trade(
        trade_id=f"t-{exit_offset_seconds}",
        entry_ts_utc=base,
        exit_ts_utc=base + timedelta(seconds=exit_offset_seconds),
        direction="long",
        size=1_000_000.0,
        entry_price=100.0,
        exit_price=100.0 + pnl_net / 10_000.0,
        pnl_gross=pnl_net,
        pnl_net=pnl_net,
        cost_spread=0.0,
        cost_slippage=0.0,
        hold_duration_bars=1,
    )


# --- build_equity_curve ---------------------------------------------------


def test_build_equity_curve_step_at_each_exit():
    """Three trades exiting at bar 10, 20, 30 with pnl [+100, -50, +30]."""
    bars = tuple(
        datetime(2020, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * i) for i in range(40)
    )
    # 15 * 60 = 900 seconds per bar. Trade exits at 15-min offsets aligned to bars.
    trades = (
        _mk_trade(exit_offset_seconds=900 * 10, pnl_net=+100.0),
        _mk_trade(exit_offset_seconds=900 * 20, pnl_net=-50.0),
        _mk_trade(exit_offset_seconds=900 * 30, pnl_net=+30.0),
    )
    equity = build_equity_curve(trades, bars)
    # exit at bar 10 → equity advances at bar 11 (bisect_right picks strictly-greater timestamp).
    assert equity[10] == pytest.approx(0.0)
    assert equity[11] == pytest.approx(100.0)
    assert equity[20] == pytest.approx(100.0)
    assert equity[21] == pytest.approx(50.0)
    assert equity[30] == pytest.approx(50.0)
    assert equity[31] == pytest.approx(80.0)
    assert equity[-1] == pytest.approx(80.0)


def test_build_equity_curve_empty_trades_returns_zero_series():
    bars = tuple(
        datetime(2020, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * i) for i in range(5)
    )
    equity = build_equity_curve((), bars)
    assert equity.shape == (5,)
    assert np.all(equity == 0.0)


# --- compute_sharpe ------------------------------------------------------


def test_compute_sharpe_zero_std_returns_zero():
    """Constant series → 0.0 without divide-by-zero."""
    bar_pnl = np.zeros(100)
    assert compute_sharpe(bar_pnl) == 0.0


def test_compute_sharpe_empty_returns_zero():
    assert compute_sharpe(np.array([])) == 0.0


def test_compute_sharpe_matches_hand_computed():
    """Alternating +1/-1 → mean 0 → Sharpe 0. Off-center series matches sqrt(6552)*mean/std."""
    bar_pnl = np.array([1.0, -1.0, 1.0, -1.0])
    assert compute_sharpe(bar_pnl) == pytest.approx(0.0, abs=1e-10)
    # Bias by +0.5 → mean 0.5, std = 1.0 → sharpe = sqrt(6552) * 0.5.
    bar_pnl2 = np.array([1.5, -0.5, 1.5, -0.5])
    expected = math.sqrt(6552) * 0.5 / 1.0
    assert compute_sharpe(bar_pnl2) == pytest.approx(expected)


# --- max_drawdown + time_to_recovery ------------------------------------


def test_max_drawdown_monotone_equity_returns_zero():
    equity = np.array([0.0, 10.0, 20.0, 30.0])
    dd, trough = max_drawdown_from_equity(equity)
    assert dd == 0.0
    assert trough == 0


def test_max_drawdown_v_shape():
    """equity [0, 100, 50, 150] → dd = 0.5 at index 2."""
    equity = np.array([0.0, 100.0, 50.0, 150.0])
    dd, trough = max_drawdown_from_equity(equity)
    assert dd == pytest.approx(0.5)
    assert trough == 2


def test_max_drawdown_empty_returns_zero():
    dd, trough = max_drawdown_from_equity(np.array([]))
    assert dd == 0.0
    assert trough == 0


def test_time_to_recovery_from_trough():
    """[0, 100, 50, 150] → trough at 2, recovery at 3 → 1 bar."""
    equity = np.array([0.0, 100.0, 50.0, 150.0])
    _, trough = max_drawdown_from_equity(equity)
    ttr = time_to_recovery_bars_from_equity(equity, trough)
    assert ttr == 1


def test_time_to_recovery_unrecovered_returns_bars_remaining():
    """[0, 100, 50, 60]: trough at 2; never recovers to 100 → returns bars remaining (1)."""
    equity = np.array([0.0, 100.0, 50.0, 60.0])
    _, trough = max_drawdown_from_equity(equity)
    ttr = time_to_recovery_bars_from_equity(equity, trough)
    assert ttr == 1


# --- block_bootstrap_sharpe ---------------------------------------------


def test_block_bootstrap_sharpe_reproducible_with_seed():
    """Same seed → identical (se, positive_fraction)."""
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    bar_pnl = np.concatenate([np.ones(546), -np.ones(546), np.zeros(546)])
    se1, pf1 = block_bootstrap_sharpe(bar_pnl, n_resamples=100, rng=rng1)
    se2, pf2 = block_bootstrap_sharpe(bar_pnl, n_resamples=100, rng=rng2)
    assert se1 == se2
    assert pf1 == pf2
    assert 0.0 <= pf1 <= 1.0
    assert se1 >= 0.0


def test_block_bootstrap_sharpe_short_series_returns_zero():
    """Fewer than bars_per_block bars → (0, 0), no crash."""
    bar_pnl = np.ones(100)
    se, pf = block_bootstrap_sharpe(bar_pnl, n_resamples=10)
    assert se == 0.0
    assert pf == 0.0


# --- compute_sim_metrics orchestrator -----------------------------------


def test_compute_sim_metrics_empty_ledger_returns_zeros():
    bars = tuple(
        datetime(2020, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * i) for i in range(10)
    )
    m = compute_sim_metrics((), bars)
    assert m.n_bars == 10
    assert m.n_trades == 0
    assert m.sharpe_point == 0.0
    assert m.sharpe_se == 0.0
    assert m.block_bootstrap_positive_fraction == 0.0
    assert m.max_drawdown == 0.0
    assert m.time_to_recovery_bars == 0
    assert m.hit_rate == 0.0


def test_compute_sim_metrics_populates_all_fields():
    """Three trades over ~40 bars: metrics populate; hit_rate matches count."""
    bars = tuple(
        datetime(2020, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * i) for i in range(40)
    )
    trades = (
        _mk_trade(900 * 10, +100.0),
        _mk_trade(900 * 20, -50.0),
        _mk_trade(900 * 30, +30.0),
    )
    m = compute_sim_metrics(trades, bars, n_resamples=100, rng_seed=0)
    assert m.n_bars == 40
    assert m.n_trades == 3
    # hit_rate: two winners of three.
    assert m.hit_rate == pytest.approx(2.0 / 3.0)
    # sharpe_se is 0.0 because the 40-bar series is shorter than bars_per_block=546.
    assert m.sharpe_se == 0.0
    assert m.block_bootstrap_positive_fraction == 0.0
    # Equity curve peaks at bar 11 with +100 and troughs at bar 21 with +50 → dd = 0.5.
    assert m.max_drawdown == pytest.approx(0.5)
    # Recovery at bar 31 (equity 80) never exceeds 100 → returns bars_remaining.
    assert m.time_to_recovery_bars >= 1
