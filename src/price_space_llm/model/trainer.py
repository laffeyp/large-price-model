"""Training loop with strict-vocabulary emit at every SDD-declared step.

Emits per tech-arch §9 + v0.3 vocabulary:
- `WINDOW_SAMPLED` per training window pulled from the sampler
- `TRAINING_STEP_COMPLETED` per optimizer step
- `CHECKPOINT_WRITTEN` every `eval_every` steps with all six validation
  metrics (`val_nll`, `val_ece`, `val_brier`, `val_rps`, `val_dir_acc`,
  `val_top1`, `val_top3`)
- `EPOCH_COMPLETED` at end of the run
- `TRAINING_DIVERGED` if the loss goes NaN or the grad norm explodes

Divergence policy: NaN train_loss halts (raises `TrainingDiverged`
after emitting). Grad-norm > `grad_clip * 10` is treated as
gradient_explosion. Val-metric divergence is out of scope for Sprint
031 (needs multi-epoch tracking; deferred).
"""

import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F

from price_space_llm.model.dataset import (
    TokenizedArtifact,
    WindowBatch,
    WindowBatchFeats,
    WindowSampler,
    WindowSamplerFeats,
    split_tokens,
)
from price_space_llm.model.transformer import (
    MarketStateTransformer,
    MarketStateTransformerConfig,
    PriceSpaceLLM,
    TransformerConfig,
)
from price_space_llm.signals import StrictSignalEmitter


@dataclass(slots=True, frozen=True, kw_only=True)
class TrainerConfig:
    n_steps: int
    batch_size: int
    lr: float
    eval_every: int
    train_frac: float = 0.8
    grad_clip: float = 1.0
    seed: int = 0


@dataclass(slots=True, frozen=True, kw_only=True)
class TrainerResult:
    run_id: str
    final_step: int
    final_train_loss: float
    n_checkpoints: int
    n_parameters: int
    checkpoint_dir: str
    elapsed_seconds: float


class TrainingDiverged(RuntimeError):
    """Raised after emitting TRAINING_DIVERGED so the caller can exit nonzero."""


def _compute_val_metrics(
    model: PriceSpaceLLM,
    val_sampler: WindowSampler,
    n_val_batches: int,
) -> dict[str, float]:
    """Deterministic val pass. Returns the seven metrics CHECKPOINT_WRITTEN requires.

    Sprint 032 wired real ECE / Brier / RPS via `evaluation.metrics.compute_metric_set`;
    Sprint 031 had shipped 0.0 placeholders. This trainer path now runs the same
    computation the offline evaluator uses.
    """
    from price_space_llm.evaluation.metrics import compute_metric_set

    model.eval()
    all_probs: list[torch.Tensor] = []
    all_targets: list[torch.Tensor] = []
    vocab_size = model.config.vocab_size
    # Sprint 051 blocker #4: val batches move to model's device before forward.
    val_device = next(model.parameters()).device
    with torch.no_grad():
        for _ in range(n_val_batches):
            batch = val_sampler.sample()
            inputs = batch.inputs.to(val_device)
            targets_dev = batch.targets.to(val_device)
            logits = model(inputs)  # (B, T, V)
            probs = F.softmax(logits, dim=-1).reshape(-1, vocab_size)
            targets = targets_dev.reshape(-1)
            all_probs.append(probs)
            all_targets.append(targets)
    model.train()
    if not all_probs:
        raise ValueError("val pass produced zero batches; check n_val_batches")

    probs_cat = torch.cat(all_probs, dim=0)
    targets_cat = torch.cat(all_targets, dim=0)
    if probs_cat.shape[0] == 0:
        raise ValueError("val pass produced zero tokens; check batch_size and n_val_batches")

    ms = compute_metric_set(probs_cat, targets_cat, vocab_size)
    return {
        "val_nll": ms.nll,
        "val_ece": ms.ece,
        "val_brier": ms.brier,
        "val_rps": ms.rps,
        "val_dir_acc": ms.dir_acc,
        "val_top1": ms.top1,
        "val_top3": ms.top3,
    }


def _grad_norm(model: PriceSpaceLLM) -> float:
    total = 0.0
    for p in model.parameters():
        if p.grad is not None:
            total += float((p.grad.detach() ** 2).sum().item())
    return math.sqrt(total)


def run_training(
    *,
    tokens: list[int],
    trainer_cfg: TrainerConfig,
    model_cfg: TransformerConfig,
    emitter: StrictSignalEmitter,
    run_id: str,
    checkpoint_dir: Path,
    device: str = "cpu",
) -> TrainerResult:
    """Fit model on `tokens`; emit every declared training tag; write checkpoints.

    Every training scalar (train_loss, lr, grad_norm, throughput) lands in the
    SDD JSONL trace via TRAINING_STEP_COMPLETED emissions. Every checkpoint's
    val metrics land in CHECKPOINT_WRITTEN emissions. That trace IS the log;
    downstream plotting reads `logs/{run_id}/signals.jsonl`.
    """
    train_tokens, val_tokens = split_tokens(tokens, trainer_cfg.train_frac)
    generator = torch.Generator()
    generator.manual_seed(trainer_cfg.seed)
    torch.manual_seed(trainer_cfg.seed)

    train_sampler = WindowSampler(
        train_tokens,
        context_len=model_cfg.context_len,
        batch_size=trainer_cfg.batch_size,
        generator=generator,
    )
    val_generator = torch.Generator()
    val_generator.manual_seed(trainer_cfg.seed + 1)
    val_sampler = WindowSampler(
        val_tokens,
        context_len=model_cfg.context_len,
        batch_size=trainer_cfg.batch_size,
        generator=val_generator,
    )

    # Sprint 051 blocker #4: model + batch tensors live on `device`. Sampler
    # generator stays on CPU (integer index sampling); every batch's inputs and
    # targets move to device inside the loop before the forward pass.
    torch_device = torch.device(device)
    model = PriceSpaceLLM(model_cfg).to(torch_device)
    optimizer = torch.optim.Adam(model.parameters(), lr=trainer_cfg.lr)

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    n_checkpoints = 0
    final_loss = float("nan")
    total_train_loss = 0.0
    n_steps_done = 0

    for step in range(1, trainer_cfg.n_steps + 1):
        step_t0 = time.monotonic()
        batch: WindowBatch = train_sampler.sample()
        # Sprint 041: emit the first-batch start position from the sampler, per prior review §4.1.
        # Payload documents this as "first window in the batch"; other batch entries carry
        # different starts, uploaded to W&B only at the sink layer per Sprint 040.
        emitter.emit(
            "WINDOW_SAMPLED",
            run_id=run_id,
            start_position=int(batch.starts[0]),
            context_len=str(model_cfg.context_len),
        )
        inputs = batch.inputs.to(torch_device)
        targets = batch.targets.to(torch_device)
        logits = model(inputs)
        loss = F.cross_entropy(
            logits.reshape(-1, model_cfg.vocab_size),
            targets.reshape(-1),
        )
        train_loss = float(loss.item())

        if math.isnan(train_loss) or math.isinf(train_loss):
            emitter.emit(
                "TRAINING_DIVERGED",
                run_id=run_id,
                step=step,
                train_loss=train_loss if not math.isnan(train_loss) else 0.0,
                grad_norm=0.0,
                val_nll_at_last_eval=float("nan"),
                reason="nan_loss",
            )
            raise TrainingDiverged(f"NaN/Inf loss at step {step}")

        optimizer.zero_grad(set_to_none=True)
        loss.backward()  # type: ignore[no-untyped-call]
        grad_norm = _grad_norm(model)
        if grad_norm > trainer_cfg.grad_clip * 10:
            emitter.emit(
                "TRAINING_DIVERGED",
                run_id=run_id,
                step=step,
                train_loss=train_loss,
                grad_norm=grad_norm,
                val_nll_at_last_eval=float("nan"),
                reason="gradient_explosion",
            )
            raise TrainingDiverged(f"grad_norm {grad_norm:.3f} > clip*10 at step {step}")
        torch.nn.utils.clip_grad_norm_(model.parameters(), trainer_cfg.grad_clip)
        optimizer.step()

        step_elapsed = time.monotonic() - step_t0
        tokens_this_step = trainer_cfg.batch_size * model_cfg.context_len
        throughput = tokens_this_step / max(step_elapsed, 1e-6)

        emitter.emit(
            "TRAINING_STEP_COMPLETED",
            run_id=run_id,
            step=step,
            train_loss=train_loss,
            lr=float(trainer_cfg.lr),
            grad_norm=grad_norm,
            throughput_tokens_per_sec=throughput,
        )

        total_train_loss += train_loss
        n_steps_done += 1
        final_loss = train_loss

        if step % trainer_cfg.eval_every == 0:
            metrics = _compute_val_metrics(model, val_sampler, n_val_batches=4)
            ckpt_path = checkpoint_dir / f"{run_id}-step{step:08d}.pt"
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "step": step,
                    "config": {
                        "vocab_size": model_cfg.vocab_size,
                        "context_len": model_cfg.context_len,
                        "d_model": model_cfg.d_model,
                        "n_layers": model_cfg.n_layers,
                        "n_heads": model_cfg.n_heads,
                    },
                },
                ckpt_path,
            )
            # Point `{run_id}-latest.pt` at the newest step's checkpoint so downstream
            # sim/eval CLIs can request "latest" per Sprint 036 artifact-versioning discipline.
            latest_symlink = checkpoint_dir / f"{run_id}-latest.pt"
            if latest_symlink.exists() or latest_symlink.is_symlink():
                latest_symlink.unlink()
            os.symlink(ckpt_path.name, latest_symlink)
            emitter.emit(
                "CHECKPOINT_WRITTEN",
                run_id=run_id,
                step=step,
                path=str(ckpt_path),
                val_nll=metrics["val_nll"],
                val_ece=metrics["val_ece"],
                val_brier=metrics["val_brier"],
                val_rps=metrics["val_rps"],
                val_dir_acc=metrics["val_dir_acc"],
                val_top1=metrics["val_top1"],
                val_top3=metrics["val_top3"],
            )
            n_checkpoints += 1

    # Sprint 041: real effective-epoch count = ceil(tokens_consumed / tokens_per_epoch).
    # Random-window sampling has no natural epoch boundary; the effective count is how
    # many times the training corpus was passed over in expectation.
    tokens_consumed = n_steps_done * trainer_cfg.batch_size * model_cfg.context_len
    tokens_per_epoch = max(len(train_tokens), 1)
    effective_epoch = max(1, math.ceil(tokens_consumed / tokens_per_epoch))
    emitter.emit(
        "EPOCH_COMPLETED",
        run_id=run_id,
        epoch=effective_epoch,
        mean_train_loss=total_train_loss / max(n_steps_done, 1),
        n_steps=n_steps_done,
    )

    return TrainerResult(
        run_id=run_id,
        final_step=n_steps_done,
        final_train_loss=final_loss,
        n_checkpoints=n_checkpoints,
        n_parameters=model.num_parameters(),
        checkpoint_dir=str(checkpoint_dir),
        elapsed_seconds=time.monotonic() - t0,
    )


# Sprint 053: market-state training path -------------------------------------


def _split_artifact(
    artifact: TokenizedArtifact, train_frac: float
) -> tuple[TokenizedArtifact, TokenizedArtifact]:
    """Contiguous split of a TokenizedArtifact on the time axis."""
    if not 0.0 < train_frac < 1.0:
        raise ValueError(f"train_frac must be in (0, 1); got {train_frac}")
    t = artifact.targets.shape[0]
    n_train = int(t * train_frac)
    train = TokenizedArtifact(
        features={k: v[:n_train] for k, v in artifact.features.items()},
        targets=artifact.targets[:n_train],
        vol=artifact.vol[:n_train],
        timestamps=artifact.timestamps[:n_train],
        is_overnight_gap=(
            artifact.is_overnight_gap[:n_train] if artifact.is_overnight_gap is not None else None
        ),
        mask=artifact.mask[:n_train],
        channel_names=artifact.channel_names,
        meta=artifact.meta,
    )
    val = TokenizedArtifact(
        features={k: v[n_train:] for k, v in artifact.features.items()},
        targets=artifact.targets[n_train:],
        vol=artifact.vol[n_train:],
        timestamps=artifact.timestamps[n_train:],
        is_overnight_gap=(
            artifact.is_overnight_gap[n_train:] if artifact.is_overnight_gap is not None else None
        ),
        mask=artifact.mask[n_train:],
        channel_names=artifact.channel_names,
        meta=artifact.meta,
    )
    return train, val


def _compute_val_metrics_feats(
    model: MarketStateTransformer,
    val_sampler: WindowSamplerFeats,
    n_val_batches: int,
) -> dict[str, float]:
    """Val pass over the market-state sampler; returns the same seven metrics
    the bucket-ID `_compute_val_metrics` produces."""
    from price_space_llm.evaluation.metrics import compute_metric_set

    model.eval()
    val_device = next(model.parameters()).device
    vocab_size = model.config.vocab_size
    all_probs: list[torch.Tensor] = []
    all_targets: list[torch.Tensor] = []
    with torch.no_grad():
        for _ in range(n_val_batches):
            batch: WindowBatchFeats = val_sampler.sample()
            feats = {k: v.to(val_device) for k, v in batch.feats.items()}
            targets_dev = batch.targets.to(val_device)
            logits = model(feats)
            probs = F.softmax(logits, dim=-1).reshape(-1, vocab_size)
            targets = targets_dev.reshape(-1)
            # Filter -100 targets before computing metrics; ignore_index style.
            keep = targets != -100
            all_probs.append(probs[keep])
            all_targets.append(targets[keep])
    model.train()
    probs_cat = torch.cat(all_probs, dim=0)
    targets_cat = torch.cat(all_targets, dim=0)
    if probs_cat.shape[0] == 0:
        raise ValueError("val pass produced zero non-ignored tokens")
    ms = compute_metric_set(probs_cat, targets_cat, vocab_size)
    return {
        "val_nll": ms.nll,
        "val_ece": ms.ece,
        "val_brier": ms.brier,
        "val_rps": ms.rps,
        "val_dir_acc": ms.dir_acc,
        "val_top1": ms.top1,
        "val_top3": ms.top3,
    }


def run_training_feats(
    *,
    artifact: TokenizedArtifact,
    trainer_cfg: TrainerConfig,
    model_cfg: MarketStateTransformerConfig,
    emitter: StrictSignalEmitter,
    run_id: str,
    checkpoint_dir: Path,
    device: str = "cpu",
) -> TrainerResult:
    """Fit `MarketStateTransformer` on the per-channel feats path.

    Same emit surface as `run_training`: WINDOW_SAMPLED per step, TRAINING_STEP_COMPLETED
    per step, CHECKPOINT_WRITTEN at every eval, EPOCH_COMPLETED at close, TRAINING_DIVERGED
    on NaN/grad-explosion. Reuses `TrainerConfig`/`TrainerResult`/`TrainingDiverged`.
    """
    train_artifact, val_artifact = _split_artifact(artifact, trainer_cfg.train_frac)
    generator = torch.Generator()
    generator.manual_seed(trainer_cfg.seed)
    torch.manual_seed(trainer_cfg.seed)

    train_sampler = WindowSamplerFeats(
        train_artifact,
        context_len=model_cfg.context_len,
        batch_size=trainer_cfg.batch_size,
        generator=generator,
    )
    val_generator = torch.Generator()
    val_generator.manual_seed(trainer_cfg.seed + 1)
    val_sampler = WindowSamplerFeats(
        val_artifact,
        context_len=model_cfg.context_len,
        batch_size=trainer_cfg.batch_size,
        generator=val_generator,
    )

    torch_device = torch.device(device)
    model = MarketStateTransformer(model_cfg).to(torch_device)
    optimizer = torch.optim.Adam(model.parameters(), lr=trainer_cfg.lr)

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    n_checkpoints = 0
    final_loss = float("nan")
    total_train_loss = 0.0
    n_steps_done = 0

    for step in range(1, trainer_cfg.n_steps + 1):
        step_t0 = time.monotonic()
        batch = train_sampler.sample()
        emitter.emit(
            "WINDOW_SAMPLED",
            run_id=run_id,
            start_position=int(batch.starts[0]),
            context_len=str(model_cfg.context_len),
        )
        feats = {k: v.to(torch_device) for k, v in batch.feats.items()}
        targets = batch.targets.to(torch_device)
        logits = model(feats)
        loss = F.cross_entropy(
            logits.reshape(-1, model_cfg.vocab_size),
            targets.reshape(-1),
            ignore_index=-100,
        )
        train_loss = float(loss.item())

        if math.isnan(train_loss) or math.isinf(train_loss):
            emitter.emit(
                "TRAINING_DIVERGED",
                run_id=run_id,
                step=step,
                train_loss=train_loss if not math.isnan(train_loss) else 0.0,
                grad_norm=0.0,
                val_nll_at_last_eval=float("nan"),
                reason="nan_loss",
            )
            raise TrainingDiverged(f"NaN/Inf loss at step {step}")

        optimizer.zero_grad(set_to_none=True)
        loss.backward()  # type: ignore[no-untyped-call]
        grad_norm = _grad_norm_generic(model)
        if grad_norm > trainer_cfg.grad_clip * 10:
            emitter.emit(
                "TRAINING_DIVERGED",
                run_id=run_id,
                step=step,
                train_loss=train_loss,
                grad_norm=grad_norm,
                val_nll_at_last_eval=float("nan"),
                reason="gradient_explosion",
            )
            raise TrainingDiverged(f"grad_norm {grad_norm:.3f} > clip*10 at step {step}")
        torch.nn.utils.clip_grad_norm_(model.parameters(), trainer_cfg.grad_clip)
        optimizer.step()

        step_elapsed = time.monotonic() - step_t0
        tokens_this_step = trainer_cfg.batch_size * model_cfg.context_len
        throughput = tokens_this_step / max(step_elapsed, 1e-6)
        emitter.emit(
            "TRAINING_STEP_COMPLETED",
            run_id=run_id,
            step=step,
            train_loss=train_loss,
            lr=float(trainer_cfg.lr),
            grad_norm=grad_norm,
            throughput_tokens_per_sec=throughput,
        )
        total_train_loss += train_loss
        n_steps_done += 1
        final_loss = train_loss

        if step % trainer_cfg.eval_every == 0:
            metrics = _compute_val_metrics_feats(model, val_sampler, n_val_batches=4)
            ckpt_path = checkpoint_dir / f"{run_id}-step{step:08d}.pt"
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "step": step,
                    "config": {
                        "vocab_size": model_cfg.vocab_size,
                        "context_len": model_cfg.context_len,
                        "d_model": model_cfg.d_model,
                        "n_layers": model_cfg.n_layers,
                        "n_heads": model_cfg.n_heads,
                        "channel_dims": model_cfg.channel_dims,
                    },
                },
                ckpt_path,
            )
            latest_symlink = checkpoint_dir / f"{run_id}-latest.pt"
            if latest_symlink.exists() or latest_symlink.is_symlink():
                latest_symlink.unlink()
            os.symlink(ckpt_path.name, latest_symlink)
            emitter.emit(
                "CHECKPOINT_WRITTEN",
                run_id=run_id,
                step=step,
                path=str(ckpt_path),
                val_nll=metrics["val_nll"],
                val_ece=metrics["val_ece"],
                val_brier=metrics["val_brier"],
                val_rps=metrics["val_rps"],
                val_dir_acc=metrics["val_dir_acc"],
                val_top1=metrics["val_top1"],
                val_top3=metrics["val_top3"],
            )
            n_checkpoints += 1

    tokens_consumed = n_steps_done * trainer_cfg.batch_size * model_cfg.context_len
    tokens_per_epoch = max(train_artifact.targets.shape[0], 1)
    effective_epoch = max(1, math.ceil(tokens_consumed / tokens_per_epoch))
    emitter.emit(
        "EPOCH_COMPLETED",
        run_id=run_id,
        epoch=effective_epoch,
        mean_train_loss=total_train_loss / max(n_steps_done, 1),
        n_steps=n_steps_done,
    )

    return TrainerResult(
        run_id=run_id,
        final_step=n_steps_done,
        final_train_loss=final_loss,
        n_checkpoints=n_checkpoints,
        n_parameters=model.num_parameters(),
        checkpoint_dir=str(checkpoint_dir),
        elapsed_seconds=time.monotonic() - t0,
    )


def _grad_norm_generic(model: nn.Module) -> float:
    total = 0.0
    for p in model.parameters():
        if p.grad is not None:
            total += float((p.grad.detach() ** 2).sum().item())
    return math.sqrt(total)
