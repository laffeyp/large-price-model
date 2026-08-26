"""Sprint 097: simulator metrics + block bootstrap on the trade ledger.

Formulas per tech-arch § 11.5:

    equity[t]           = sum of pnl_net for trades exited on or before bar t.
    bar_pnl[t]          = equity[t] - equity[t-1].
    sharpe (annualized) = sqrt(bars_per_year) * mean(bar_pnl) / std(bar_pnl).
    max_drawdown        = max(cummax(equity) - equity) / max(cummax(equity), eps).
    time_to_recovery    = bars from drawdown trough to first bar where equity
                          re-touches the pre-drawdown peak. Unrecovered runs
                          report bars_remaining.
    hit_rate            = mean(1[pnl_net > 0]) over the trade ledger.
    block bootstrap     = 18 non-overlapping monthly blocks (546 bars each)
                          x 10,000 resamples with replacement; per resample
                          concatenate sampled blocks, compute sharpe, collect.
                          SE = std(resample_sharpes); positive_fraction = mean(> 0).

Sprint 100 lands the mark-to-market opt-in per review §4.1. When the caller
passes a `prices` array to `build_equity_curve`, the curve carries per-bar
unrealized P&L for any open position: for bars in `[entry_bar_idx, exit_bar_idx)`,
`equity[t] += signed_size * (price[t] - entry_price) / entry_price`; at
`exit_bar_idx` the closed `pnl_net` posts (unrealized becomes realized, costs
land as a one-bar step). Without `prices`, the Sprint 097 closed-trade
step-function form ships unchanged for backwards compatibility.

`bars_per_year = 6552` = 252 trading days x 26 15-min RTH bars per day.
`bars_per_block = 546` = 21 trading days x 26 bars per month.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from price_space_llm.simulation.positions import Trade

BARS_PER_YEAR_DEFAULT = 6552
BARS_PER_BLOCK_DEFAULT = 546  # 21 trading days x 26 15-min RTH bars per day
N_BLOCKS_DEFAULT = 18
N_RESAMPLES_DEFAULT = 10_000


@dataclass(slots=True, frozen=True, kw_only=True)
class SimMetrics:
    """Numeric summary for `SIM_RUN_COMPLETED` payload + downstream reports."""

    sharpe_point: float
    sharpe_se: float
    block_bootstrap_positive_fraction: float
    max_drawdown: float
    time_to_recovery_bars: int
    hit_rate: float
    n_bars: int
    n_trades: int


def build_equity_curve(
    trades: tuple[Trade, ...],
    bar_timestamps_utc: tuple[datetime, ...],
    *,
    prices: np.ndarray | None = None,
) -> np.ndarray:
    """Return `equity[t]` for each bar.

    Without `prices` (Sprint 097 default): `equity[t]` = cumulative `pnl_net`
    of trades exited on or before bar `t`. Step function at trade exits.

    With `prices` (Sprint 100, tech-arch §11.5): continuous mark-to-market.
    For each trade, bars in `[entry_bar_idx, exit_bar_idx)` carry unrealized
    P&L `signed_size * (prices[t] - entry_price) / entry_price`; at
    `exit_bar_idx` the closed `pnl_net` posts (unrealized becomes realized,
    costs land as a one-bar step). `prices` must have the same length as
    `bar_timestamps_utc`.

    Trades whose `exit_ts_utc` sit before the first bar timestamp contribute
    at bar 0. Trades whose `exit_ts_utc` sit after the last bar are dropped
    from the curve (they belong to a later window; the caller is responsible
    for the ledger-vs-window match).
    """
    n = len(bar_timestamps_utc)
    equity: np.ndarray = np.zeros(n, dtype=np.float64)
    if n == 0 or not trades:
        return equity
    # Sprint 103 (review §3.3): vectorized index resolution via searchsorted.
    sorted_bar_ts: np.ndarray = np.fromiter(
        (ts.timestamp() for ts in bar_timestamps_utc), dtype=np.float64, count=n
    )
    exit_epochs: np.ndarray = np.fromiter(
        (tr.exit_ts_utc.timestamp() for tr in trades), dtype=np.float64, count=len(trades)
    )
    exit_indices_arr = np.asarray(
        np.searchsorted(sorted_bar_ts, exit_epochs, side="right"),
        dtype=np.int64,
    )
    exit_indices = [int(x) for x in exit_indices_arr.tolist()]
    if prices is not None:
        if prices.shape[0] != n:
            raise ValueError(
                f"build_equity_curve: prices length {prices.shape[0]} "
                f"!= bar_timestamps length {n}"
            )
        entry_epochs: np.ndarray = np.fromiter(
            (tr.entry_ts_utc.timestamp() for tr in trades),
            dtype=np.float64,
            count=len(trades),
        )
        entry_indices_arr = np.asarray(
            np.searchsorted(sorted_bar_ts, entry_epochs, side="right"),
            dtype=np.int64,
        )
        entry_indices = [int(x) - 1 for x in entry_indices_arr.tolist()]
        for i, tr in enumerate(trades):
            entry_idx = max(entry_indices[i], 0)
            exit_idx = exit_indices[i]
            open_end = min(exit_idx, n)
            if entry_idx < open_end and tr.entry_price > 0.0:
                unrealized = (
                    tr.size
                    * (prices[entry_idx:open_end] - tr.entry_price)
                    / tr.entry_price
                )
                equity[entry_idx:open_end] += unrealized
            if exit_idx < n:
                equity[exit_idx:] += tr.pnl_net
        return equity
    for i, tr in enumerate(trades):
        idx = exit_indices[i]
        if idx >= n:
            continue
        equity[idx:] += tr.pnl_net
    return equity


def compute_sharpe(
    bar_pnl: np.ndarray,
    bars_per_year: int = BARS_PER_YEAR_DEFAULT,
) -> float:
    """Annualized Sharpe on a per-bar P&L series.

    Zero-std → 0.0 (guarded, not NaN).
    """
    if bar_pnl.size == 0:
        return 0.0
    std = float(bar_pnl.std(ddof=0))
    if std == 0.0 or not math.isfinite(std):
        return 0.0
    mean = float(bar_pnl.mean())
    return math.sqrt(bars_per_year) * mean / std


def max_drawdown_from_equity(equity: np.ndarray) -> tuple[float, int]:
    """Return `(max_drawdown_frac, trough_index)`.

    `max_drawdown_frac = max(cummax(equity) - equity) / max(cummax(equity), eps)`.
    Zero equity throughout → 0.0. `trough_index` is the argmax of the drawdown
    series; ties broken toward the earliest bar.
    """
    if equity.size == 0:
        return 0.0, 0
    peaks = np.maximum.accumulate(equity)
    drawdowns = peaks - equity
    if drawdowns.max() == 0.0:
        return 0.0, 0
    trough = int(drawdowns.argmax())
    peak_at_trough = float(peaks[trough])
    if peak_at_trough <= 0.0:
        # Sprint 100 fix (review §4.3): all-loss curves have peak == 0.
        # Return the absolute-drawdown fraction against |equity_trough| so a
        # strategy that lost money throughout does not report zero drawdown.
        trough_equity = float(equity[trough])
        if trough_equity == 0.0:
            return 1.0, trough
        return float(abs(drawdowns[trough] / trough_equity)), trough
    return float(drawdowns[trough] / peak_at_trough), trough


def time_to_recovery_bars_from_equity(equity: np.ndarray, trough_index: int) -> int:
    """Bars from `trough_index` to the first bar where equity re-touches the pre-trough peak.

    Returns bars remaining if the peak is never re-touched (honest count, not a sentinel).
    """
    n = equity.size
    if n == 0 or trough_index >= n:
        return 0
    peak = float(np.maximum.accumulate(equity[: trough_index + 1])[-1])
    for i in range(trough_index + 1, n):
        if equity[i] >= peak:
            return i - trough_index
    return n - 1 - trough_index


def block_bootstrap_sharpe(
    bar_pnl: np.ndarray,
    *,
    n_blocks: int = N_BLOCKS_DEFAULT,
    n_resamples: int = N_RESAMPLES_DEFAULT,
    bars_per_block: int = BARS_PER_BLOCK_DEFAULT,
    bars_per_year: int = BARS_PER_YEAR_DEFAULT,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Return `(sharpe_se, positive_fraction)` via non-overlapping monthly blocks.

    Partitions `bar_pnl` into contiguous non-overlapping blocks of length
    `bars_per_block`; drops any tail shorter than one block. Each of the
    `n_resamples` iterations picks `n_blocks` block indices with replacement,
    concatenates, and computes Sharpe. Deterministic given `rng`.

    `bar_pnl` shorter than `bars_per_block` → returns `(0.0, 0.0)`. `rng` is
    the caller's `numpy.random.Generator`; test callers pass a seeded rng.
    """
    if rng is None:
        rng = np.random.default_rng(42)
    if bar_pnl.size < bars_per_block:
        return 0.0, 0.0
    n_available = bar_pnl.size // bars_per_block
    if n_available == 0:
        return 0.0, 0.0
    blocks = bar_pnl[: n_available * bars_per_block].reshape(n_available, bars_per_block)
    # Sprint 102 (review §3.2): vectorized single-pass form. Same rng seed,
    # same output as the prior Python-loop implementation; ~50x wall-clock at
    # n_resamples=10_000.
    idx = rng.integers(0, n_available, size=(n_resamples, n_blocks))
    resamples = blocks[idx].reshape(n_resamples, n_blocks * bars_per_block)
    means = resamples.mean(axis=1)
    stds = resamples.std(axis=1, ddof=0)
    scale = math.sqrt(bars_per_year)
    sharpes = np.where(stds > 0.0, scale * means / np.where(stds > 0.0, stds, 1.0), 0.0)
    se = float(sharpes.std(ddof=0))
    positive_fraction = float((sharpes > 0.0).mean())
    return se, positive_fraction


def compute_sim_metrics(
    trades: tuple[Trade, ...],
    bar_timestamps_utc: tuple[datetime, ...],
    *,
    prices: np.ndarray | None = None,
    bars_per_year: int = BARS_PER_YEAR_DEFAULT,
    n_resamples: int = N_RESAMPLES_DEFAULT,
    n_blocks: int = N_BLOCKS_DEFAULT,
    bars_per_block: int = BARS_PER_BLOCK_DEFAULT,
    rng_seed: int = 42,
) -> SimMetrics:
    """Compute the full metrics block from a trade ledger + bar timestamp series.

    Empty ledger or empty bar series → zero-valued SimMetrics; the walker
    emits zeros through `SIM_RUN_COMPLETED` honestly instead of raising.
    """
    n_bars = len(bar_timestamps_utc)
    n_trades = len(trades)
    if n_bars == 0 or n_trades == 0:
        return SimMetrics(
            sharpe_point=0.0,
            sharpe_se=0.0,
            block_bootstrap_positive_fraction=0.0,
            max_drawdown=0.0,
            time_to_recovery_bars=0,
            hit_rate=0.0,
            n_bars=n_bars,
            n_trades=n_trades,
        )
    equity = build_equity_curve(trades, bar_timestamps_utc, prices=prices)
    bar_pnl = np.diff(equity, prepend=0.0)
    sharpe_point = compute_sharpe(bar_pnl, bars_per_year)
    rng = np.random.default_rng(rng_seed)
    sharpe_se, positive_fraction = block_bootstrap_sharpe(
        bar_pnl,
        n_blocks=n_blocks,
        n_resamples=n_resamples,
        bars_per_block=bars_per_block,
        bars_per_year=bars_per_year,
        rng=rng,
    )
    max_dd, trough = max_drawdown_from_equity(equity)
    ttr = time_to_recovery_bars_from_equity(equity, trough)
    hits = sum(1 for tr in trades if tr.pnl_net > 0.0)
    hit_rate = hits / n_trades
    return SimMetrics(
        sharpe_point=sharpe_point,
        sharpe_se=sharpe_se,
        block_bootstrap_positive_fraction=positive_fraction,
        max_drawdown=max_dd,
        time_to_recovery_bars=ttr,
        hit_rate=hit_rate,
        n_bars=n_bars,
        n_trades=n_trades,
    )


__all__ = [
    "BARS_PER_BLOCK_DEFAULT",
    "BARS_PER_YEAR_DEFAULT",
    "N_BLOCKS_DEFAULT",
    "N_RESAMPLES_DEFAULT",
    "SimMetrics",
    "block_bootstrap_sharpe",
    "build_equity_curve",
    "compute_sharpe",
    "compute_sim_metrics",
    "max_drawdown_from_equity",
    "time_to_recovery_bars_from_equity",
]
