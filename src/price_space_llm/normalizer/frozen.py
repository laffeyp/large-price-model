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

# Sprint 076: channels whose std is zero by construction. Event-family channels
# fire fresh-known-at flags at fixed schedules and encode nothing else; every
# feature the tokenizer computes on them is constant zero across time.
# `warn_channels_under_clamp` exempts these; expanding the set requires an
# explicit code change so the exemption is auditable.
EXPECTED_CONSTANT_CHANNELS: frozenset[str] = frozenset(
    {
        "event__FOMC",
        "event__CPI_RELEASE",
        "event__OPTIONS_EXPIRY",
        "event__EARNINGS_DENSITY_SPX",
    }
)


@dataclass(slots=True, frozen=True, kw_only=True)
class FrozenNormalizer:
    """Per-(channel, feature) mean + std constants.

    Both dicts are keyed by the same channel names as the source
    TokenizedArtifact's `features`. `mean[key]` and `std[key]` each have
    shape `[F_c]` matching the channel's per-feature width.

    `std_clamp` (Sprint 076) is the divisor floor for constant columns. Ships
    with the persisted `.pt` so a re-loaded normalizer keeps the fit-time
    value; pre-Sprint-076 artifacts on disk have no key and fall back to the
    module-level `STD_CLAMP = 1e-8` at load time.
    """

    mean: dict[str, Tensor]
    std: dict[str, Tensor]
    feature_count: int  # Σ_c F_c across all channels
    std_clamp: float = STD_CLAMP

    def channels(self) -> list[str]:
        return sorted(self.mean.keys())


class NormalizerStdClampViolation(RuntimeError):
    """Sprint 079: raised by `fit_frozen_normalizer` in strict mode when
    a non-exempt channel's std lies under the clamp band. Bit-tight
    version of the Sprint 076 opt-in `warn_channels_under_clamp` helper.
    Callers that fit on synthetic data with genuinely-tiny std pass
    `strict_std_clamp=False`.
    """


def fit_frozen_normalizer(
    artifact: TokenizedArtifact,
    *,
    training_range_start: str,
    training_range_end: str,
    emitter: StrictSignalEmitter,
    run_id: str,
    warmup_bars: int = WARMUP_BARS_DEFAULT,
    strict_std_clamp: bool = True,
    std_clamp: float = STD_CLAMP,
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

    normalizer = FrozenNormalizer(
        mean=mean,
        std=std,
        feature_count=total_feature_count,
        std_clamp=std_clamp,
    )
    # Sprint 080 (v0.6): emit NORMALIZER_CHANNEL_UNDER_CLAMP per hit regardless
    # of strict/lenient posture. The trace records every offender before the
    # raise fires in strict mode, and stands as a pure warning in lenient mode.
    hits = warn_channels_under_clamp(normalizer)
    for channel, feature_index, std_value in hits:
        emitter.emit(
            "NORMALIZER_CHANNEL_UNDER_CLAMP",
            run_id=run_id,
            channel=channel,
            feature_index=feature_index,
            std_value=std_value,
            std_clamp=std_clamp,
        )
    if strict_std_clamp and hits:
        detail = ", ".join(f"{c}[{i}]=std={v!r}" for c, i, v in hits[:5])
        raise NormalizerStdClampViolation(
            f"{len(hits)} non-exempt channel(s) with std < {std_clamp}: {detail} "
            "(and more if truncated). Add the channel to "
            "EXPECTED_CONSTANT_CHANNELS if it is genuinely constant, or pass "
            "strict_std_clamp=False to accept the tiny-std normalization."
        )
    emitter.emit(
        "NORMALIZER_FITTED",
        run_id=run_id,
        feature_count=total_feature_count,
        warmup_bars=warmup_bars,
        training_range_start=training_range_start,
        training_range_end=training_range_end,
    )
    return normalizer


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
            # Sprint 076: pin the clamp with the artifact so re-loads recover
            # the fit-time value.
            "std_clamp": normalizer.std_clamp,
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


class LegacyStdClampMissing(RuntimeError):
    """Raised when `load_frozen_normalizer` reads an artifact with no
    `std_clamp` key and the caller has not opted into legacy tolerance via
    `allow_legacy_std_clamp=True`.

    Sprint 077 tightens the Sprint 076 hand-tight fallback into a bit-tight
    load-time refusal. A caller loading a pre-Sprint-076 normalizer would
    silently receive `std_clamp = STD_CLAMP` (1e-8); this raise forces the
    caller to acknowledge the fallback or regenerate the artifact.
    """


def load_frozen_normalizer(
    path: Path,
    *,
    allow_legacy_std_clamp: bool = False,
) -> FrozenNormalizer:
    """Read the persisted dict and return a FrozenNormalizer dataclass.

    Sprint 076 stored `std_clamp` alongside `mean` / `std` / `feature_count`.
    Sprint 077: an artifact without the key raises `LegacyStdClampMissing`
    unless the caller passes `allow_legacy_std_clamp=True`, in which case the
    module-level `STD_CLAMP` is used as the fallback and no exception fires.
    """
    payload = torch.load(path, weights_only=False)
    if "std_clamp" not in payload and not allow_legacy_std_clamp:
        raise LegacyStdClampMissing(
            f"frozen normalizer at {path} has no std_clamp key (pre-Sprint-076 "
            "artifact). Refit via scripts/measure_drift.py or pass "
            "allow_legacy_std_clamp=True to accept the module-default 1e-8 fallback."
        )
    std_clamp = float(payload.get("std_clamp", STD_CLAMP))
    return FrozenNormalizer(
        mean=payload["mean"],
        std=payload["std"],
        feature_count=int(payload["feature_count"]),
        std_clamp=std_clamp,
    )


def apply_frozen_normalizer(
    feats: dict[str, Tensor], normalizer: FrozenNormalizer
) -> dict[str, Tensor]:
    """Return a new dict with each channel's tensor z-scored by frozen constants.

    Broadcast rules: `feats[key]` shape can be `[T, F_c]` (single-window) or
    `[B, T, F_c]` (batched); the constants are `[F_c]` and broadcast over the
    leading dims. Constant columns (std == 0) pass through as 0 via a
    `max(std, normalizer.std_clamp)` divisor (Sprint 076: per-normalizer
    clamp instead of the module constant, so a caller that fits with a
    tighter or looser floor sees the same floor at apply time).

    Input tensors are not mutated; a new dict of new tensors is returned.
    """
    out: dict[str, Tensor] = {}
    for key, tensor in feats.items():
        if key not in normalizer.mean:
            raise ValueError(f"normalizer missing channel {key!r}")
        mean = normalizer.mean[key].to(tensor.device)
        std = normalizer.std[key].to(tensor.device)
        std_clamped = std.clamp(min=normalizer.std_clamp)
        out[key] = (tensor - mean) / std_clamped
    return out


def warn_channels_under_clamp(
    normalizer: FrozenNormalizer,
    *,
    exempt: frozenset[str] = EXPECTED_CONSTANT_CHANNELS,
) -> list[tuple[str, int, float]]:
    """Return every non-exempt (channel, feature_index) whose std sits inside the clamp band.

    Sprint 076: opt-in check the caller wires when it wants to surface
    genuinely-tiny-std channels that would silently over-normalize. Constant
    channels named in `exempt` are known-zero-std by construction; every other
    channel where `std[i] < normalizer.std_clamp` produces a `(channel,
    feature_index, std_value)` tuple.

    Empty list => every non-exempt std is safely above the clamp floor.
    """
    hits: list[tuple[str, int, float]] = []
    for key, std in normalizer.std.items():
        if key in exempt:
            continue
        for i, value in enumerate(std.tolist()):
            if value < normalizer.std_clamp:
                hits.append((key, i, float(value)))
    return hits
