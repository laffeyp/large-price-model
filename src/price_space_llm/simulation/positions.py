"""Sprint 096: position state + trades + PnL math.

Named approximations (documented on the sprint card):

- **Fill price = close at fill bar.** The spec says "entries and exits print
  at the next bar's open." The tokenizer ships close-derived log_returns via
  `raw_targets`, not opens. On a 15-min bar the open-vs-close gap is small
  relative to the microstructure the strategy trades; the approximation is
  named in the sprint card and applied uniformly to entries and exits so it
  cancels in the round-trip P&L.
- **Single `spread_cost_frac` = round-trip cost fraction.** Per-position cost
  `= spread_cost_frac * |size|`. Equivalent under symmetric assumptions to
  half-spread charged on each leg.
- **`slippage_frac * |size|` linearizes `kappa * size^2`.** Sprint 099's
  kappa sensitivity plot revisits the quadratic form.

PnL math:

    pnl_gross     = size * (exit_price / entry_price - 1)   (signed size)
    cost_spread   = spread_cost_frac * |size|
    cost_slippage = slippage_frac    * |size|
    pnl_net       = pnl_gross - cost_spread - cost_slippage

`size` is signed: long positions carry positive size, short positions negative.
Long profit when price rises, short profit when price falls — the signed-size
form encodes both without a direction branch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import torch

if TYPE_CHECKING:
    from price_space_llm.signals import StrictSignalEmitter


@dataclass(slots=True, frozen=True, kw_only=True)
class Position:
    """Open position tracked by `run_simulation_with_trades`."""

    direction: str  # ∈ {"long", "short"}
    size: float  # signed
    entry_bar_ts_utc: datetime
    entry_price: float
    entry_bar_index: int


@dataclass(slots=True, frozen=True, kw_only=True)
class Trade:
    """One closed round-trip in the trade ledger.

    Sprint 100 adds `entry_price` and `exit_price`. Mark-to-market equity
    (`metrics.build_equity_curve(prices=...)`) reconstructs the per-bar
    unrealized P&L from `signed_size * (price[t] - entry_price) / entry_price`
    over the hold interval, then transitions to `pnl_net` at exit. The walker
    knows both prices at construction; keeping them on `Trade` avoids a
    second downstream lookup.
    """

    trade_id: str
    entry_ts_utc: datetime
    exit_ts_utc: datetime
    direction: str
    size: float
    entry_price: float
    exit_price: float
    pnl_gross: float
    pnl_net: float
    cost_spread: float
    cost_slippage: float
    hold_duration_bars: int


def compute_pnl(
    size: float,
    entry_price: float,
    exit_price: float,
    spread_cost_frac: float,
    slippage_frac: float,
) -> tuple[float, float, float, float]:
    """Return `(pnl_gross, pnl_net, cost_spread, cost_slippage)`.

    `size` is signed. Direction is implicit in sign: long = +size, short = -size.
    The `size * (exit/entry - 1)` form encodes both directions in one line.
    Raises `ValueError` on non-positive `entry_price` (would divide by zero).
    """
    if entry_price <= 0.0 or not math.isfinite(entry_price):
        raise ValueError(
            f"compute_pnl: entry_price must be positive and finite; got {entry_price}"
        )
    if exit_price <= 0.0 or not math.isfinite(exit_price):
        raise ValueError(
            f"compute_pnl: exit_price must be positive and finite; got {exit_price}"
        )
    pnl_gross = size * (exit_price / entry_price - 1.0)
    cost_spread = spread_cost_frac * abs(size)
    cost_slippage = slippage_frac * abs(size)
    pnl_net = pnl_gross - cost_spread - cost_slippage
    return pnl_gross, pnl_net, cost_spread, cost_slippage


def derive_prices_from_log_returns(raw_targets: torch.Tensor) -> torch.Tensor:
    """Cumulative anchored prices from log_returns; `p_t = exp(sum_{k<=t} safe_r_k)`.

    NaN log-returns are treated as zero (price unchanged bar-over-bar) via the
    `torch.where(isfinite, r, 0)` mask before cumsum. Sprint 103 vectorized
    rewrite (review §3.1) -- semantically identical to the Sprint 096 loop:
    a NaN return means zero log-return means the price stays flat between
    bars, which is what the loop's skip-multiply produces.
    """
    if raw_targets.ndim != 1:
        raise ValueError(
            f"raw_targets must be 1-D; got shape {tuple(raw_targets.shape)}"
        )
    n = raw_targets.shape[0]
    if n == 0:
        return torch.zeros(0, dtype=torch.float64)
    safe = torch.where(
        torch.isfinite(raw_targets),
        raw_targets,
        torch.zeros_like(raw_targets),
    )
    log_prices = torch.cumsum(safe.to(torch.float64), dim=0)
    return torch.exp(log_prices)


def emit_position_opened(
    emitter: StrictSignalEmitter,
    *,
    decision_bar_ts_iso: str,
    fill_bar_ts_iso: str,
    direction: str,
    size: float,
    entry_price: float,
    target_symbol: str,
) -> None:
    """Emit POSITION_OPENED. Extracted from `skeleton.py` in Sprint 104."""
    emitter.emit(
        "POSITION_OPENED",
        decision_bar_ts=decision_bar_ts_iso,
        fill_bar_ts=fill_bar_ts_iso,
        direction=direction,
        size=size,
        entry_price=entry_price,
        target_symbol=target_symbol,
    )


def emit_position_closed(
    emitter: StrictSignalEmitter,
    *,
    decision_bar_ts_iso: str,
    fill_bar_ts_iso: str,
    direction: str,
    size: float,
    exit_price: float,
    pnl_gross: float,
    pnl_net: float,
    hold_duration_bars: int,
    close_kind: str,
) -> None:
    """Emit POSITION_CLOSED. Extracted from `skeleton.py` in Sprint 104."""
    emitter.emit(
        "POSITION_CLOSED",
        decision_bar_ts=decision_bar_ts_iso,
        fill_bar_ts=fill_bar_ts_iso,
        direction=direction,
        size=size,
        exit_price=exit_price,
        pnl_gross=pnl_gross,
        pnl_net=pnl_net,
        hold_duration_bars=hold_duration_bars,
        close_kind=close_kind,
    )


def emit_trade_ledgered(emitter: StrictSignalEmitter, trade: Trade) -> None:
    """Emit TRADE_LEDGERED. Extracted from `skeleton.py` in Sprint 104."""
    emitter.emit(
        "TRADE_LEDGERED",
        trade_id=trade.trade_id,
        entry_ts=trade.entry_ts_utc.isoformat(),
        exit_ts=trade.exit_ts_utc.isoformat(),
        direction=trade.direction,
        size=trade.size,
        pnl_net=trade.pnl_net,
        cost_spread=trade.cost_spread,
        cost_slippage=trade.cost_slippage,
    )


def close_position_and_record(
    *,
    position: Position,
    fill_bar_index: int,
    fill_bar_ts: datetime,
    fill_price: float,
    decision_bar_ts_iso: str,
    spread_cost_frac: float,
    slippage_frac: float,
    close_kind: str,
    emitter: StrictSignalEmitter,
    trades: list[Trade],
) -> None:
    """Close an open position, ledger the trade, emit POSITION_CLOSED + TRADE_LEDGERED.

    Extracted from `skeleton.py` in Sprint 104. The walker calls this on any
    direction change and once more at end-of-range if a position is still open.
    """
    pnl_gross, pnl_net, cost_spread, cost_slippage = compute_pnl(
        size=position.size,
        entry_price=position.entry_price,
        exit_price=fill_price,
        spread_cost_frac=spread_cost_frac,
        slippage_frac=slippage_frac,
    )
    hold_duration = fill_bar_index - position.entry_bar_index
    emit_position_closed(
        emitter,
        decision_bar_ts_iso=decision_bar_ts_iso,
        fill_bar_ts_iso=fill_bar_ts.isoformat(),
        direction=position.direction,
        size=position.size,
        exit_price=fill_price,
        pnl_gross=pnl_gross,
        pnl_net=pnl_net,
        hold_duration_bars=hold_duration,
        close_kind=close_kind,
    )
    trade = Trade(
        trade_id=f"trade-{len(trades):06d}",
        entry_ts_utc=position.entry_bar_ts_utc,
        exit_ts_utc=fill_bar_ts,
        direction=position.direction,
        size=position.size,
        entry_price=position.entry_price,
        exit_price=fill_price,
        pnl_gross=pnl_gross,
        pnl_net=pnl_net,
        cost_spread=cost_spread,
        cost_slippage=cost_slippage,
        hold_duration_bars=hold_duration,
    )
    trades.append(trade)
    emit_trade_ledgered(emitter, trade)


__all__ = [
    "Position",
    "Trade",
    "close_position_and_record",
    "compute_pnl",
    "derive_prices_from_log_returns",
    "emit_position_closed",
    "emit_position_opened",
    "emit_trade_ledgered",
]
