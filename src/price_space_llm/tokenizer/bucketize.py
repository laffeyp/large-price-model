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
from typing import Any, Literal

import polars as pl

from price_space_llm.signals import StrictSignalEmitter


@dataclass(slots=True, frozen=True, kw_only=True)
class BucketStats:
    n_buckets: Literal[16, 32, 64]
    target_symbol: str
    training_range_start: str  # YYYY-MM-DD
    training_range_end: str  # YYYY-MM-DD
    train_partition_row_count: int
    edges: tuple[float, ...]  # len == n_buckets - 1, strictly increasing


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

    stats = BucketStats(
        n_buckets=n_buckets,
        target_symbol=target_symbol,
        training_range_start=training_range_start.isoformat(),
        training_range_end=training_range_end.isoformat(),
        train_partition_row_count=train_partition_row_count,
        edges=edges,
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
) -> str:
    """Persist stats as JSON; emit BUCKET_STATS_WRITTEN with sha256; return the sha256."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(asdict(stats), sort_keys=True)
    output_path.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    emitter.emit(
        "BUCKET_STATS_WRITTEN",
        n_buckets=str(stats.n_buckets),
        path=str(output_path),
        sha256=digest,
    )
    return digest


def load_bucket_stats(path: Path) -> BucketStats:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return BucketStats(
        n_buckets=doc["n_buckets"],
        target_symbol=doc["target_symbol"],
        training_range_start=doc["training_range_start"],
        training_range_end=doc["training_range_end"],
        train_partition_row_count=doc["train_partition_row_count"],
        edges=tuple(doc["edges"]),
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
    write_bucket_stats(stats, bucket_stats_path, emitter)

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
