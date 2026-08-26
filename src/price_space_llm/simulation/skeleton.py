"""Simulator skeleton — bar walker + emit-surface scaffold.

Sprint 092 (Phase F, roadmap 074). No model, no prediction, no cost model,
no positions, no trades. The skeleton exists so Sprint 093 has a fixed
surface to add PREDICTION_EMITTED + DECISION_MADE + POSITION_OPENED against.

Every summary field on `SIM_RUN_COMPLETED` lands as 0 or 0.0 because the
skeleton runs zero trades; that is honest arithmetic, not fabrication. The
`SimResult.notes` field carries the string `"skeleton"` so a trace reader
distinguishes a skeleton run from a real Sprint 093+ run at a glance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import polars as pl
import torch
from torch.nn import functional as F

from price_space_llm.model.dataset import TokenizedArtifact
from price_space_llm.model.transformer import MarketStateTransformer
from price_space_llm.signals import StrictSignalEmitter
from price_space_llm.simulation.metrics import SimMetrics, compute_sim_metrics
from price_space_llm.simulation.policy import (
    PolicyConfig,
    compute_edge,
    decide,
    variance_vn,
)
from price_space_llm.simulation.positions import (
    Position,
    Trade,
    close_position_and_record,
    derive_prices_from_log_returns,
    emit_position_opened,
)
from price_space_llm.simulation.prediction import derive_prediction_scalars
from price_space_llm.tokenizer.bucketize import BucketStats


@dataclass(slots=True, frozen=True, kw_only=True)
class SimResult:
    """Return type of `run_simulation_skeleton`.

    Sprint 092 populates `n_bars_processed`; every other field is 0 or 0.0
    for a skeleton run. Sprint 093+ replaces zeros with real numbers.
    """

    n_bars_processed: int
    n_trades: int = 0
    sharpe_point: float = 0.0
    sharpe_se: float = 0.0
    block_bootstrap_positive_fraction: float = 0.0
    max_drawdown: float = 0.0
    time_to_recovery_bars: int = 0
    implied_capacity_usd: float = 0.0
    # Sprint 095 (from review 074-094 § 7.1): bars skipped because
    # `artifact.vol[t] <= 0` (undefined vol-normalization). Counting the skip
    # in-band so a downstream reader parsing BAR_PROCESSED counts vs
    # date-range width does not silently miss the delta.
    n_bars_skipped_undefined_vol: int = 0
    # Sprint 100 (from review §4.5): bars skipped because the next-bar fill
    # price is NaN (upstream raw_target NaN cascaded through prices).
    n_bars_skipped_nan_price: int = 0
    # Sprint 096: trade ledger and total P&L. `n_trades` overrides the parent
    # field with the derived count when a caller populates `trades`.
    trades: tuple[Trade, ...] = ()
    pnl_total: float = 0.0
    # Sprint 097: full metrics block. None on skeleton runs; populated on
    # run_simulation_with_trades.
    metrics: SimMetrics | None = None
    # Sprint 103 (review §2.68): typed discriminator, was `str`.
    notes: Literal[
        "skeleton", "predictions-only", "predictions+policy", "predictions+policy+trades"
    ] = field(default="skeleton")


def run_simulation_skeleton(
    aligned_parquet_path: Path,
    *,
    split: str,
    date_range_start: date,
    date_range_end: date,
    emitter: StrictSignalEmitter,
    run_id: str,
    checkpoint_step: int,
    checkpoint_run_id: str,
    cost_calibration_run_id: str,
) -> SimResult:
    """Walk the aligned parquet in grid order over `[date_range_start, date_range_end]`.

    Emits `SIM_RUN_STARTED` once at entry, `BAR_PROCESSED` per bar, and
    `SIM_RUN_COMPLETED` once at exit. Every summary metric on the completion
    emit lands at 0 (or 0.0) because the skeleton runs zero trades — Sprint 093
    replaces the zeros with real numbers once the decision policy exists.
    """
    emitter.emit(
        "SIM_RUN_STARTED",
        run_id=run_id,
        split=split,
        date_range_start=date_range_start.isoformat(),
        date_range_end=date_range_end.isoformat(),
        checkpoint_step=checkpoint_step,
        checkpoint_run_id=checkpoint_run_id,
        cost_calibration_run_id=cost_calibration_run_id,
    )

    df = pl.read_parquet(aligned_parquet_path)
    if "grid_ts" not in df.columns:
        raise ValueError(
            f"aligned parquet at {aligned_parquet_path} has no 'grid_ts' column"
        )
    filtered = df.filter(
        (pl.col("grid_ts").dt.date() >= date_range_start)
        & (pl.col("grid_ts").dt.date() <= date_range_end)
    ).sort("grid_ts")

    n_bars = 0
    for row in filtered.iter_rows(named=True):
        ts = row["grid_ts"]
        emitter.emit(
            "BAR_PROCESSED",
            timestamp=ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        )
        n_bars += 1

    emitter.emit(
        "SIM_RUN_COMPLETED",
        run_id=run_id,
        n_trades=0,
        sharpe_point=0.0,
        sharpe_se=0.0,
        block_bootstrap_positive_fraction=0.0,
        max_drawdown=0.0,
        time_to_recovery_bars=0,
        implied_capacity_at_this_size_usd=0.0,
    )

    return SimResult(n_bars_processed=n_bars, notes="skeleton")


def run_simulation_with_trades(
    artifact: TokenizedArtifact,
    model: MarketStateTransformer,
    bucket_stats: BucketStats,
    policy: PolicyConfig,
    *,
    target_symbol: str,
    emitter: StrictSignalEmitter,
    run_id: str,
    checkpoint_step: int,
    checkpoint_run_id: str,
    cost_calibration_run_id: str,
    split: str = "train",
    date_range_start: date = date(2015, 1, 1),
    date_range_end: date = date(2022, 12, 31),
) -> SimResult:
    """Sprint 096: walker + prediction + decision + position state machine + trades.

    Extends Sprint 094's `run_simulation_with_policy` with three new emit
    surfaces: `POSITION_OPENED` on a decision that opens (flat -> {long, short})
    or flips ({long, short} -> {short, long}); `POSITION_CLOSED` on a decision
    that closes ({long, short} -> flat, or the flip's close half); `TRADE_LEDGERED`
    per closed position.

    Fill mechanics: DECISION_MADE at bar `t` -> position event at fill bar
    `t+1`. If the walker exhausts its range with an open position, the walker
    force-closes at the last bar with `close_kind="sim_range_end"`.

    Named approximations (sprint card § 1): fill price = close at fill bar
    (spec's "next bar's open" not available from the tokenizer); single
    `spread_cost_frac` = round-trip cost fraction; slippage linearized as
    `slippage_frac * |size|`.

    Requires `artifact.raw_targets` (Sprint 088); raises `ValueError` if None.
    """
    if artifact.raw_targets is None:
        raise ValueError(
            "run_simulation_with_trades requires artifact.raw_targets; regenerate "
            "the .pt via scripts/bucketize.py --format pt (Sprint 088+ stamps it)."
        )
    model.eval()
    context_len = model.config.context_len
    n_rows = artifact.targets.shape[0]
    if n_rows < context_len + 2:
        # +2 because a decision at bar t requires bar t+1 as fill.
        raise ValueError(
            f"artifact has {n_rows} rows; need at least {context_len + 2} to walk one trade"
        )
    per_bucket = bucket_stats.per_bucket
    if not per_bucket:
        raise ValueError(
            "bucket_stats.per_bucket is empty; regenerate via Sprint 056 tokenizer"
        )
    train_means = bucket_stats.train_means_tensor
    # Prices from cumulative log_returns.
    prices = derive_prices_from_log_returns(artifact.raw_targets)

    emitter.emit(
        "SIM_RUN_STARTED",
        run_id=run_id,
        split=split,
        date_range_start=date_range_start.isoformat(),
        date_range_end=date_range_end.isoformat(),
        checkpoint_step=checkpoint_step,
        checkpoint_run_id=checkpoint_run_id,
        cost_calibration_run_id=cost_calibration_run_id,
    )

    n_bars = 0
    n_skipped = 0
    n_skipped_nan_price = 0
    current_direction = "flat"
    current_position: Position | None = None
    trades: list[Trade] = []
    device = next(model.parameters()).device
    with torch.no_grad():
        for t in range(context_len, n_rows - 1):
            realized_vol = float(artifact.vol[t].item())
            if realized_vol <= 0.0:
                n_skipped += 1
                continue
            feats_window: dict[str, torch.Tensor] = {}
            for key, tensor in artifact.features.items():
                feats_window[key] = tensor[t - context_len : t].unsqueeze(0).to(device)
            logits = model(feats_window)
            probs = F.softmax(logits[0, -1, :], dim=-1).detach().cpu()
            scalars = derive_prediction_scalars(probs, train_means, realized_vol)
            var_vn = variance_vn(probs, train_means)
            edge = compute_edge(
                scalars.expected_vn_return,
                var_vn,
                realized_vol,
                policy.spread_cost_frac,
                policy.slippage_frac,
                policy.lambda_risk,
            )
            decision_bar_ts = datetime.fromtimestamp(
                int(artifact.timestamps[t].item()), tz=UTC
            )
            fill_bar_ts = datetime.fromtimestamp(
                int(artifact.timestamps[t + 1].item()), tz=UTC
            )
            decision_bar_ts_iso = decision_bar_ts.isoformat()
            fill_bar_ts_iso = fill_bar_ts.isoformat()
            fill_price = float(prices[t + 1].item())
            # Sprint 100 fix (review §4.5): a NaN fill price would inject a
            # phantom exit into the ledger. Skip and count.
            if not (fill_price > 0.0):
                n_skipped_nan_price += 1
                continue

            emitter.emit(
                "PREDICTION_EMITTED",
                timestamp=decision_bar_ts_iso,
                expected_vn_return=scalars.expected_vn_return,
                expected_return=scalars.expected_return,
                p_up=scalars.p_up,
                sharpness=scalars.sharpness,
                entropy=scalars.entropy,
            )
            emitter.emit("BAR_PROCESSED", timestamp=decision_bar_ts_iso)
            decision, hysteresis_dropped = decide(current_direction, edge, policy)
            emitter.emit(
                "DECISION_MADE",
                timestamp=decision_bar_ts_iso,
                direction=decision.direction,
                size=decision.size,
                edge=decision.edge,
                threshold=decision.threshold,
                reason=decision.reason,
                effective_threshold=decision.effective_threshold,
            )
            if hysteresis_dropped:
                emitter.emit(
                    "SIGNAL_DROPPED",
                    timestamp=decision_bar_ts_iso,
                    dropped_reason="hysteresis_below_flip_threshold",
                )

            # Position state transitions on any change from `current_direction`.
            if decision.direction != current_direction:
                # Close existing position (if any) at fill price.
                if current_position is not None:
                    close_position_and_record(
                        position=current_position,
                        fill_bar_index=t + 1,
                        fill_bar_ts=fill_bar_ts,
                        fill_price=fill_price,
                        decision_bar_ts_iso=decision_bar_ts_iso,
                        spread_cost_frac=policy.spread_cost_frac,
                        slippage_frac=policy.slippage_frac,
                        close_kind="normal",
                        emitter=emitter,
                        trades=trades,
                    )
                    current_position = None
                # Open new position (unless flat).
                if decision.direction != "flat":
                    emit_position_opened(
                        emitter,
                        decision_bar_ts_iso=decision_bar_ts_iso,
                        fill_bar_ts_iso=fill_bar_ts_iso,
                        direction=decision.direction,
                        size=decision.size,
                        entry_price=fill_price,
                        target_symbol=target_symbol,
                    )
                    current_position = Position(
                        direction=decision.direction,
                        size=decision.size,
                        entry_bar_ts_utc=fill_bar_ts,
                        entry_price=fill_price,
                        entry_bar_index=t + 1,
                    )
                current_direction = decision.direction
            n_bars += 1

    # End-of-range flush: force-close any still-open position.
    if current_position is not None:
        last_index = n_rows - 1
        last_ts = datetime.fromtimestamp(
            int(artifact.timestamps[last_index].item()), tz=UTC
        )
        last_price = float(prices[last_index].item())
        close_position_and_record(
            position=current_position,
            fill_bar_index=last_index,
            fill_bar_ts=last_ts,
            fill_price=last_price,
            decision_bar_ts_iso=last_ts.isoformat(),
            spread_cost_frac=policy.spread_cost_frac,
            slippage_frac=policy.slippage_frac,
            close_kind="sim_range_end",
            emitter=emitter,
            trades=trades,
        )
        current_position = None

    pnl_total = float(sum(tr.pnl_net for tr in trades))

    # Sprint 097: bar-timestamp series for the metrics computation. Uses the
    # walker's processed bar indices [context_len, n_rows-2) — the same range
    # over which trades entered and exited. Metrics-side annualization
    # constant is bars_per_year = 6552 (15-min RTH); block bootstrap uses
    # 18 non-overlapping 546-bar monthly blocks and 10,000 resamples.
    processed_bar_timestamps = tuple(
        datetime.fromtimestamp(int(artifact.timestamps[t].item()), tz=UTC)
        for t in range(context_len, n_rows - 1)
    )
    # Sprint 100 (review §4.1): mark-to-market equity. Slice `prices` over
    # the same [context_len, n_rows-1) window as the timestamps so the two
    # arrays align 1:1. `prices` is a torch.Tensor of float64.
    prices_slice = prices[context_len : n_rows - 1].cpu().numpy()
    metrics = compute_sim_metrics(
        tuple(trades),
        processed_bar_timestamps,
        prices=prices_slice,
    )

    emitter.emit(
        "SIM_RUN_COMPLETED",
        run_id=run_id,
        n_trades=len(trades),
        sharpe_point=metrics.sharpe_point,
        sharpe_se=metrics.sharpe_se,
        block_bootstrap_positive_fraction=metrics.block_bootstrap_positive_fraction,
        max_drawdown=metrics.max_drawdown,
        time_to_recovery_bars=metrics.time_to_recovery_bars,
        implied_capacity_at_this_size_usd=0.0,  # Sprint 098 capacity sweep
    )
    return SimResult(
        n_bars_processed=n_bars,
        n_bars_skipped_undefined_vol=n_skipped,
        n_bars_skipped_nan_price=n_skipped_nan_price,
        n_trades=len(trades),
        trades=tuple(trades),
        pnl_total=pnl_total,
        metrics=metrics,
        notes="predictions+policy+trades",
    )


__all__ = [
    "SimResult",
    "run_simulation_skeleton",
    "run_simulation_with_trades",
]
