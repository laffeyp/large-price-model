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

# Sprint 069: spec § 6 line 306 — market_context symbols get three additional
# features (log_return already ships from the base pass). VXX carries the real
# VIX-ecosystem volume signal per Sprint 050 substitution; VIX index has
# volume=0 by construction, so its volume_z_100 lands as null via div-by-zero
# guard — honest per the earlier ratification.
CROSS_ASSET_FEATURE_SPECS: tuple[str, ...] = (
    "realized_vol_30",
    "volume_z_100",
    "bar_shape",
)

# Sprint 069: VIX-only extra features per spec § 6 line 306.
# vix_level = close (VIX is quoted in vol points).
# vix_change = close_t - close_{t-1} (CBOE convention: absolute vol-point delta).
VIX_FEATURE_SPECS: tuple[str, ...] = (
    "vix_level",
    "vix_change",
)

# Sprint 070: macro features per spec § 6.
# delta_since_last_release: close - close-at-previous-release, carried between releases.
# days_since_release: age_since_known_at (in bars) divided by BARS_PER_RTH_DAY.
# countdown_to_next: deferred (needs release-schedule integration; separate sprint).
MACRO_FEATURE_SPECS: tuple[str, ...] = (
    "delta_since_last_release",
    "days_since_release",
)
BARS_PER_RTH_DAY = 26  # 09:45..16:00 ET at 15-min = 26 bars per weekday.


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

        # Sprint 069: cross-asset features on market_context channels. Same
        # bar_shape / volume_z_100 / realized_vol_30 arithmetic as Sprint 049's
        # target block minus range_pct / dollar_volume / spread_proxy (target-only
        # per spec § 6).
        elif channel_name == "market_context":
            open_col = f"{key}__open"
            high_col = f"{key}__high"
            low_col = f"{key}__low"
            volume_col = f"{key}__volume"
            bar_shape_col = f"{key}__bar_shape"
            volume_z_col = f"{key}__volume_z_100"
            rvol_col = f"{key}__realized_vol_30"
            vol_mean_col = f"{key}__volume_roll_mean_100"
            vol_std_col = f"{key}__volume_roll_std_100"

            with_cross = with_z.with_columns(
                [
                    (
                        (pl.col(close_col) - pl.col(open_col))
                        / (pl.col(high_col) - pl.col(low_col) + BAR_SHAPE_EPS)
                    ).alias(bar_shape_col),
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
            with_cross = with_cross.with_columns(
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
            cross_out_cols = [rvol_col, volume_z_col, bar_shape_col]
            cross_feature_names = list(CROSS_ASSET_FEATURE_SPECS)

            # VIX-only: vix_level (= close) + vix_change (= close - close.shift(1)).
            symbol_name = key.split("__", 1)[1] if "__" in key else key
            if symbol_name == "VIX":
                vix_level_col = f"{key}__vix_level"
                vix_change_col = f"{key}__vix_change"
                with_cross = with_cross.with_columns(
                    [
                        pl.col(close_col).alias(vix_level_col),
                        (pl.col(close_col) - pl.col(close_col).shift(1)).alias(vix_change_col),
                    ]
                )
                cross_out_cols = [*cross_out_cols, vix_level_col, vix_change_col]
                cross_feature_names = cross_feature_names + list(VIX_FEATURE_SPECS)

            out = out.hstack(with_cross.select(cross_out_cols))
            feature_names = feature_names + cross_feature_names
            emit_frame = with_cross

        # Sprint 070: macro features. Reads close (release-day step function) +
        # age_since_known_at (bars since last observation, Sprint 042). Computes
        # release-day delta carried between releases, and age in RTH days.
        elif channel_name == "macro":
            delta_col = f"{key}__delta_since_last_release"
            days_col = f"{key}__days_since_release"
            age_col = f"age_since_known_at__{key}"

            diff_expr = pl.col(close_col) - pl.col(close_col).shift(1)
            fresh_expr = (
                pl.when(diff_expr != 0).then(diff_expr).otherwise(None)
            )
            with_macro = with_z.with_columns(
                [
                    fresh_expr.forward_fill().fill_null(0.0).alias(delta_col),
                ]
            )
            # days_since_release: age in bars / BARS_PER_RTH_DAY. When
            # age_since_known_at is absent (older aligned parquet), fall back to
            # zero + emit failure.
            if age_col in aligned.columns:
                with_macro = with_macro.with_columns(
                    [
                        (pl.col(age_col).cast(pl.Float32) / float(BARS_PER_RTH_DAY)).alias(
                            days_col
                        ),
                    ]
                )
            else:
                with_macro = with_macro.with_columns(
                    [pl.lit(None, dtype=pl.Float32).alias(days_col)]
                )
            out = out.hstack(with_macro.select([delta_col, days_col]))
            feature_names = feature_names + list(MACRO_FEATURE_SPECS)
            emit_frame = with_macro

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
    # Sprint 069: VIX-specific vix_change uses close - close.shift(1); row 0 null.
    if feature_name == "vix_change" and row_idx == 0:
        return "insufficient_history"
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

    # Sprint 049/069/070: per-channel feature counts.
    # target = FEATURE_SPECS + TARGET_FEATURE_SPECS.
    # market_context = FEATURE_SPECS + CROSS_ASSET_FEATURE_SPECS (+ VIX for symbol=VIX).
    # macro = FEATURE_SPECS + MACRO_FEATURE_SPECS.
    # others = FEATURE_SPECS only.
    def _per_channel_count(key: str, channel_name: str) -> int:
        base = len(FEATURE_SPECS)
        if channel_name == "target":
            return base + len(TARGET_FEATURE_SPECS)
        if channel_name == "market_context":
            symbol_name = key.split("__", 1)[1] if "__" in key else key
            vix_extra = len(VIX_FEATURE_SPECS) if symbol_name == "VIX" else 0
            return base + len(CROSS_ASSET_FEATURE_SPECS) + vix_extra
        if channel_name == "macro":
            return base + len(MACRO_FEATURE_SPECS)
        return base

    per_channel_feature_counts = sum(
        _per_channel_count(key, channel_name) for key, (_, channel_name) in channel_columns.items()
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
