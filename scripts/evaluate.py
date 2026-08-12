#!/usr/bin/env python3
"""Evaluation CLI: read checkpoint + tokens + features; compute metrics per regime; write snapshot.

Emits SESSION_INIT + CONFIG_RESOLVED + REGIME_LABELS_FROZEN +
METRIC_COMPUTED x 42 (7 metrics x 2 splits x 3 regimes) +
BUCKET_FREQUENCY_DRIFT_MEASURED + METRIC_SNAPSHOT_WRITTEN x N_splits +
SESSION_COMPLETE.
"""

import argparse
import hashlib
import sys
import traceback
from pathlib import Path

from price_space_llm.config import ConfigValidationFailed, load_config
from price_space_llm.evaluation import run_evaluation
from price_space_llm.git import git_sha
from price_space_llm.script_harness import script_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evaluate")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--tokens", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiment/v1.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to artifacts/{run_id}/.",
    )
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--train-frac", type=float, default=0.8)
    parser.add_argument("--training-start", default="2024-06-03")
    parser.add_argument("--training-end", default="2024-06-28")
    args = parser.parse_args(argv)

    for label, path in (
        ("checkpoint", args.checkpoint),
        ("tokens", args.tokens),
        ("features", args.features),
    ):
        if not path.exists():
            print(f"evaluate: {label} not found: {path}", file=sys.stderr)
            return 1

    run_id = f"evaluate-{args.checkpoint.stem}-{args.seed:016d}"
    output_dir = args.output_dir or Path("artifacts") / run_id
    checkpoint_bytes = args.checkpoint.read_bytes()
    config_hash = hashlib.sha256(checkpoint_bytes[:65536]).hexdigest()
    data_hash = hashlib.sha256(args.tokens.read_bytes()).hexdigest()

    result = None
    with script_session(
        run_kind="eval",
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
            print(f"evaluate: config invalid: {ex}", file=sys.stderr)
            return 1
        cfg = config_result.config

        try:
            result = run_evaluation(
                checkpoint_path=args.checkpoint,
                features_path=args.features,
                tokens_path=args.tokens,
                target_symbol=cfg.target_symbol,
                train_frac=args.train_frac,
                output_dir=output_dir,
                emitter=emitter,
                run_id=run_id,
                training_range_start=args.training_start,
                training_range_end=args.training_end,
            )
        except (FileNotFoundError, ValueError):
            traceback.print_exc(file=sys.stderr)
            return 1

    if result is not None:
        print(
            f"evaluate: {result.n_metric_emits} METRIC_COMPUTED in "
            f"{result.elapsed_seconds:.2f}s; snapshot={result.metrics_path}; "
            f"regime_thresholds=(low<{result.thresholds.low_threshold:.6f}, "
            f"mid<{result.thresholds.mid_threshold:.6f}); trace={sink_path}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
