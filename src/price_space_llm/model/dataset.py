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


def split_tokens(tokens: list[int], train_frac: float) -> tuple[list[int], list[int]]:
    """Contiguous split: first `train_frac` fraction is train, rest is val."""
    if not 0.0 < train_frac < 1.0:
        raise ValueError(f"train_frac must be in (0, 1); got {train_frac}")
    n_train = int(len(tokens) * train_frac)
    return tokens[:n_train], tokens[n_train:]


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
    vol: Tensor  # Tensor[T] float32; target's realized_vol_30
    timestamps: Tensor  # Tensor[T] int64; UTC Unix seconds
    is_overnight_gap: Tensor | None  # Tensor[T] int8 (Sprint 055) or None
    mask: Tensor  # Tensor[T] bool; True iff every feature is non-null
    channel_names: tuple[str, ...]
    meta: dict[str, Any] = field(default_factory=dict)


def load_tokens_pt(path: Path) -> TokenizedArtifact:
    """Read a Sprint 052 tokenized `.pt` artifact and return the typed dataclass.

    Raises `ValueError` if any required key is missing (features, targets,
    vol, timestamps, mask, channel_names, meta). `is_overnight_gap` is
    optional and defaults to None.
    """
    payload = torch.load(path, weights_only=False)
    required = ("features", "targets", "vol", "timestamps", "mask", "channel_names", "meta")
    for k in required:
        if k not in payload:
            raise ValueError(f"tokens .pt at {path} missing required field {k!r}")
    return TokenizedArtifact(
        features=payload["features"],
        targets=payload["targets"],
        vol=payload["vol"],
        timestamps=payload["timestamps"],
        is_overnight_gap=payload.get("is_overnight_gap"),
        mask=payload["mask"],
        channel_names=tuple(payload["channel_names"]),
        meta=dict(payload["meta"]),
    )
