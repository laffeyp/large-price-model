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

import math
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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

# Sprint 049: six spec §6 target features (tech-arch line 302). Apply only to
# the target channel (channel_name == "target"). Cross-asset variants land in
# Sprint 050.
TARGET_FEATURE_SPECS: tuple[str, ...] = (
    "bar_shape",
    "range_pct",
    "volume_z_100",
    "dollar_volume",
    "spread_proxy",
    "realized_vol_30",
)
VOLUME_ROLLING_WINDOW = 100
REALIZED_VOL_WINDOW = 30
BAR_SHAPE_EPS = 1e-12


@dataclass(slots=True, frozen=True, kw_only=True)
class FeatureResult:
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
        base_cols = [log_ret_col, rmean_col, rstd_col, rz_col]
        out = out.hstack(with_z.select(base_cols))

        feature_names = list(FEATURE_SPECS)
        emit_frame = with_z

        # Sprint 049: six spec §6 target features layer on the target channel
        # only. Consumes OHLCV columns Sprint 042 wrote plus the log_return the
        # base pass just computed.
        if channel_name == "target":
            open_col = f"{key}__open"
            high_col = f"{key}__high"
            low_col = f"{key}__low"
            volume_col = f"{key}__volume"
            bar_shape_col = f"{key}__bar_shape"
            range_pct_col = f"{key}__range_pct"
            volume_z_col = f"{key}__volume_z_100"
            dollar_vol_col = f"{key}__dollar_volume"
            spread_col = f"{key}__spread_proxy"
            rvol_col = f"{key}__realized_vol_30"
            vol_mean_col = f"{key}__volume_roll_mean_100"
            vol_std_col = f"{key}__volume_roll_std_100"

            with_target = with_z.with_columns(
                [
                    (
                        (pl.col(close_col) - pl.col(open_col))
                        / (pl.col(high_col) - pl.col(low_col) + BAR_SHAPE_EPS)
                    ).alias(bar_shape_col),
                    ((pl.col(high_col) - pl.col(low_col)) / pl.col(close_col).shift(1)).alias(
                        range_pct_col
                    ),
                    (pl.col(close_col) * pl.col(volume_col)).alias(dollar_vol_col),
                    (
                        (2.0 * (pl.col(high_col) - pl.col(low_col)).abs())
                        / (pl.col(high_col) + pl.col(low_col))
                    ).alias(spread_col),
                    pl.col(volume_col)
                    .rolling_mean(window_size=VOLUME_ROLLING_WINDOW)
                    .alias(vol_mean_col),
                    pl.col(volume_col)
                    .rolling_std(window_size=VOLUME_ROLLING_WINDOW)
                    .alias(vol_std_col),
                    pl.col(log_ret_col)
                    .rolling_std(window_size=REALIZED_VOL_WINDOW)
                    .alias(rvol_col),
                ]
            )
            with_target = with_target.with_columns(
                [
                    (
                        pl.when(pl.col(vol_std_col) == 0)
                        .then(None)
                        .otherwise(
                            (pl.col(volume_col) - pl.col(vol_mean_col)) / pl.col(vol_std_col)
                        )
                    ).alias(volume_z_col),
                ]
            )
            target_out_cols = [
                bar_shape_col,
                range_pct_col,
                volume_z_col,
                dollar_vol_col,
                spread_col,
                rvol_col,
            ]
            out = out.hstack(with_target.select(target_out_cols))
            feature_names = feature_names + list(TARGET_FEATURE_SPECS)
            emit_frame = with_target

        grid_ts_values = aligned["grid_ts"].to_list()
        for feature_name in feature_names:
            col_name = f"{key}__{feature_name}"
            values = emit_frame[col_name].to_list()
            for ts, val in zip(grid_ts_values, values, strict=True):
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    reason = _classify_failure(
                        feature_name, close_col, emit_frame, grid_ts_values, ts
                    )
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
    # Sprint 049: target-feature failure classification.
    if feature_name == "range_pct" and row_idx == 0:
        return "insufficient_history"
    if feature_name == "volume_z_100":
        if row_idx < VOLUME_ROLLING_WINDOW:
            return "insufficient_history"
        vol_std_col = close_col.replace("__close", "__volume_roll_std_100")
        if vol_std_col in df.columns:
            v = df[vol_std_col].to_list()[row_idx]
            if v == 0:
                return "divide_by_zero"
    if feature_name == "realized_vol_30" and row_idx < REALIZED_VOL_WINDOW:
        return "insufficient_history"
    if feature_name == "bar_shape":
        high_col = close_col.replace("__close", "__high")
        low_col = close_col.replace("__close", "__low")
        if high_col in df.columns and low_col in df.columns:
            h = df[high_col].to_list()[row_idx]
            lo = df[low_col].to_list()[row_idx]
            if h is not None and lo is not None and h == lo:
                # eps floor kept the divisor non-zero and the numerator zero,
                # yielding value 0 (not null). If this feature is null and
                # high == low, the classification is nan_input on close/open.
                open_col = close_col.replace("__close", "__open")
                if open_col in df.columns:
                    op = df[open_col].to_list()[row_idx]
                    if op is None:
                        return "nan_input"
    if feature_name == "spread_proxy":
        high_col = close_col.replace("__close", "__high")
        low_col = close_col.replace("__close", "__low")
        if high_col in df.columns and low_col in df.columns:
            h = df[high_col].to_list()[row_idx]
            lo = df[low_col].to_list()[row_idx]
            if h is not None and lo is not None and (h + lo) == 0:
                return "divide_by_zero"
    if feature_name == "dollar_volume":
        volume_col = close_col.replace("__close", "__volume")
        if volume_col in df.columns:
            v = df[volume_col].to_list()[row_idx]
            if v is None:
                return "nan_input"
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
    # Sprint 049: target channel emits FEATURE_SPECS + TARGET_FEATURE_SPECS;
    # non-target channels emit FEATURE_SPECS only.
    per_channel_feature_counts = sum(
        len(FEATURE_SPECS) + (len(TARGET_FEATURE_SPECS) if channel_name == "target" else 0)
        for _, (_, channel_name) in channel_columns.items()
    )
    n_features_emitted = aligned.height * per_channel_feature_counts - n_failures

    return FeatureResult(
        run_id=run_id,
        total_rows=features.height,
        n_features_emitted=n_features_emitted,
        n_failures=n_failures,
        elapsed_seconds=elapsed,
        output_path=str(output_path),
    )
