"""Probability-forecast metrics: nll, ece, brier, rps, dir_acc, top1, top3.

Every function takes `probs: Tensor (N, V)` and `targets: Tensor (N,)`
where V = vocab_size (n_buckets). Returns a scalar float. No emit --
callers compose the results into `METRIC_COMPUTED` payloads.

- nll: mean negative log-likelihood of the target bucket
- ece: expected calibration error over K equal-width probability bins
- brier: mean squared error of one-hot targets vs predicted probs
- rps: ranked probability score -- sum over |CDF(pred) - CDF(target)|^2 / (V-1)
- dir_acc: sign(argmax >= V/2) == sign(target >= V/2)
- top1: argmax(probs) == target
- top3: target in top-3 argmax
- bucket_frequency_drift: max_absolute_deviation + outer_bucket_ratio
  between two normalized bucket histograms
"""

from dataclasses import dataclass

import torch
from torch import Tensor


@dataclass(slots=True, frozen=True, kw_only=True)
class MetricSet:
    nll: float
    ece: float
    brier: float
    rps: float
    dir_acc: float
    top1: float
    top3: float
    n_examples: int


def compute_nll(probs: Tensor, targets: Tensor) -> float:
    """Mean negative log likelihood of the target bucket. probs are strictly-positive rows."""
    if probs.shape[0] == 0:
        return 0.0
    eps = 1e-12
    picked = probs.gather(1, targets.unsqueeze(1)).squeeze(1).clamp_min(eps)
    return float((-picked.log()).mean().item())


def compute_top_k(probs: Tensor, targets: Tensor, k: int) -> float:
    if probs.shape[0] == 0:
        return 0.0
    topk = probs.topk(k, dim=-1).indices  # (N, k)
    hit = (topk == targets.unsqueeze(-1)).any(dim=-1)
    return float(hit.float().mean().item())


def compute_dir_acc(probs: Tensor, targets: Tensor, vocab_size: int) -> float:
    """Directional accuracy: bucket_id >= vocab_size // 2 → 'up'; else 'down'."""
    if probs.shape[0] == 0:
        return 0.0
    preds = probs.argmax(dim=-1)
    threshold = vocab_size // 2
    pred_up = preds >= threshold
    tgt_up = targets >= threshold
    return float((pred_up == tgt_up).float().mean().item())


def compute_brier(probs: Tensor, targets: Tensor) -> float:
    """Mean squared error of one-hot(targets) vs probs."""
    if probs.shape[0] == 0:
        return 0.0
    one_hot = torch.zeros_like(probs)
    one_hot.scatter_(1, targets.unsqueeze(1), 1.0)
    return float(((probs - one_hot) ** 2).sum(dim=-1).mean().item())


def compute_rps(probs: Tensor, targets: Tensor) -> float:
    """Ranked probability score: mean_j (CDF(pred, j) - CDF(target, j))^2 / (V-1).

    Averaged across N examples. Lower is better.
    """
    if probs.shape[0] == 0:
        return 0.0
    _n, v = probs.shape
    if v <= 1:
        return 0.0
    one_hot = torch.zeros_like(probs)
    one_hot.scatter_(1, targets.unsqueeze(1), 1.0)
    cdf_pred = probs.cumsum(dim=-1)
    cdf_target = one_hot.cumsum(dim=-1)
    diff_sq = (cdf_pred - cdf_target) ** 2
    per_example = diff_sq.sum(dim=-1) / (v - 1)
    return float(per_example.mean().item())


def compute_ece(probs: Tensor, targets: Tensor, n_bins: int = 15) -> float:
    """Expected calibration error over `n_bins` equal-width confidence bins.

    Uses top-1 confidence as the calibration signal, matching Guo et al. 2017.
    """
    if probs.shape[0] == 0:
        return 0.0
    confidences, preds = probs.max(dim=-1)  # (N,)
    correct = (preds == targets).float()  # (N,)
    n = confidences.shape[0]
    edges = torch.linspace(0.0, 1.0, n_bins + 1, dtype=probs.dtype, device=probs.device)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        # Include the upper edge in the last bin so probability 1.0 is not dropped.
        in_bin = (confidences >= lo) & (confidences < hi if i < n_bins - 1 else confidences <= hi)
        n_in = int(in_bin.sum().item())
        if n_in == 0:
            continue
        bin_conf = float(confidences[in_bin].mean().item())
        bin_acc = float(correct[in_bin].mean().item())
        ece += (n_in / n) * abs(bin_conf - bin_acc)
    return float(ece)


def compute_metric_set(probs: Tensor, targets: Tensor, vocab_size: int) -> MetricSet:
    """Compute all seven metrics on a (probs, targets) pair. n_examples reports the row count."""
    return MetricSet(
        nll=compute_nll(probs, targets),
        ece=compute_ece(probs, targets),
        brier=compute_brier(probs, targets),
        rps=compute_rps(probs, targets),
        dir_acc=compute_dir_acc(probs, targets, vocab_size),
        top1=compute_top_k(probs, targets, k=1),
        top3=compute_top_k(probs, targets, k=3),
        n_examples=int(probs.shape[0]),
    )


def compute_bucket_frequency_drift(
    train_bucket_ids: list[int],
    val_bucket_ids: list[int],
    vocab_size: int,
) -> tuple[list[float], list[float], float, float]:
    """Return (train_freq, val_freq, max_absolute_deviation, outer_bucket_ratio).

    `outer_bucket_ratio` = (val_freq[0] + val_freq[-1]) / (train_freq[0] + train_freq[-1]).
    Diagnostic for tail-shape drift: values > 1 mean val tails are heavier than train's.
    Ratio is 0.0 if the train tails sum to zero.
    """
    train_counts = [0] * vocab_size
    for b in train_bucket_ids:
        if 0 <= b < vocab_size:
            train_counts[b] += 1
    val_counts = [0] * vocab_size
    for b in val_bucket_ids:
        if 0 <= b < vocab_size:
            val_counts[b] += 1
    train_total = sum(train_counts) or 1
    val_total = sum(val_counts) or 1
    train_freq = [c / train_total for c in train_counts]
    val_freq = [c / val_total for c in val_counts]
    max_dev = max(abs(a - b) for a, b in zip(train_freq, val_freq, strict=True))
    train_tails = train_freq[0] + train_freq[-1]
    val_tails = val_freq[0] + val_freq[-1]
    outer_ratio = val_tails / train_tails if train_tails > 0 else 0.0
    return train_freq, val_freq, float(max_dev), float(outer_ratio)
