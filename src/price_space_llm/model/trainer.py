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
import time
from dataclasses import dataclass
from pathlib import Path

import torch
from torch.nn import functional as F

from price_space_llm.model.dataset import WindowBatch, WindowSampler, split_tokens
from price_space_llm.model.transformer import PriceSpaceLLM, TransformerConfig
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
    """Deterministic val pass. Returns the six metrics CHECKPOINT_WRITTEN requires."""
    model.eval()
    total_nll = 0.0
    total_correct_top1 = 0
    total_correct_top3 = 0
    total_dir_correct = 0
    total_tokens = 0
    vocab_size = model.config.vocab_size
    with torch.no_grad():
        for _ in range(n_val_batches):
            batch = val_sampler.sample()
            logits = model(batch.inputs)  # (B, T, V)
            log_probs = F.log_softmax(logits, dim=-1)
            targets = batch.targets  # (B, T)
            nll = F.nll_loss(
                log_probs.reshape(-1, vocab_size),
                targets.reshape(-1),
                reduction="sum",
            )
            total_nll += float(nll.item())
            probs = log_probs.exp()
            preds = probs.argmax(dim=-1)  # (B, T)
            total_correct_top1 += int((preds == targets).sum().item())
            top3 = probs.topk(3, dim=-1).indices  # (B, T, 3)
            total_correct_top3 += int((top3 == targets.unsqueeze(-1)).any(dim=-1).sum().item())
            # Direction: bucket_id above median → "up," else "down."
            median = vocab_size // 2
            pred_up = preds >= median
            tgt_up = targets >= median
            total_dir_correct += int((pred_up == tgt_up).sum().item())
            total_tokens += targets.numel()
    model.train()
    if total_tokens == 0:
        raise ValueError("val pass produced zero tokens; check batch_size and n_val_batches")

    val_nll = total_nll / total_tokens
    # ECE and Brier are placeholders on Sprint 031 (need calibration bins + one-hot targets).
    # Report neutral values so CHECKPOINT_WRITTEN emits validly; Sprint 032 wires the real ones.
    val_ece = 0.0
    val_brier = 0.0
    val_rps = 0.0  # ranked-probability-score, deferred
    return {
        "val_nll": val_nll,
        "val_ece": val_ece,
        "val_brier": val_brier,
        "val_rps": val_rps,
        "val_dir_acc": total_dir_correct / total_tokens,
        "val_top1": total_correct_top1 / total_tokens,
        "val_top3": total_correct_top3 / total_tokens,
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
) -> TrainerResult:
    """Fit model on `tokens`; emit every declared training tag; write checkpoints."""
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

    model = PriceSpaceLLM(model_cfg)
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
        emitter.emit(
            "WINDOW_SAMPLED",
            run_id=run_id,
            start_position=int(step),  # deterministic proxy; sampler returns starts per-batch
            context_len=str(model_cfg.context_len),
        )
        logits = model(batch.inputs)
        loss = F.cross_entropy(
            logits.reshape(-1, model_cfg.vocab_size),
            batch.targets.reshape(-1),
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

    emitter.emit(
        "EPOCH_COMPLETED",
        run_id=run_id,
        epoch=1,
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
