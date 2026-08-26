"""Sprint 093: derive the four `PREDICTION_EMITTED` payload scalars from a probability distribution.

Consumers give a `[V]` softmax distribution + per-bucket raw-return mean
(Sprint 056 `BucketRow.train_mean`, fit on raw log-returns by
`tokenizer.bucketize.fit_bucketizer`) + a scalar realized_vol for the bar.

    expected_return    = sum_i p_i * train_mean_i          # raw log-return
    expected_vn_return = expected_return / realized_vol    # vol-normalized
    p_up               = sum_{i >= V//2} p_i
    entropy            = -sum_i p_i * log(p_i)    (clamped to avoid log(0))
    sharpness          = 1 - entropy / log(V)

Scale note: `compute_edge` subtracts `(spread + slippage) / realized_vol`
and expects `expected_vn_return` on the same vol-normalized scale.
Pre-fix (Sprint 093 through Sprint 116) `expected_vn_return` was set to
`sum_i p_i * train_mean_i` — a raw log-return, not vol-normalized. On
SPY 15-min bars the two scales differed by ~1000x and cost terms
dominated the edge regardless of the model's prediction.

Every value is finite for a well-formed distribution. NaN train_means (from
empty training buckets, Sprint 056) contribute zero to the sums (treated as
`p_i * 0 = 0`) because a bucket with no training mass carries no defensible
expected value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch


@dataclass(slots=True, frozen=True, kw_only=True)
class PredictionScalars:
    """The four floats + entropy required by `PREDICTION_EMITTED.typed_payload`.

    `expected_vn_return` and `expected_return` are separate because the emit
    payload names both; `expected_return` = `expected_vn_return * realized_vol`.
    """

    expected_vn_return: float
    expected_return: float
    p_up: float
    sharpness: float
    entropy: float


def _entropy(probs: torch.Tensor) -> float:
    """Shannon entropy in nats. Uses `torch.special.xlogy(p, p)` semantics with a clamp."""
    eps = 1e-12
    clamped = probs.clamp_min(eps)
    return float((-(probs * clamped.log()).sum()).item())


def derive_prediction_scalars(
    probs: torch.Tensor,
    bucket_train_means: torch.Tensor,
    realized_vol: float,
) -> PredictionScalars:
    """Compute the five prediction scalars from a per-bar softmax + bucket stats.

    `probs` shape `[V]` floats summing to ~1. `bucket_train_means` shape `[V]`
    floats; NaN entries (from empty training buckets per Sprint 056) contribute
    zero to the expected-value sum. `realized_vol` is a scalar float; the
    tokenizer's `vol` field carries `target__{sym}__realized_vol_30` per bar.
    """
    if probs.ndim != 1:
        raise ValueError(f"probs must be 1-D; got shape {tuple(probs.shape)}")
    if bucket_train_means.ndim != 1:
        raise ValueError(
            f"bucket_train_means must be 1-D; got shape {tuple(bucket_train_means.shape)}"
        )
    if probs.shape[0] != bucket_train_means.shape[0]:
        raise ValueError(
            f"probs len {probs.shape[0]} != bucket_train_means len {bucket_train_means.shape[0]}"
        )
    # Sprint 100 fix (review §6.4): NaN probs poison every downstream sum
    # (expected_return, p_up, entropy) silently. Fail loud instead.
    if bool(torch.isnan(probs).any()):
        raise ValueError(
            "derive_prediction_scalars: probs contain NaN; upstream model "
            "produced NaN logits. Check the walker's per-bar forward pass."
        )
    v = int(probs.shape[0])

    means_safe = torch.where(
        torch.isnan(bucket_train_means),
        torch.zeros_like(bucket_train_means),
        bucket_train_means,
    )
    if realized_vol <= 0.0 or not math.isfinite(realized_vol):
        raise ValueError(
            f"derive_prediction_scalars: realized_vol must be positive and finite; "
            f"got {realized_vol}"
        )
    expected_return = float((probs * means_safe).sum().item())
    expected_vn_return = expected_return / realized_vol
    p_up = float(probs[v // 2 :].sum().item())
    entropy = _entropy(probs)
    log_v = math.log(v)
    sharpness = 0.0 if log_v <= 0 else 1.0 - entropy / log_v
    return PredictionScalars(
        expected_vn_return=expected_vn_return,
        expected_return=expected_return,
        p_up=p_up,
        sharpness=sharpness,
        entropy=entropy,
    )


__all__ = [
    "PredictionScalars",
    "derive_prediction_scalars",
]
