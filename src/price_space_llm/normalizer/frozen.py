"""Frozen normalizer: per-(channel, feature) mean + std constants.

Product-spec § Feature normalization:
    "v1 uses an expanding-window causal z-score computed on the training
     partition only, then frozen. At inference and on validation and test,
     the frozen scaler is used as-is."

Sprint 054 interpretation (A): fit one mean + std per (channel, feature)
across the entire training partition (rows where target != -100), freeze
those constants, apply the same transform on train + val + test. Simpler
than per-bar expanding stats + Welford's, and matches the "then frozen"
downstream shape. Interpretation (B) per-bar expanding stats is a follow-up
if Sprint 055's drift diagnostic surfaces mismatch.

Constant columns (std == 0) pass through as zero via a 1e-8 divisor clamp;
no NaN poisoning of the model.
"""

import io
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import Tensor

from price_space_llm.artifacts import write_versioned
from price_space_llm.model.dataset import TokenizedArtifact
from price_space_llm.signals import StrictSignalEmitter

WARMUP_BARS_DEFAULT = 2000
STD_CLAMP = 1e-8


@dataclass(slots=True, frozen=True, kw_only=True)
class FrozenNormalizer:
    """Per-(channel, feature) mean + std constants.

    Both dicts are keyed by the same channel names as the source
    TokenizedArtifact's `features`. `mean[key]` and `std[key]` each have
    shape `[F_c]` matching the channel's per-feature width.
    """

    mean: dict[str, Tensor]
    std: dict[str, Tensor]
    feature_count: int  # Σ_c F_c across all channels

    def channels(self) -> list[str]:
        return sorted(self.mean.keys())


def fit_frozen_normalizer(
    artifact: TokenizedArtifact,
    *,
    training_range_start: str,
    training_range_end: str,
    emitter: StrictSignalEmitter,
    run_id: str,
    warmup_bars: int = WARMUP_BARS_DEFAULT,
) -> FrozenNormalizer:
    """Fit per-channel mean + std across training-partition rows.

    A row counts toward the fit iff `artifact.targets[i] != -100` (matches the
    sampler's ignore-index semantics; null-target rows would skew statistics).
    Emits `NORMALIZER_FITTED` at close.

    `warmup_bars` is a documentation constant recorded in the emit payload; the
    interpretation (A) fit uses the full training partition, not a warmup prefix.
    """
    if not artifact.features:
        raise ValueError("cannot fit normalizer on empty features")

    valid_mask = artifact.targets != -100
    if valid_mask.sum().item() == 0:
        raise ValueError("no valid rows (every target is -100); cannot fit normalizer")

    mean: dict[str, Tensor] = {}
    std: dict[str, Tensor] = {}
    total_feature_count = 0
    for key, tensor in artifact.features.items():
        # tensor: [T, F_c]. Select rows where target is valid.
        selected = tensor[valid_mask]
        mean[key] = selected.mean(dim=0)
        std[key] = selected.std(dim=0, unbiased=False)
        total_feature_count += int(tensor.shape[1])

    emitter.emit(
        "NORMALIZER_FITTED",
        run_id=run_id,
        feature_count=total_feature_count,
        warmup_bars=warmup_bars,
        training_range_start=training_range_start,
        training_range_end=training_range_end,
    )
    return FrozenNormalizer(mean=mean, std=std, feature_count=total_feature_count)


def write_frozen_normalizer(
    normalizer: FrozenNormalizer,
    base_path: Path,
    emitter: StrictSignalEmitter,
    run_id: str,
) -> Path:
    """Persist via `artifacts.write_versioned`; emit `NORMALIZER_STATE_WRITTEN`.

    `base_path` is the LOGICAL base name (e.g. `artifacts/tokenizer/normalizers.pt`).
    Landed at `normalizers.{run_id}.pt` with `normalizers.latest.pt` symlink and
    `.sha256` sidecar per Sprint 036 storage discipline.
    """
    buffer = io.BytesIO()
    torch.save(
        {
            "mean": normalizer.mean,
            "std": normalizer.std,
            "feature_count": normalizer.feature_count,
        },
        buffer,
    )
    content = buffer.getvalue()
    result = write_versioned(base_path, run_id, content)
    emitter.emit(
        "NORMALIZER_STATE_WRITTEN",
        run_id=run_id,
        path=str(result.versioned_path),
        feature_count=normalizer.feature_count,
        sha256=result.sha256,
    )
    return result.versioned_path


def load_frozen_normalizer(path: Path) -> FrozenNormalizer:
    """Read the persisted dict and return a FrozenNormalizer dataclass."""
    payload = torch.load(path, weights_only=False)
    return FrozenNormalizer(
        mean=payload["mean"],
        std=payload["std"],
        feature_count=int(payload["feature_count"]),
    )


def apply_frozen_normalizer(
    feats: dict[str, Tensor], normalizer: FrozenNormalizer
) -> dict[str, Tensor]:
    """Return a new dict with each channel's tensor z-scored by frozen constants.

    Broadcast rules: `feats[key]` shape can be `[T, F_c]` (single-window) or
    `[B, T, F_c]` (batched); the constants are `[F_c]` and broadcast over the
    leading dims. Constant columns (std == 0) pass through as 0 via a
    `max(std, STD_CLAMP)` divisor.

    Input tensors are not mutated; a new dict of new tensors is returned.
    """
    out: dict[str, Tensor] = {}
    for key, tensor in feats.items():
        if key not in normalizer.mean:
            raise ValueError(f"normalizer missing channel {key!r}")
        mean = normalizer.mean[key].to(tensor.device)
        std = normalizer.std[key].to(tensor.device)
        std_clamped = std.clamp(min=STD_CLAMP)
        out[key] = (tensor - mean) / std_clamped
    return out
