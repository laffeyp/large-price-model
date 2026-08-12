"""Deterministic evaluator over a checkpoint.

Reads a `.pt` checkpoint from Sprint 031, reconstructs the model,
iterates every valid window in the requested split, produces
(probs, targets) tensors, computes the seven metrics per regime, emits
`METRIC_COMPUTED` x 7 x n_regimes x n_splits, freezes regime labels
with `REGIME_LABELS_FROZEN`, measures bucket-frequency drift with
`BUCKET_FREQUENCY_DRIFT_MEASURED`, and writes `artifacts/{run_id}/
metrics.json` with `METRIC_SNAPSHOT_WRITTEN` (sha256'd).

Deterministic: no random sampling. Every valid start position in the
split contributes exactly one (input, target) window. Reproducible
across runs at bit-level on CPU.
"""

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import polars as pl
import torch
from torch import Tensor
from torch.nn import functional as F

from price_space_llm.evaluation.metrics import (
    MetricSet,
    compute_bucket_frequency_drift,
    compute_metric_set,
)
from price_space_llm.evaluation.regimes import (
    RegimeThresholds,
    assign_regime,
    fit_regime_thresholds,
)
from price_space_llm.model.transformer import PriceSpaceLLM, TransformerConfig
from price_space_llm.signals import StrictSignalEmitter

REGIME_LABELS: tuple[str, ...] = ("low", "mid", "high")
METRIC_NAMES: tuple[str, ...] = ("nll", "ece", "brier", "rps", "dir_acc", "top1", "top3")


@dataclass(slots=True, frozen=True, kw_only=True)
class EvaluatorResult:
    run_id: str
    checkpoint_path: str
    metrics_path: str
    n_metric_emits: int
    thresholds: RegimeThresholds
    elapsed_seconds: float


def _load_checkpoint(path: Path) -> tuple[PriceSpaceLLM, dict[str, Any]]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    cfg_dict = payload["config"]
    model_cfg = TransformerConfig(
        vocab_size=cfg_dict["vocab_size"],
        context_len=cfg_dict["context_len"],
        d_model=cfg_dict["d_model"],
        n_layers=cfg_dict["n_layers"],
        n_heads=cfg_dict["n_heads"],
        dropout=0.0,
    )
    model = PriceSpaceLLM(model_cfg)
    model.load_state_dict(payload["model_state_dict"])
    model.eval()
    return model, cfg_dict


def _deterministic_windows(tokens: list[int], context_len: int) -> tuple[Tensor, Tensor]:
    """Return (inputs, targets) covering every valid start position. Both shape (N, T)."""
    n = len(tokens) - context_len - 1
    if n < 1:
        return torch.zeros((0, context_len), dtype=torch.long), torch.zeros(
            (0, context_len), dtype=torch.long
        )
    t = torch.tensor(tokens, dtype=torch.long)
    inputs = torch.stack([t[s : s + context_len] for s in range(n + 1)])
    targets = torch.stack([t[s + 1 : s + 1 + context_len] for s in range(n + 1)])
    return inputs, targets


def _forward_all_in_batches(
    model: PriceSpaceLLM,
    inputs: Tensor,
    batch_size: int = 32,
) -> Tensor:
    """Run the model over `inputs` in batches; return concatenated softmax probs (N, T, V)."""
    all_probs: list[Tensor] = []
    with torch.no_grad():
        for start in range(0, inputs.shape[0], batch_size):
            batch = inputs[start : start + batch_size]
            logits = model(batch)  # (B, T, V)
            all_probs.append(F.softmax(logits, dim=-1))
    return torch.cat(all_probs, dim=0) if all_probs else torch.zeros((0,))


def _load_features_and_tokens(
    features_path: Path,
    tokens_path: Path,
    target_symbol: str,
) -> tuple[pl.DataFrame, list[int], list[float | None]]:
    """Return (aligned features frame, tokens list, per-token rolling-vol list)."""
    features = pl.read_parquet(features_path)
    tokens_df = pl.read_parquet(tokens_path)
    token_col = f"target__{target_symbol}__bucket_id"
    vol_col = f"target__{target_symbol}__rolling_std_20"
    if token_col not in tokens_df.columns:
        raise ValueError(f"tokens parquet lacks {token_col!r}")
    if vol_col not in features.columns:
        raise ValueError(f"features parquet lacks {vol_col!r}")

    joined = tokens_df.join(features.select(["grid_ts", vol_col]), on="grid_ts", how="left")
    joined = joined.filter(pl.col(token_col).is_not_null())
    tokens = [int(v) for v in joined[token_col].to_list()]
    vols_raw = joined[vol_col].to_list()
    vols = [float(v) if v is not None else None for v in vols_raw]
    return features, tokens, vols


def _partition_positions_by_regime(
    vols: list[float | None],
    context_len: int,
    thresholds: RegimeThresholds,
) -> dict[str, list[int]]:
    """Assign each valid start position to a regime by the volatility at the LAST context bar.

    A window starting at position `s` uses tokens[s..s+context_len-1] as input; the target
    position is s+context_len. The regime label follows the target's volatility -- this is
    the "regime of the bar we are predicting into," matching the tech-arch's stated intent.
    """
    positions_by_regime: dict[str, list[int]] = {r: [] for r in REGIME_LABELS}
    n_valid = len(vols) - context_len - 1
    for s in range(n_valid + 1):
        target_idx = s + context_len
        if target_idx >= len(vols):
            continue
        regime = assign_regime(vols[target_idx], thresholds)
        positions_by_regime[regime].append(s)
    return positions_by_regime


def _metrics_over_positions(
    probs: Tensor,
    targets: Tensor,
    positions: list[int],
    vocab_size: int,
) -> MetricSet:
    """Subset (probs, targets) at the last position of each window and compute the metric set."""
    if not positions:
        return MetricSet(
            nll=0.0, ece=0.0, brier=0.0, rps=0.0, dir_acc=0.0, top1=0.0, top3=0.0, n_examples=0
        )
    # For each window position we score the LAST-position prediction only.
    idx = torch.tensor(positions, dtype=torch.long)
    last_probs = probs[idx, -1, :]  # (M, V)
    last_targets = targets[idx, -1]  # (M,)
    return compute_metric_set(last_probs, last_targets, vocab_size)


def run_evaluation(
    *,
    checkpoint_path: Path,
    features_path: Path,
    tokens_path: Path,
    target_symbol: str,
    train_frac: float,
    output_dir: Path,
    emitter: StrictSignalEmitter,
    run_id: str,
    training_range_start: str,
    training_range_end: str,
) -> EvaluatorResult:
    """End-to-end offline evaluation of a checkpoint against tokens + features."""
    t0 = time.monotonic()
    model, cfg_dict = _load_checkpoint(checkpoint_path)
    context_len = cfg_dict["context_len"]
    vocab_size = cfg_dict["vocab_size"]

    _features, tokens, vols = _load_features_and_tokens(features_path, tokens_path, target_symbol)
    n_train = int(len(tokens) * train_frac)
    train_tokens = tokens[:n_train]
    val_tokens = tokens[n_train:]
    train_vols = vols[:n_train]
    val_vols = vols[n_train:]

    # Freeze regime labels on the training-window volatility.
    thresholds = fit_regime_thresholds(train_vols)
    emitter.emit(
        "REGIME_LABELS_FROZEN",
        run_id=run_id,
        low_threshold=thresholds.low_threshold,
        mid_threshold=thresholds.mid_threshold,
        training_range_start=training_range_start,
        training_range_end=training_range_end,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_by_split_regime: dict[str, dict[str, MetricSet]] = {}
    n_metric_emits = 0

    for split, split_tokens, split_vols in (
        ("train", train_tokens, train_vols),
        ("val", val_tokens, val_vols),
    ):
        inputs, targets = _deterministic_windows(split_tokens, context_len)
        if inputs.shape[0] == 0:
            metrics_by_split_regime[split] = {r: _empty_set() for r in REGIME_LABELS}
            continue
        probs = _forward_all_in_batches(model, inputs)
        positions_by_regime = _partition_positions_by_regime(split_vols, context_len, thresholds)
        metrics_by_split_regime[split] = {}
        for regime in REGIME_LABELS:
            metric_set = _metrics_over_positions(
                probs, targets, positions_by_regime[regime], vocab_size
            )
            metrics_by_split_regime[split][regime] = metric_set
            for name in METRIC_NAMES:
                emitter.emit(
                    "METRIC_COMPUTED",
                    run_id=run_id,
                    name=name,
                    value=float(getattr(metric_set, name)),
                    split=split,
                    regime_label=regime,
                )
                n_metric_emits += 1

    # Bucket-frequency drift: train vs val, all regimes pooled.
    train_freq, val_freq, max_dev, outer_ratio = compute_bucket_frequency_drift(
        train_tokens, val_tokens, vocab_size
    )
    emitter.emit(
        "BUCKET_FREQUENCY_DRIFT_MEASURED",
        run_id=run_id,
        split="val",
        train_frequency_by_bucket=train_freq,
        realized_frequency_by_bucket=val_freq,
        max_absolute_deviation=max_dev,
        outer_bucket_ratio=outer_ratio,
    )

    # Persist metrics.json.
    metrics_path = output_dir / "metrics.json"
    metrics_body = {
        "run_id": run_id,
        "checkpoint": str(checkpoint_path),
        "thresholds": asdict(thresholds),
        "metrics": {
            split: {regime: asdict(ms) for regime, ms in per_regime.items()}
            for split, per_regime in metrics_by_split_regime.items()
        },
        "drift": {
            "max_absolute_deviation": max_dev,
            "outer_bucket_ratio": outer_ratio,
        },
    }
    body_text = json.dumps(metrics_body, sort_keys=True, indent=2)
    metrics_path.write_text(body_text, encoding="utf-8")
    digest = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
    for split in sorted(metrics_by_split_regime):
        emitter.emit(
            "METRIC_SNAPSHOT_WRITTEN",
            run_id=run_id,
            path=str(metrics_path),
            split=split,
            keys=list(METRIC_NAMES),
            sha256=digest,
        )

    return EvaluatorResult(
        run_id=run_id,
        checkpoint_path=str(checkpoint_path),
        metrics_path=str(metrics_path),
        n_metric_emits=n_metric_emits,
        thresholds=thresholds,
        elapsed_seconds=time.monotonic() - t0,
    )


def _empty_set() -> MetricSet:
    return MetricSet(
        nll=0.0, ece=0.0, brier=0.0, rps=0.0, dir_acc=0.0, top1=0.0, top3=0.0, n_examples=0
    )
