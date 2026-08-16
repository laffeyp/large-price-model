#!/usr/bin/env python3
"""Normalization-drift diagnostic CLI (Sprint 055).

Reads a training + a holdout Sprint 052 `.pt` artifact and a Sprint 054 frozen
normalizer, applies the normalizer to both, and emits one
`NORMALIZER_DRIFT_MEASURED` per (channel, feature_index) with train/holdout
mean + std + KS statistic + p-value. Best-effort PNG per feature to
`--output-dir`.

Product-spec-v4.md line 251: "plot the normalized-feature distribution on the
holdout against training. Track it as a failure mode."
"""

import argparse
import hashlib
import sys
import traceback
from pathlib import Path

from price_space_llm.model.dataset import load_tokens_pt
from price_space_llm.normalizer import (
    load_frozen_normalizer,
    measure_normalizer_drift,
)
from price_space_llm.script_harness import script_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="measure_drift")
    parser.add_argument("--train-tokens-pt", type=Path, required=True)
    parser.add_argument("--holdout-tokens-pt", type=Path, required=True)
    parser.add_argument(
        "--normalizer",
        type=Path,
        default=Path("artifacts/tokenizer/normalizers.latest.pt"),
        help="Sprint 054 frozen-normalizer artifact.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="PNGs land here. Defaults to artifacts/{run_id}/drift/.",
    )
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    for label, path in (
        ("train-tokens-pt", args.train_tokens_pt),
        ("holdout-tokens-pt", args.holdout_tokens_pt),
        ("normalizer", args.normalizer),
    ):
        if not path.exists():
            print(f"measure_drift: {label} not found: {path}", file=sys.stderr)
            return 1

    run_id = f"drift-{args.train_tokens_pt.stem}-vs-{args.holdout_tokens_pt.stem}-{args.seed:016d}"
    output_dir = args.output_dir or Path("artifacts") / run_id / "drift"

    # Hashes: config_hash keyed to normalizer bytes (its shape defines the diagnostic);
    # data_hash keyed to the concatenation of the two artifact hashes.
    normalizer_bytes = args.normalizer.read_bytes()
    config_hash = hashlib.sha256(normalizer_bytes).hexdigest()
    train_h = hashlib.sha256(args.train_tokens_pt.read_bytes()).hexdigest()
    holdout_h = hashlib.sha256(args.holdout_tokens_pt.read_bytes()).hexdigest()
    data_hash = hashlib.sha256(f"{train_h}|{holdout_h}".encode()).hexdigest()

    n_measured = 0
    with script_session(
        run_kind="eval",
        run_id=run_id,
        config_hash=config_hash,
        data_hash=data_hash,
        seed=args.seed,
        logs_dir=args.logs_dir,
    ) as (emitter, sink_path):
        try:
            train_artifact = load_tokens_pt(args.train_tokens_pt)
            holdout_artifact = load_tokens_pt(args.holdout_tokens_pt)
            normalizer = load_frozen_normalizer(args.normalizer)
            n_measured = measure_normalizer_drift(
                train_artifact=train_artifact,
                holdout_artifact=holdout_artifact,
                normalizer=normalizer,
                emitter=emitter,
                run_id=run_id,
                plot_dir=output_dir,
            )
        except (FileNotFoundError, ValueError):
            traceback.print_exc(file=sys.stderr)
            return 1

    print(
        f"measure_drift: {n_measured} features measured; plots={output_dir}; trace={sink_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
