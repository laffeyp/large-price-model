#!/usr/bin/env python3
"""Feature-computation CLI over an aligned parquet.

Reads `data/aligned/{align_run_id}.parquet`, computes strictly-causal
features per tech-arch §6, writes `data/features/{run_id}.parquet`.
Emits FEATURE_COMPUTED / FEATURE_COMPUTATION_FAILED per (channel,
feature, timestamp) with honest reason enums on failures.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import traceback
from pathlib import Path

from price_space_llm.features import run_feature_pipeline
from price_space_llm.signals import (
    StrictSignalEmitter,
    load_vocabulary,
    process_session,
)


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "0" * 40


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
    args = parser.parse_args(argv)

    if not args.aligned.exists():
        print(f"features: aligned parquet not found: {args.aligned}", file=sys.stderr)
        return 1

    run_id = f"features-{args.aligned.stem}-{args.seed:016d}"
    sink_path = args.logs_dir / run_id / "signals.jsonl"
    output_path = args.output_dir / f"{run_id}.parquet"

    emitter = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink_path)
    aligned_bytes = args.aligned.read_bytes()
    config_hash = hashlib.sha256(aligned_bytes).hexdigest()
    data_hash = hashlib.sha256(aligned_bytes).hexdigest()

    result = None
    with process_session(
        run_kind="train",  # v0.3 has no `feature` run_kind; train covers upstream prep.
        config_hash=config_hash,
        git_sha=_git_sha(),
        data_hash=data_hash,
        seed=args.seed,
        run_id=run_id,
        emitter=emitter,
    ):
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
            f"features: {result['n_features_emitted']} emitted, {result['n_failures']} failed "
            f"in {result['elapsed_seconds']:.2f}s; output={result['output_path']}; "
            f"trace={sink_path}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
