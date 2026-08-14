#!/usr/bin/env python3
"""Training CLI -- reads tokens parquet + config, runs the transformer trainer.

Emits the full training tag surface: WINDOW_SAMPLED per window,
TRAINING_STEP_COMPLETED per step, CHECKPOINT_WRITTEN at every eval,
EPOCH_COMPLETED at end, TRAINING_DIVERGED on NaN or grad-explosion.
"""

import argparse
import hashlib
import sys
import traceback
from pathlib import Path

from price_space_llm.config import ConfigValidationFailed, load_config
from price_space_llm.git import git_sha
from price_space_llm.model import (
    TransformerConfig,
    load_tokens,
    run_training,
)
from price_space_llm.model.trainer import TrainerConfig, TrainingDiverged
from price_space_llm.script_harness import script_session
from price_space_llm.wandb_sink import WandbConfig, WandbSink


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="train")
    parser.add_argument(
        "--tokens",
        type=Path,
        required=True,
        help="Path to a tokens parquet from `scripts/bucketize.py`.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiment/v1.json"),
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=Path("artifacts/checkpoints"),
    )
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-steps", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--eval-every", type=int, default=25)
    parser.add_argument(
        "--wandb",
        choices=("off", "offline", "online"),
        default="off",
        help="off = no W&B; offline = writes wandb/ locally; online needs WANDB_API_KEY.",
    )
    parser.add_argument(
        "--wandb-project",
        default="price-space-llm",
        help="W&B project name; matches WORKING_AGREEMENT.md § Weights & Biases.",
    )
    parser.add_argument(
        "--wandb-dir",
        type=Path,
        default=Path("wandb"),
        help="On-disk root for W&B run directories (offline mode).",
    )
    args = parser.parse_args(argv)

    if not args.tokens.exists():
        print(f"train: tokens parquet not found: {args.tokens}", file=sys.stderr)
        return 1

    run_id = f"train-{args.tokens.stem}-s{args.n_steps}-{args.seed:016d}"
    # Sprint 041: config_hash keyed to the resolved experiment config file; data_hash
    # keyed to the tokens parquet. Previously both hashed tokens_bytes -- silently
    # broke reproducibility across configs with the same input.
    if not args.config.exists():
        print(f"train: config not found: {args.config}", file=sys.stderr)
        return 1
    config_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()
    data_hash = hashlib.sha256(args.tokens.read_bytes()).hexdigest()

    result = None
    with script_session(
        run_kind="train",
        run_id=run_id,
        config_hash=config_hash,
        data_hash=data_hash,
        seed=args.seed,
        logs_dir=args.logs_dir,
    ) as (emitter, sink_path):
        try:
            config_result = load_config(
                args.config, emitter=emitter, run_id=run_id, git_sha=git_sha()
            )
        except ConfigValidationFailed as ex:
            print(f"train: config invalid: {ex}", file=sys.stderr)
            return 1
        cfg = config_result.config

        tokens = load_tokens(args.tokens, cfg.target_symbol)
        if len(tokens) < cfg.context_len + 2:
            print(
                f"train: only {len(tokens)} tokens; need at least {cfg.context_len + 2}",
                file=sys.stderr,
            )
            return 1

        model_cfg = TransformerConfig(
            vocab_size=cfg.n_buckets,
            context_len=cfg.context_len,
        )
        trainer_cfg = TrainerConfig(
            n_steps=args.n_steps,
            batch_size=args.batch_size,
            lr=args.lr,
            eval_every=args.eval_every,
            seed=args.seed,
        )
        wandb_sink_context: WandbSink | None
        if args.wandb == "off":
            wandb_sink_context = None
        else:
            wandb_cfg = WandbConfig(
                project=args.wandb_project,
                run_name=run_id,
                config={
                    "vocab_size": model_cfg.vocab_size,
                    "context_len": model_cfg.context_len,
                    "d_model": model_cfg.d_model,
                    "n_layers": model_cfg.n_layers,
                    "n_heads": model_cfg.n_heads,
                    "n_steps": trainer_cfg.n_steps,
                    "batch_size": trainer_cfg.batch_size,
                    "lr": trainer_cfg.lr,
                    "eval_every": trainer_cfg.eval_every,
                    "seed": trainer_cfg.seed,
                },
                mode="offline" if args.wandb == "offline" else "online",
                dir=args.wandb_dir,
            )
            wandb_sink_context = WandbSink(wandb_cfg, emitter, run_id=run_id)

        try:
            if wandb_sink_context is None:
                result = run_training(
                    tokens=tokens,
                    trainer_cfg=trainer_cfg,
                    model_cfg=model_cfg,
                    emitter=emitter,
                    run_id=run_id,
                    checkpoint_dir=args.checkpoint_dir,
                )
            else:
                with wandb_sink_context as sink:
                    result = run_training(
                        tokens=tokens,
                        trainer_cfg=trainer_cfg,
                        model_cfg=model_cfg,
                        emitter=emitter,
                        run_id=run_id,
                        checkpoint_dir=args.checkpoint_dir,
                        wandb_sink=sink,
                    )
        except TrainingDiverged as ex:
            print(f"train: diverged: {ex}", file=sys.stderr)
            return 2
        except (FileNotFoundError, ValueError):
            traceback.print_exc(file=sys.stderr)
            return 1

    if result is not None:
        print(
            f"train: {result.final_step} steps in {result.elapsed_seconds:.2f}s; "
            f"final_train_loss={result.final_train_loss:.4f}; "
            f"checkpoints={result.n_checkpoints}; "
            f"params={result.n_parameters}; trace={sink_path}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
