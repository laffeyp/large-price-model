#!/usr/bin/env python3
"""Feature-computation CLI over an aligned parquet.

Reads `data/aligned/{align_run_id}.parquet`, computes strictly-causal
features per tech-arch §6, writes `data/features/{run_id}.parquet`.
Emits FEATURE_COMPUTED / FEATURE_COMPUTATION_FAILED per (channel,
feature, timestamp) with honest reason enums on failures. Also emits
CONFIG_RESOLVED at session open (Sprint 028), enforcing the tech-arch
§11.3 registration gate on lambda_risk + alpha_mag_weight.
"""

import argparse
import hashlib
import sys
import traceback
from pathlib import Path

from price_space_llm.config import ConfigValidationFailed, load_config
from price_space_llm.features import run_feature_pipeline
from price_space_llm.git import git_sha
from price_space_llm.heldout_guard import HeldoutReadRefused, guard_heldout_parquet
from price_space_llm.script_harness import script_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="features")
    parser.add_argument(
        "--aligned",
        type=Path,
        required=True,
        help="Path to an aligned parquet from `scripts/align.py`.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/features"))
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiment/v1.json"),
        help="ExperimentConfig JSON. Validated by pydantic; CONFIG_RESOLVED fires on success.",
    )
    parser.add_argument(
        "--allow-test-look",
        action="store_true",
        help="Sprint 065: acknowledge reading a held-out aligned parquet. "
        "Register the look via scripts/register_test_look.py first.",
    )
    args = parser.parse_args(argv)

    # Sprint 065: refuse to read a held-out aligned parquet without acknowledgment.
    try:
        guard_heldout_parquet(args.aligned, allow_test_look=args.allow_test_look)
    except HeldoutReadRefused as ex:
        print(f"features: {ex}", file=sys.stderr)
        return 2

    if not args.aligned.exists():
        print(f"features: aligned parquet not found: {args.aligned}", file=sys.stderr)
        return 1

    run_id = f"features-{args.aligned.stem}-{args.seed:016d}"
    output_path = args.output_dir / f"{run_id}.parquet"
    # Sprint 041: config_hash keyed to the experiment config; data_hash to the aligned parquet.
    config_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()
    data_hash = hashlib.sha256(args.aligned.read_bytes()).hexdigest()

    result = None
    with script_session(
        run_kind="train",  # v0.3 has no `feature` run_kind; train covers upstream prep.
        run_id=run_id,
        config_hash=config_hash,
        data_hash=data_hash,
        seed=args.seed,
        logs_dir=args.logs_dir,
    ) as (emitter, sink_path):
        try:
            load_config(args.config, emitter=emitter, run_id=run_id, git_sha=git_sha())
        except ConfigValidationFailed as ex:
            print(f"features: config invalid: {ex}", file=sys.stderr)
            return 1
        try:
            result = run_feature_pipeline(
                aligned_path=args.aligned,
                output_path=output_path,
                emitter=emitter,
                run_id=run_id,
            )
        except (FileNotFoundError, ValueError):
            traceback.print_exc(file=sys.stderr)
            return 1

    if result is not None:
        print(
            f"features: {result.n_features_emitted} emitted, {result.n_failures} failed "
            f"in {result.elapsed_seconds:.2f}s; output={result.output_path}; "
            f"trace={sink_path}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
