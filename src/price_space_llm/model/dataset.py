"""Random-window sampler over the tokens parquet.

Reads the tokens parquet from Sprint 030, filters non-null bucket_ids,
and yields fixed-shape (input, target) batches. Input length = context_len;
target is the input shifted one position forward. Every window's target
position lies strictly after its input positions -- the causality gate
mirrors the alignment invariant from Sprint 025.

Split: `train_frac` (default 0.8) of the tokens go to training; the tail
becomes the validation set. Splits are contiguous (no shuffling of the
underlying time-series). Random sampling occurs within a partition, not
across.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
import torch
from torch import Tensor


@dataclass(slots=True, frozen=True, kw_only=True)
class WindowBatch:
    inputs: Tensor  # (B, T) int64
    targets: Tensor  # (B, T) int64 -- inputs shifted by 1
    starts: tuple[
        int, ...
    ]  # Sprint 041: real start positions per batch entry, in token-stream index.


def load_tokens(tokens_path: Path, target_symbol: str) -> list[int]:
    """Read the tokens parquet; return the target symbol's bucket_id sequence, nulls dropped."""
    df = pl.read_parquet(tokens_path)
    col = f"target__{target_symbol}__bucket_id"
    if col not in df.columns:
        raise ValueError(f"tokens parquet has no column {col!r}")
    return [int(v) for v in df[col].to_list() if v is not None]


class WindowSampler:
    """Yields random windows of length `context_len + 1` (input + target-shift).

    `generator` fixes the sample sequence; identical seeds yield identical batches.
    """

    def __init__(
        self,
        tokens: list[int],
        *,
        context_len: int,
        batch_size: int,
        generator: torch.Generator,
    ) -> None:
        if len(tokens) < context_len + 1:
            raise ValueError(f"need at least {context_len + 1} tokens; got {len(tokens)}")
        self._tokens = torch.tensor(tokens, dtype=torch.long)
        self._context_len = context_len
        self._batch_size = batch_size
        self._generator = generator
        self._max_start = len(tokens) - context_len - 1

    def sample(self) -> WindowBatch:
        """One batch. Every sequence input[i] predicts target[i]; target = tokens shifted +1."""
        starts = torch.randint(
            low=0,
            high=self._max_start + 1,
            size=(self._batch_size,),
            generator=self._generator,
        )
        inputs = torch.stack([self._tokens[s : s + self._context_len] for s in starts])  # (B, T)
        targets = torch.stack(
            [self._tokens[s + 1 : s + 1 + self._context_len] for s in starts]
        )  # (B, T)
        starts_tuple = tuple(int(x) for x in starts.tolist())
        return WindowBatch(inputs=inputs, targets=targets, starts=starts_tuple)

    def n_valid_starts(self) -> int:
        return self._max_start + 1

    def peek_starts(self) -> tuple[int, ...]:
        """Return one deterministic starts vector for testing."""
        starts = torch.randint(
            low=0,
            high=self._max_start + 1,
            size=(self._batch_size,),
            generator=self._generator,
        )
        return tuple(int(x) for x in starts.tolist())


def split_tokens(
    tokens: list[int], train_frac: float, embargo: int = 0
) -> tuple[list[int], list[int]]:
    """Contiguous split with an optional purged embargo at the boundary.

    Sprint 058: `embargo` drops that many tokens between train and val so the
    val window's first target does not see the training window's last input.
    Spec § Testing + § 9.2. Default `embargo=0` preserves the pre-Sprint-058
    behavior for callers that don't opt in.
    """
    if not 0.0 < train_frac < 1.0:
        raise ValueError(f"train_frac must be in (0, 1); got {train_frac}")
    if embargo < 0:
        raise ValueError(f"embargo must be >= 0; got {embargo}")
    n_train = int(len(tokens) * train_frac)
    return tokens[:n_train], tokens[n_train + embargo :]


# Sprint 052: extended tokenized artifact reader ---------------------------


@dataclass(slots=True, frozen=True, kw_only=True)
class TokenizedArtifact:
    """Per-channel feature tensors + targets + metadata per tech-arch §5.

    Sprint 052 ships this alongside the legacy parquet path; Sprint 053's
    MarketStateEmbedder consumes it via a per-channel `nn.Linear(F_c, d_model)`
    projection summed to a per-bar market-state vector.
    """

    features: dict[str, Tensor]  # {channel__symbol: Tensor[T, F_c]}
    targets: Tensor  # Tensor[T] int64; -100 = null (PyTorch CE ignore_index)
    # Sprint 088: raw float log-return per grid position; NaN where the
    # log_return column was null (same rows where targets == -100). None on
    # pre-Sprint-088 artifacts. Consumed by the quantile-head ablation
    # (Sprint 089); ignored by the categorical head. Defaults to None so
    # every pre-Sprint-088 caller constructs the dataclass unchanged.
    raw_targets: Tensor | None = None
    vol: Tensor  # Tensor[T] float32; target's realized_vol_30
    timestamps: Tensor  # Tensor[T] int64; UTC Unix seconds
    is_overnight_gap: Tensor | None  # Tensor[T] int8 (Sprint 055) or None
    # Sprint 075 semantic: True iff row is a valid training example for the
    # target (target features non-null AND targets != -100). Pre-Sprint-075
    # artifacts on disk carry the old semantic (all-features-non-null) and
    # collapse to all-False on the real corpus; check
    # `meta.get("mask_semantics")` before consuming.
    mask: Tensor  # Tensor[T] bool
    channel_names: tuple[str, ...]
    meta: dict[str, Any] = field(default_factory=dict)


# Sprint 053: multi-channel window sampler --------------------------------


@dataclass(slots=True, frozen=True, kw_only=True)
class WindowBatchFeats:
    """Per-channel feature batch for the MarketStateTransformer.

    `feats[key]` shape: `Tensor[B, T, F_c]`. `targets` shape: `Tensor[B, T]` int64,
    with -100 marking null targets (PyTorch CE ignore_index).
    """

    feats: dict[str, Tensor]
    targets: Tensor
    starts: tuple[int, ...]
    # Sprint 089: parallel float raw targets for the quantile-head loss.
    # None when the source artifact has raw_targets=None (pre-Sprint-088 .pt
    # or explicit categorical-only fixture).
    raw_targets: Tensor | None = None


class WindowSamplerFeats:
    """Random-window sampler over a Sprint 052 TokenizedArtifact.

    Uses the same start indices across every channel so all per-channel slices
    align in time. Targets are `artifact.targets[start+1 : start+1+context_len]`
    matching the bucket-ID sampler's shift-by-one causality convention.
    """

    def __init__(
        self,
        artifact: TokenizedArtifact,
        *,
        context_len: int,
        batch_size: int,
        generator: torch.Generator,
    ) -> None:
        if not artifact.features:
            raise ValueError("TokenizedArtifact has no features; cannot sample")
        first_key = next(iter(artifact.features.keys()))
        t = artifact.features[first_key].shape[0]
        for key, tensor in artifact.features.items():
            if tensor.shape[0] != t:
                raise ValueError(f"channel {key!r} length {tensor.shape[0]} != {t} (first channel)")
        if t < context_len + 1:
            raise ValueError(f"need at least {context_len + 1} rows; got {t}")
        if artifact.targets.shape[0] != t:
            raise ValueError(f"targets length {artifact.targets.shape[0]} != features length {t}")
        self._artifact = artifact
        self._context_len = context_len
        self._batch_size = batch_size
        self._generator = generator
        self._max_start = t - context_len - 1

    def sample(self) -> WindowBatchFeats:
        starts = torch.randint(
            low=0,
            high=self._max_start + 1,
            size=(self._batch_size,),
            generator=self._generator,
        )
        feats: dict[str, Tensor] = {}
        for key, tensor in self._artifact.features.items():
            slices = [tensor[s : s + self._context_len] for s in starts]
            feats[key] = torch.stack(slices)  # (B, T, F_c)
        targets = torch.stack(
            [self._artifact.targets[s + 1 : s + 1 + self._context_len] for s in starts]
        )  # (B, T)
        # Sprint 089: sample raw_targets in parallel when present.
        raw_targets: Tensor | None = None
        if self._artifact.raw_targets is not None:
            raw_targets = torch.stack(
                [
                    self._artifact.raw_targets[s + 1 : s + 1 + self._context_len]
                    for s in starts
                ]
            )
        starts_tuple = tuple(int(x) for x in starts.tolist())
        return WindowBatchFeats(
            feats=feats,
            targets=targets,
            starts=starts_tuple,
            raw_targets=raw_targets,
        )

    def n_valid_starts(self) -> int:
        return self._max_start + 1


def zero_non_target_features(artifact: TokenizedArtifact, target_symbol: str) -> TokenizedArtifact:
    """Sprint 061: return a new TokenizedArtifact with every non-target channel's
    feature tensor replaced by zeros of the same shape.

    Product-spec § Baselines target-only ablation: *"same architecture as the
    default transformer, every non-target channel zeroed at the embedder — the
    whole thesis rides on this comparison."* The zeroed model can still consume
    the target features; the ablation isolates whether the extra channels are
    doing real work.

    `target_symbol` matches the channel key suffix, e.g. `target__SPY` when
    `target_symbol == "SPY"`. Target channel's tensor is copied through
    unchanged. targets, vol, timestamps, is_overnight_gap, mask, channel_names,
    meta all pass through unchanged.
    """
    target_key = f"target__{target_symbol}"
    if target_key not in artifact.features:
        raise ValueError(
            f"target key {target_key!r} not in artifact.features; "
            f"got keys={sorted(artifact.features.keys())}"
        )
    new_features: dict[str, Tensor] = {}
    for key, tensor in artifact.features.items():
        if key == target_key:
            new_features[key] = tensor
        else:
            new_features[key] = torch.zeros_like(tensor)
    return TokenizedArtifact(
        features=new_features,
        targets=artifact.targets,
        raw_targets=artifact.raw_targets,
        vol=artifact.vol,
        timestamps=artifact.timestamps,
        is_overnight_gap=artifact.is_overnight_gap,
        mask=artifact.mask,
        channel_names=artifact.channel_names,
        meta=artifact.meta,
    )


CURRENT_MASK_SEMANTICS = "target_valid_v075"


class LegacyMaskSemanticRefused(RuntimeError):
    """Raised when `load_tokens_pt` reads an artifact whose `mask_semantics`
    marker does not match `CURRENT_MASK_SEMANTICS` and the caller has not
    opted into legacy tolerance via `allow_legacy_mask=True`.

    Sprint 077 tightens the Sprint 075 hand-tight marker into a bit-tight
    load-time refusal. Pre-Sprint-075 artifacts carry an all-False mask
    field (sparse event channels poisoned the all-non-null check); loading
    them silently would let a downstream consumer treat every row as invalid.
    """


def load_tokens_pt(
    path: Path,
    *,
    allow_legacy_mask: bool = False,
) -> TokenizedArtifact:
    """Read a Sprint 052 tokenized `.pt` artifact and return the typed dataclass.

    Raises `ValueError` if any required key is missing (features, targets,
    vol, timestamps, mask, channel_names, meta). `is_overnight_gap` is
    optional and defaults to None.

    Sprint 077: raises `LegacyMaskSemanticRefused` when
    `meta.get("mask_semantics") != CURRENT_MASK_SEMANTICS` unless the caller
    passes `allow_legacy_mask=True`. The old all-features-non-null semantic
    collapsed to all-False on the real corpus (Sprint 052 named this;
    Sprint 075 fixed it and stamped `target_valid_v075`).
    """
    payload = torch.load(path, weights_only=False)
    required = ("features", "targets", "vol", "timestamps", "mask", "channel_names", "meta")
    for k in required:
        if k not in payload:
            raise ValueError(f"tokens .pt at {path} missing required field {k!r}")
    marker = payload["meta"].get("mask_semantics")
    if marker != CURRENT_MASK_SEMANTICS and not allow_legacy_mask:
        raise LegacyMaskSemanticRefused(
            f"tokens .pt at {path} has mask_semantics={marker!r}; expected "
            f"{CURRENT_MASK_SEMANTICS!r}. Regenerate via scripts/bucketize.py "
            "or pass allow_legacy_mask=True after acknowledging the legacy semantic."
        )
    return TokenizedArtifact(
        features=payload["features"],
        targets=payload["targets"],
        # Sprint 088: raw_targets is optional; None on pre-Sprint-088 artifacts.
        raw_targets=payload.get("raw_targets"),
        vol=payload["vol"],
        timestamps=payload["timestamps"],
        is_overnight_gap=payload.get("is_overnight_gap"),
        mask=payload["mask"],
        channel_names=tuple(payload["channel_names"]),
        meta=dict(payload["meta"]),
    )
