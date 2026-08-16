"""Normalization-drift diagnostic (Sprint 055).

Product-spec-v4.md line 251:
    "Track it as a failure mode. Fix: plot the normalized-feature distribution
     on the holdout against training."

`measure_normalizer_drift` applies the frozen normalizer to a training and a
holdout `TokenizedArtifact`, compares per-(channel, feature_index) distributions
via a two-sample Kolmogorov-Smirnov statistic + asymptotic p-value, and emits
one `NORMALIZER_DRIFT_MEASURED` per feature. If matplotlib is importable, one
PNG per feature lands in `plot_dir`.

The KS statistic is hand-rolled (no scipy dep): sort both samples, sweep the
empirical CDF, take the max absolute gap. The p-value uses the Kolmogorov
distribution's asymptotic form for two samples, valid for n>=100. Every real
channel in the pipeline exceeds 10k rows so the asymptotic is accurate.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

from price_space_llm.model.dataset import TokenizedArtifact
from price_space_llm.normalizer.frozen import (
    FrozenNormalizer,
    apply_frozen_normalizer,
)
from price_space_llm.signals import StrictSignalEmitter


def two_sample_ks(sample_a: np.ndarray, sample_b: np.ndarray) -> tuple[float, float]:
    """Kolmogorov-Smirnov two-sample statistic + asymptotic p-value.

    Returns `(D, p)`. `D` is the max absolute difference between the two
    empirical CDFs. `p` uses the asymptotic Kolmogorov distribution:
    `p = 2 * Σ_{k=1..∞} (-1)^{k-1} exp(-2 k^2 λ^2)` where
    `λ = (√(n₁ n₂ / (n₁ + n₂))) D`. Truncated at k=100 (converges fast).

    Constant samples with identical values yield `D=0.0`, `p=1.0`.
    """
    a = np.sort(np.asarray(sample_a, dtype=np.float64))
    b = np.sort(np.asarray(sample_b, dtype=np.float64))
    n_a = a.size
    n_b = b.size
    if n_a == 0 or n_b == 0:
        return 0.0, 1.0

    # Merge indices to compute empirical CDF difference at every observed value.
    all_values = np.concatenate([a, b])
    all_values.sort()
    cdf_a = np.searchsorted(a, all_values, side="right") / n_a
    cdf_b = np.searchsorted(b, all_values, side="right") / n_b
    d = float(np.max(np.abs(cdf_a - cdf_b)))

    if d == 0.0:
        return 0.0, 1.0

    n_eff = math.sqrt(n_a * n_b / (n_a + n_b))
    lam = n_eff * d
    p_sum = 0.0
    for k in range(1, 101):
        term = ((-1) ** (k - 1)) * math.exp(-2.0 * (k * lam) ** 2)
        p_sum += term
        if abs(term) < 1e-15:
            break
    p = max(0.0, min(1.0, 2.0 * p_sum))
    return d, p


def _write_drift_plot(
    plot_path: Path,
    train_values: np.ndarray,
    holdout_values: np.ndarray,
    channel: str,
    feature_index: int,
    ks_statistic: float,
    p_value: float,
) -> bool:
    """Best-effort PNG write. Returns True on success, False if matplotlib is missing."""
    try:
        import matplotlib  # type: ignore[import-not-found]

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore[import-not-found]
    except ImportError:
        return False

    plot_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 4))
    bins = 50
    ax.hist(train_values, bins=bins, alpha=0.5, label="train", color="tab:blue", density=True)
    ax.hist(holdout_values, bins=bins, alpha=0.5, label="holdout", color="tab:orange", density=True)
    ax.set_xlabel("normalized value")
    ax.set_ylabel("density")
    ax.set_title(f"{channel} feat[{feature_index}]  KS={ks_statistic:.4f}  p={p_value:.4g}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_path, dpi=90)
    plt.close(fig)
    return True


def measure_normalizer_drift(
    *,
    train_artifact: TokenizedArtifact,
    holdout_artifact: TokenizedArtifact,
    normalizer: FrozenNormalizer,
    emitter: StrictSignalEmitter,
    run_id: str,
    plot_dir: Path | None = None,
) -> int:
    """Compare training-vs-holdout normalized-feature distributions per feature.

    Emits one `NORMALIZER_DRIFT_MEASURED` per (channel, feature_index) with
    train_mean/std, holdout_mean/std, KS statistic, and p-value. If `plot_dir`
    is set and matplotlib is importable, writes one PNG per feature.

    Returns the number of features measured (== `normalizer.feature_count` if
    both artifacts carry the same channel set).
    """
    train_channels = set(train_artifact.features.keys())
    holdout_channels = set(holdout_artifact.features.keys())
    if train_channels != holdout_channels:
        mismatch_train = sorted(train_channels - holdout_channels)
        mismatch_holdout = sorted(holdout_channels - train_channels)
        raise ValueError(
            "train and holdout artifacts have different channel sets. "
            f"Only in train: {mismatch_train}. Only in holdout: {mismatch_holdout}."
        )

    train_norm = apply_frozen_normalizer(train_artifact.features, normalizer)
    holdout_norm = apply_frozen_normalizer(holdout_artifact.features, normalizer)

    train_valid = train_artifact.targets != -100
    holdout_valid = holdout_artifact.targets != -100

    n_measured = 0
    for channel in sorted(train_norm.keys()):
        tensor_train = train_norm[channel][train_valid]  # (n_train, F_c)
        tensor_holdout = holdout_norm[channel][holdout_valid]  # (n_holdout, F_c)
        f_c = tensor_train.shape[1]
        for feature_index in range(f_c):
            train_col = tensor_train[:, feature_index].detach().cpu().numpy()
            holdout_col = tensor_holdout[:, feature_index].detach().cpu().numpy()
            train_mean = float(train_col.mean()) if train_col.size else 0.0
            train_std = float(train_col.std(ddof=0)) if train_col.size else 0.0
            holdout_mean = float(holdout_col.mean()) if holdout_col.size else 0.0
            holdout_std = float(holdout_col.std(ddof=0)) if holdout_col.size else 0.0
            ks_stat, p_val = two_sample_ks(train_col, holdout_col)
            emitter.emit(
                "NORMALIZER_DRIFT_MEASURED",
                run_id=run_id,
                channel=channel,
                feature_index=feature_index,
                train_mean=train_mean,
                train_std=train_std,
                holdout_mean=holdout_mean,
                holdout_std=holdout_std,
                ks_statistic=ks_stat,
                p_value=p_val,
            )
            if plot_dir is not None:
                ok = _write_drift_plot(
                    plot_dir / f"{channel}__f{feature_index}.png",
                    train_col,
                    holdout_col,
                    channel,
                    feature_index,
                    ks_stat,
                    p_val,
                )
                if not ok:
                    print(
                        "measure_normalizer_drift: matplotlib not importable; skipping PNG writes",
                        file=sys.stderr,
                    )
                    plot_dir = None  # stop trying
            n_measured += 1
    return n_measured


__all__ = [
    "measure_normalizer_drift",
    "two_sample_ks",
]
