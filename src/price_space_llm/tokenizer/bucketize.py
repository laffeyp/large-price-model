"""Quantile-based return bucketizer and token emitter.

Fits `n_buckets` quantile boundaries on the target symbol's
`{target}__log_return` values within the training range, produces a
strictly-increasing edge vector of length `n_buckets - 1`, and
persists it to `artifacts/tokenizer/bucket_stats.json` with a sha256.

Assignment: for each grid row, `bucket_id = np.searchsorted(edges, x)`.
Values outside all edges are clamped to `0` or `n_buckets - 1`.
"""

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import polars as pl
import torch

from price_space_llm.signals import StrictSignalEmitter

if TYPE_CHECKING:
    from price_space_llm.normalizer import FrozenNormalizer


@dataclass(slots=True, frozen=True, kw_only=True)
class BucketRow:
    """Per-bucket statistics per spec § 7.1.

    `lower` / `upper` are the bin bounds (half-open `(lower, upper]` for interior
    buckets). `None` at either end means the open tail: `lower is None` for
    bucket 0 (leftmost), `upper is None` for bucket n-1 (rightmost).
    `train_mean` + `train_median` compute over training rows falling in this
    bucket; NaN when the bucket is empty. `train_frequency` = count / total.
    """

    lower: float | None
    upper: float | None
    train_mean: float
    train_median: float
    train_frequency: float


@dataclass(slots=True, frozen=True, kw_only=True)
class BucketStats:
    n_buckets: Literal[16, 32, 64]
    target_symbol: str
    training_range_start: str  # YYYY-MM-DD
    training_range_end: str  # YYYY-MM-DD
    train_partition_row_count: int
    edges: tuple[float, ...]  # len == n_buckets - 1, strictly increasing
    # Sprint 056: per-bucket statistics per spec § 7.1. Length == n_buckets.
    per_bucket: tuple[BucketRow, ...] = ()


@dataclass(slots=True, frozen=True, kw_only=True)
class TokenizerResult:
    run_id: str
    total_rows: int
    n_tokens_emitted: int
    n_buckets: int
    channel_count: int
    d_model: int
    bucket_stats_path: str
    tokens_output_path: str
    elapsed_seconds: float


def _log_return_col(target_symbol: str) -> str:
    return f"target__{target_symbol}__log_return"


def fit_bucketizer(
    features: pl.DataFrame,
    *,
    target_symbol: str,
    n_buckets: Literal[16, 32, 64],
    training_range_start: date,
    training_range_end: date,
    emitter: StrictSignalEmitter,
) -> BucketStats:
    """Fit quantile edges on the training-range non-null log_returns of the target symbol.

    Emits `BUCKETIZER_FITTED` at close. Does not write anything to disk;
    `write_bucket_stats` is the persistence boundary.
    """
    col = _log_return_col(target_symbol)
    if col not in features.columns:
        raise ValueError(f"features parquet has no column {col!r}")

    train_frame = features.filter(
        (pl.col("grid_ts").dt.date() >= training_range_start)
        & (pl.col("grid_ts").dt.date() <= training_range_end)
        & pl.col(col).is_not_null()
    )
    train_partition_row_count = train_frame.height
    if train_partition_row_count < n_buckets:
        raise ValueError(
            f"training partition has {train_partition_row_count} non-null rows; "
            f"need at least {n_buckets} to fit {n_buckets} quantile bins"
        )

    # Quantile edges at (1/n, 2/n, ..., (n-1)/n).
    quantiles = [i / n_buckets for i in range(1, n_buckets)]
    values = sorted(train_frame[col].to_list())
    edges = tuple(_quantile(values, q) for q in quantiles)

    # Enforce strict monotonicity: identical adjacent quantiles get an epsilon
    # nudge so `np.searchsorted` returns distinct buckets. Zero-return-dominant
    # months (holidays, low-vol days) can produce ties at 0.0.
    edges = _dedupe_strictly_increasing(edges)

    # Sprint 056: per-bucket statistics per spec § 7.1. Bin the training values
    # against final edges and compute mean/median/frequency per bucket.
    per_bucket = _compute_per_bucket_stats(
        values=train_frame[col].to_list(),
        edges=edges,
        n_buckets=n_buckets,
    )

    stats = BucketStats(
        n_buckets=n_buckets,
        target_symbol=target_symbol,
        training_range_start=training_range_start.isoformat(),
        training_range_end=training_range_end.isoformat(),
        train_partition_row_count=train_partition_row_count,
        edges=edges,
        per_bucket=per_bucket,
    )

    emitter.emit(
        "BUCKETIZER_FITTED",
        n_buckets=str(n_buckets),
        training_range_start=training_range_start.isoformat(),
        training_range_end=training_range_end.isoformat(),
        train_partition_row_count=train_partition_row_count,
    )
    return stats


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation quantile over a sorted list. q in [0, 1]."""
    if not sorted_values:
        raise ValueError("cannot compute quantile of empty list")
    if q <= 0:
        return sorted_values[0]
    if q >= 1:
        return sorted_values[-1]
    idx = q * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _compute_per_bucket_stats(
    *, values: list[float], edges: tuple[float, ...], n_buckets: int
) -> tuple[BucketRow, ...]:
    """Bin `values` against `edges` and return one BucketRow per bucket.

    Sprint 056. bucket 0 = (None, edges[0]]; interior i = (edges[i-1], edges[i]];
    bucket n-1 = (edges[n-2], None]. train_mean + train_median are NaN when a
    bucket is empty. train_frequency sums to 1.0 across all buckets modulo float
    rounding.
    """
    import statistics
    from math import nan

    per_bucket_values: list[list[float]] = [[] for _ in range(n_buckets)]
    for v in values:
        if v is None:
            continue
        # Match assign_buckets: bucket_id = count of edges strictly less than v.
        lo, hi = 0, len(edges)
        while lo < hi:
            mid = (lo + hi) // 2
            if edges[mid] <= v:
                lo = mid + 1
            else:
                hi = mid
        per_bucket_values[lo].append(float(v))

    total = sum(len(bucket) for bucket in per_bucket_values)
    rows: list[BucketRow] = []
    for i in range(n_buckets):
        lower = None if i == 0 else edges[i - 1]
        upper = None if i == n_buckets - 1 else edges[i]
        bucket_vals = per_bucket_values[i]
        if bucket_vals:
            mean = sum(bucket_vals) / len(bucket_vals)
            median = statistics.median(bucket_vals)
            frequency = len(bucket_vals) / total if total > 0 else 0.0
        else:
            mean = nan
            median = nan
            frequency = 0.0
        rows.append(
            BucketRow(
                lower=lower,
                upper=upper,
                train_mean=mean,
                train_median=median,
                train_frequency=frequency,
            )
        )
    return tuple(rows)


def _dedupe_strictly_increasing(edges: tuple[float, ...]) -> tuple[float, ...]:
    """Nudge each tied edge up by a relative epsilon so the sequence is strictly increasing."""
    out: list[float] = []
    prev = float("-inf")
    for e in edges:
        candidate = e if e > prev else prev + max(abs(prev), 1.0) * 1e-12
        out.append(candidate)
        prev = candidate
    return tuple(out)


def write_bucket_stats(
    stats: BucketStats,
    output_path: Path,
    emitter: StrictSignalEmitter,
    run_id: str = "unknown",
) -> str:
    """Persist stats via versioned-artifact write; emit BUCKET_STATS_WRITTEN with sha256.

    `output_path` is the LOGICAL base name (e.g. `artifacts/tokenizer/bucket_stats.json`).
    The actual file lands at `bucket_stats.{run_id}.json` with a `bucket_stats.latest.json`
    symlink pointing at the newest write. The emit's `path` field records the
    versioned file so downstream consumers name the specific run they read.

    Sprint 056: per_bucket serializes as JSON array. NaN train_mean / train_median
    (empty bucket) write as `null` for strict-JSON portability; `None` bounds
    (open tails) write as `null` too.
    """
    from price_space_llm.artifacts import write_versioned

    doc = asdict(stats)
    # Sprint 056: sanitize non-JSON-safe floats in per_bucket.
    doc["per_bucket"] = [_row_to_jsonable(row) for row in doc.get("per_bucket", ())]
    body = json.dumps(doc, sort_keys=True, allow_nan=False).encode("utf-8")
    result = write_versioned(output_path, run_id, body)
    emitter.emit(
        "BUCKET_STATS_WRITTEN",
        n_buckets=str(stats.n_buckets),
        path=str(result.versioned_path),
        sha256=result.sha256,
    )
    return result.sha256


def _row_to_jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Convert one BucketRow-shaped dict into strict-JSON-safe form.

    NaN train_mean / train_median write as `null`; None bounds already are null.
    Reader restores NaN for empty buckets.
    """
    import math

    out = dict(row)
    for field in ("train_mean", "train_median"):
        v = out.get(field)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out[field] = None
    return out


def _row_from_jsonable(doc: dict[str, Any]) -> BucketRow:
    """Inverse of `_row_to_jsonable`. Null train_mean / train_median restore to NaN."""
    from math import nan

    train_mean_raw = doc.get("train_mean")
    train_median_raw = doc.get("train_median")
    train_mean = float(train_mean_raw) if train_mean_raw is not None else nan
    train_median = float(train_median_raw) if train_median_raw is not None else nan
    return BucketRow(
        lower=doc.get("lower"),
        upper=doc.get("upper"),
        train_mean=train_mean,
        train_median=train_median,
        train_frequency=float(doc.get("train_frequency", 0.0)),
    )


def load_bucket_stats(path: Path) -> BucketStats:
    doc = json.loads(path.read_text(encoding="utf-8"))
    per_bucket_raw = doc.get("per_bucket", [])
    per_bucket = tuple(_row_from_jsonable(r) for r in per_bucket_raw)
    return BucketStats(
        n_buckets=doc["n_buckets"],
        target_symbol=doc["target_symbol"],
        training_range_start=doc["training_range_start"],
        training_range_end=doc["training_range_end"],
        train_partition_row_count=doc["train_partition_row_count"],
        edges=tuple(doc["edges"]),
        per_bucket=per_bucket,
    )


def assign_buckets(values: list[float | None], edges: tuple[float, ...]) -> list[int | None]:
    """Return one bucket_id per input value; None inputs preserve to None."""
    out: list[int | None] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        # Binary search into edges. `bucket_id` = number of edges strictly less than v.
        lo, hi = 0, len(edges)
        while lo < hi:
            mid = (lo + hi) // 2
            if edges[mid] <= v:
                lo = mid + 1
            else:
                hi = mid
        out.append(lo)
    return out


def _channel_columns(features: pl.DataFrame) -> list[str]:
    """Return sorted `channel__symbol` keys inferred from the log_return columns."""
    keys: set[str] = set()
    for col in features.columns:
        if col.endswith("__log_return"):
            keys.add(col.removesuffix("__log_return"))
    return sorted(keys)


def run_tokenizer(
    features_path: Path,
    output_dir: Path,
    bucket_stats_path: Path,
    *,
    target_symbol: str,
    n_buckets: Literal[16, 32, 64],
    d_model: int,
    training_range_start: date,
    training_range_end: date,
    emitter: StrictSignalEmitter,
    run_id: str,
) -> TokenizerResult:
    """End-to-end tokenizer pass. Reads features, fits, writes stats, assigns, emits tokens."""
    features = pl.read_parquet(features_path)
    t0 = time.monotonic()

    stats = fit_bucketizer(
        features,
        target_symbol=target_symbol,
        n_buckets=n_buckets,
        training_range_start=training_range_start,
        training_range_end=training_range_end,
        emitter=emitter,
    )
    write_bucket_stats(stats, bucket_stats_path, emitter, run_id=run_id)

    target_col = _log_return_col(target_symbol)
    train_mask = (features["grid_ts"].dt.date() >= training_range_start) & (
        features["grid_ts"].dt.date() <= training_range_end
    )
    train_frame = features.filter(train_mask)
    values = train_frame[target_col].to_list()
    bucket_ids = assign_buckets(values, stats.edges)

    train_ts = train_frame["grid_ts"].to_list()
    for ts, bid, val in zip(train_ts, bucket_ids, values, strict=True):
        if bid is None or val is None:
            continue
        emitter.emit(
            "BUCKET_ASSIGNED",
            timestamp=_ensure_iso(ts),
            bucket_id=str(bid),
            vol_normalized_return=float(val),
        )

    # MARKET_STATE_TOKEN_EMITTED per grid bar (regardless of null features).
    channel_keys = _channel_columns(features)
    channel_count = len(channel_keys)
    all_ts = features["grid_ts"].to_list()
    for ts in all_ts:
        emitter.emit(
            "MARKET_STATE_TOKEN_EMITTED",
            timestamp=_ensure_iso(ts),
            d_model=d_model,
            channel_count=channel_count,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    tokens_path = output_dir / f"{run_id}.parquet"
    tokens_frame = pl.DataFrame(
        {
            "grid_ts": train_ts,
            f"target__{target_symbol}__bucket_id": bucket_ids,
        }
    )
    tokens_frame.write_parquet(tokens_path)

    n_tokens = sum(1 for b in bucket_ids if b is not None)
    elapsed = time.monotonic() - t0

    return TokenizerResult(
        run_id=run_id,
        total_rows=features.height,
        n_tokens_emitted=n_tokens,
        n_buckets=n_buckets,
        channel_count=channel_count,
        d_model=d_model,
        bucket_stats_path=str(bucket_stats_path),
        tokens_output_path=str(tokens_path),
        elapsed_seconds=elapsed,
    )


def _ensure_iso(ts: Any) -> str:
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


# Sprint 052: extended tokenized artifact per tech-arch §5 --------------------


def _per_channel_feature_columns(features: pl.DataFrame) -> dict[str, list[str]]:
    """Return {channel__symbol: sorted list of feature columns} for every channel.

    Excludes the `known_at` column; every other `{key}__*` column is a feature.
    """
    keys = _channel_columns(features)
    out: dict[str, list[str]] = {}
    for key in keys:
        prefix = f"{key}__"
        cols = sorted(
            c for c in features.columns if c.startswith(prefix) and c != f"{key}__known_at"
        )
        out[key] = cols
    return out


def run_tokenizer_pt(
    features_path: Path,
    output_dir: Path,
    stats: BucketStats,
    *,
    target_symbol: str,
    emitter: StrictSignalEmitter,
    run_id: str,
    channel_coverage_path: Path | None = None,
    config_hash: str = "unknown",
    data_hash: str = "unknown",
    git_sha_value: str = "unknown",
    normalizer: "FrozenNormalizer | None" = None,
) -> Path:
    """Write the extended tokenized artifact to `data/tokenized/{run_id}.pt`.

    Per tech-arch §5: `torch.save`d dict with per-channel `Tensor[T, F_c]`,
    `targets`, `vol`, `timestamps`, `is_overnight_gap`, `mask`, `channel_names`,
    `meta`.

    Sprint 052 conventions:
    - Feature nulls become 0.0 in the tensor; row-level `mask` flips False.
    - `targets[t] = -100` (PyTorch CE ignore_index) where the target's
      log_return is null; otherwise the assigned bucket_id from `stats.edges`.
    - `vol[t]` reads `target__{sym}__realized_vol_30`; falls back to zeros if
      Sprint 049 hasn't run against this features parquet yet.
    - `timestamps[t]` is UTC Unix seconds from `grid_ts`.
    - `is_overnight_gap` is `None` until Sprint 055 (session flags) lands.
    - `mask[t]` is True iff every feature column across every channel is
      non-null at row `t`.
    """
    del emitter  # Sprint 052 defers a dedicated emit; sha256 sidecar carries
    # the auditability. Sprint 053 or a v0.5 vocab bump may add
    # TOKENIZED_ARTIFACT_WRITTEN if needed.

    features = pl.read_parquet(features_path)
    n_rows = features.height
    per_channel = _per_channel_feature_columns(features)

    features_dict: dict[str, torch.Tensor] = {}
    for key, cols in per_channel.items():
        if not cols:
            continue
        # Stack columns into [n_rows, F_c] with nulls -> 0.0. Polars returns
        # non-writable numpy arrays for zero-copy views; PyTorch refuses those,
        # so copy into a fresh writable array before wrapping.
        arr: np.ndarray = np.zeros((n_rows, len(cols)), dtype=np.float32)
        for j, col in enumerate(cols):
            vals = features[col].fill_null(0.0).to_numpy()
            arr[:, j] = vals.astype(np.float32, copy=True)
        features_dict[key] = torch.from_numpy(arr)

    # Targets: bucket_id sequence for the target symbol.
    target_col = _log_return_col(target_symbol)
    if target_col not in features.columns:
        raise ValueError(f"features parquet has no target column {target_col!r}")
    log_ret = features[target_col].to_list()
    bucket_ids = assign_buckets(log_ret, stats.edges)
    targets_np: np.ndarray = np.full(n_rows, -100, dtype=np.int64)
    for i, bid in enumerate(bucket_ids):
        if bid is not None:
            targets_np[i] = bid
    targets_t = torch.from_numpy(targets_np)

    # Vol: target's realized_vol_30; zeros if the column is absent.
    vol_col = f"target__{target_symbol}__realized_vol_30"
    vol_arr: np.ndarray
    if vol_col in features.columns:
        vol_arr = features[vol_col].fill_null(0.0).to_numpy().astype(np.float32, copy=True)
    else:
        vol_arr = np.zeros(n_rows, dtype=np.float32)
    vol_t = torch.from_numpy(vol_arr)

    # Timestamps: UTC Unix seconds.
    ts_arr: np.ndarray = features["grid_ts"].dt.epoch("s").to_numpy().astype(np.int64, copy=True)
    timestamps_t = torch.from_numpy(ts_arr)

    # Mask: True iff every feature column is non-null at that row.
    all_feature_cols = [c for cols in per_channel.values() for c in cols]
    mask_arr: np.ndarray
    if all_feature_cols:
        mask_series = features.select(
            pl.all_horizontal([pl.col(c).is_not_null() for c in all_feature_cols]).alias("__mask")
        )["__mask"]
        mask_arr = mask_series.to_numpy().astype(bool, copy=True)
    else:
        mask_arr = np.zeros(n_rows, dtype=bool)
    mask_t = torch.from_numpy(mask_arr)

    # Meta.
    channel_coverage_sha = "unknown"
    if channel_coverage_path is not None and channel_coverage_path.exists():
        channel_coverage_sha = hashlib.sha256(channel_coverage_path.read_bytes()).hexdigest()
    meta = {
        "run_id": run_id,
        "config_hash": config_hash,
        "git_sha": git_sha_value,
        "data_hash": data_hash,
        "target_symbol": target_symbol,
        "channel_coverage_sha": channel_coverage_sha,
    }

    # Sprint 062: session flags computed from grid_ts. Adds `session__flags`
    # channel (Tensor[T, 4]) + populates the `is_overnight_gap` field the
    # Sprint 052 payload previously left as None.
    from price_space_llm.tokenizer.session import compute_session_features

    session_feats, is_overnight_gap = compute_session_features(timestamps_t)
    features_dict["session__flags"] = session_feats

    # Sprint 054: apply frozen normalizer (if supplied) before persisting.
    if normalizer is not None:
        from price_space_llm.normalizer import apply_frozen_normalizer

        features_dict = apply_frozen_normalizer(features_dict, normalizer)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_id}.pt"
    torch.save(
        {
            "features": features_dict,
            "targets": targets_t,
            "vol": vol_t,
            "timestamps": timestamps_t,
            "is_overnight_gap": is_overnight_gap,  # Sprint 062: populated from grid_ts
            "mask": mask_t,
            "channel_names": tuple(sorted(features_dict.keys())),
            "meta": meta,
        },
        output_path,
    )
    return output_path
