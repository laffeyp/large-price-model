"""Strictly-causal feature computation over aligned bars.

Every feature at time T is a function of `close` values at grid times
`<= T`. Rolling windows use Polars' `rolling_*` with a fixed backward
window; no forward-looking references. The alignment invariant (§4.3)
plus causal features (§6) are what let the training loop treat every
grid row as an independent training sample without leakage.

Failure modes surface as `FEATURE_COMPUTATION_FAILED` incidents with
enum reasons `{insufficient_history, divide_by_zero, nan_input,
downstream_error}`. Rows in the output parquet carry NaN when a feature
could not be computed for that (channel, feature, timestamp); the
downstream tokenizer's missing-mask flips true for those cells per
tech-arch §7. No fill values — the vocabulary refuses lies (Sprint 023
retraction).
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import polars as pl

from price_space_llm.signals import StrictSignalEmitter

# The four v1 features per tech-arch §6.
# `log_return`: log(close_t / close_{t-1}); requires 1 prior close.
# `rolling_mean_20`, `rolling_std_20`: 20-bar backward windows over log_return.
# `rolling_z_score_20`: (log_return - rolling_mean_20) / rolling_std_20.
ROLLING_WINDOW = 20
FEATURE_SPECS: tuple[str, ...] = (
    "log_return",
    "rolling_mean_20",
    "rolling_std_20",
    "rolling_z_score_20",
)


class FeatureResult(TypedDict):
    run_id: str
    total_rows: int
    n_features_emitted: int
    n_failures: int
    elapsed_seconds: float
    output_path: str


def _channel_close_columns(aligned: pl.DataFrame) -> dict[str, tuple[str, str]]:
    """Return {`channel__symbol`: (`close_col`, `channel_name`)} for every close column."""
    result: dict[str, tuple[str, str]] = {}
    for col in aligned.columns:
        if col.endswith("__close"):
            key = col.removesuffix("__close")
            channel_name = key.split("__", 1)[0]
            result[key] = (col, channel_name)
    return result


def compute_features(
    aligned: pl.DataFrame,
    emitter: StrictSignalEmitter,
) -> tuple[pl.DataFrame, int]:
    """Compute the four v1 features per channel, returning (wide DataFrame, n_failures).

    Emits `FEATURE_COMPUTED` per (channel, feature, timestamp) with a non-null value,
    `FEATURE_COMPUTATION_FAILED` per (channel, feature, timestamp) with a null value.
    """
    channel_columns = _channel_close_columns(aligned)
    if not channel_columns:
        raise ValueError("aligned DataFrame has no __close columns")

    out = aligned.select(["grid_ts"])
    n_failures = 0

    for key, (close_col, channel_name) in channel_columns.items():
        log_ret_col = f"{key}__log_return"
        rmean_col = f"{key}__rolling_mean_20"
        rstd_col = f"{key}__rolling_std_20"
        rz_col = f"{key}__rolling_z_score_20"

        with_lr = aligned.with_columns(
            [
                (pl.col(close_col) / pl.col(close_col).shift(1)).log().alias(log_ret_col),
            ]
        )
        with_rolling = with_lr.with_columns(
            [
                pl.col(log_ret_col).rolling_mean(window_size=ROLLING_WINDOW).alias(rmean_col),
                pl.col(log_ret_col).rolling_std(window_size=ROLLING_WINDOW).alias(rstd_col),
            ]
        )
        with_z = with_rolling.with_columns(
            [
                (
                    pl.when(pl.col(rstd_col) == 0)
                    .then(None)
                    .otherwise((pl.col(log_ret_col) - pl.col(rmean_col)) / pl.col(rstd_col))
                ).alias(rz_col),
            ]
        )
        out = out.hstack(with_z.select([log_ret_col, rmean_col, rstd_col, rz_col]))

        grid_ts_values = aligned["grid_ts"].to_list()
        for feature_name in FEATURE_SPECS:
            col_name = f"{key}__{feature_name}"
            values = with_z[col_name].to_list()
            for ts, val in zip(grid_ts_values, values, strict=True):
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    reason = _classify_failure(feature_name, close_col, with_z, grid_ts_values, ts)
                    emitter.emit(
                        "FEATURE_COMPUTATION_FAILED",
                        timestamp=ts.isoformat(),
                        channel=channel_name,
                        feature_name=feature_name,
                        reason=reason,
                    )
                    n_failures += 1
                else:
                    emitter.emit(
                        "FEATURE_COMPUTED",
                        timestamp=ts.isoformat(),
                        channel=channel_name,
                        feature_name=feature_name,
                    )

    return out, n_failures


def _classify_failure(
    feature_name: str,
    close_col: str,
    df: pl.DataFrame,
    grid_ts_values: list[datetime],
    ts: datetime,
) -> str:
    """Pick a `FEATURE_COMPUTATION_FAILED.reason` for a null feature value at `ts`.

    Heuristic: rolling features on early rows fail from insufficient_history;
    log_return on the very first row fails from insufficient_history; other
    nulls with a null `close` at that row fail from nan_input; anything else
    is downstream_error.
    """
    row_idx = grid_ts_values.index(ts)
    close_val = df[close_col].to_list()[row_idx]
    if close_val is None:
        return "nan_input"
    if feature_name == "log_return" and row_idx == 0:
        return "insufficient_history"
    if feature_name.startswith("rolling_") and row_idx < ROLLING_WINDOW:
        return "insufficient_history"
    if feature_name == "rolling_z_score_20":
        rstd_col = close_col.replace("__close", "__rolling_std_20")
        if rstd_col in df.columns:
            rstd_val = df[rstd_col].to_list()[row_idx]
            if rstd_val == 0:
                return "divide_by_zero"
    return "downstream_error"


def run_feature_pipeline(
    aligned_path: Path,
    output_path: Path,
    emitter: StrictSignalEmitter,
    run_id: str,
) -> FeatureResult:
    """End-to-end feature computation: read aligned parquet, compute, write features parquet."""
    aligned = pl.read_parquet(aligned_path)
    t0 = time.monotonic()
    features, n_failures = compute_features(aligned, emitter)
    elapsed = time.monotonic() - t0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    features.write_parquet(output_path)

    channel_columns = _channel_close_columns(aligned)
    n_features_emitted = aligned.height * len(FEATURE_SPECS) * len(channel_columns) - n_failures

    return FeatureResult(
        run_id=run_id,
        total_rows=features.height,
        n_features_emitted=n_features_emitted,
        n_failures=n_failures,
        elapsed_seconds=elapsed,
        output_path=str(output_path),
    )
