#!/usr/bin/env python3
"""Alignment CLI — reads cached bars, runs the 15-min UTC RTH join_asof, writes parquet.

Reads `data/manifests/channel_coverage.json` for the accepted-channel
set. For each accepted (channel, symbol), loads the cached raw response
under `data/raw/`, converts to a bar DataFrame, joins into a fixed
15-min UTC RTH grid keyed on `known_at` (strategy=backward — the
alignment invariant per tech-arch §17), and writes the wide aligned
DataFrame to `data/aligned/{run_id}.parquet`.

Emits the four align-category signals per v0.3 vocabulary.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import traceback
from pathlib import Path

from price_space_llm.alignment import run_alignment
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
    parser = argparse.ArgumentParser(prog="align")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/manifests/channel_coverage.json"),
    )
    parser.add_argument("--cache-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/aligned"))
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        print(f"align: manifest not found: {args.manifest}", file=sys.stderr)
        return 1

    run_id = f"align-{args.month}-{args.seed:016d}"
    sink_path = args.logs_dir / run_id / "signals.jsonl"
    output_path = args.output_dir / f"{run_id}.parquet"

    emitter = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink_path)

    manifest_bytes = args.manifest.read_bytes()
    config_hash = hashlib.sha256(f"{args.month}:{manifest_bytes.hex()}".encode()).hexdigest()
    data_hash = hashlib.sha256(manifest_bytes).hexdigest()

    exit_code = 0
    result = None
    with process_session(
        run_kind="align",
        config_hash=config_hash,
        git_sha=_git_sha(),
        data_hash=data_hash,
        seed=args.seed,
        run_id=run_id,
        emitter=emitter,
    ):
        try:
            result = run_alignment(
                manifest_path=args.manifest,
                cache_dir=args.cache_dir,
                month=args.month,
                output_path=output_path,
                emitter=emitter,
                run_id=run_id,
            )
        except (FileNotFoundError, ValueError):
            traceback.print_exc(file=sys.stderr)
            return 1

    if result is not None:
        missing_summary = ", ".join(
            f"{k}={v:.3f}" for k, v in result["missing_fractions_per_channel"].items()
        )
        print(
            f"align: {result['total_rows']} rows in {result['elapsed_seconds']:.2f}s; "
            f"missing_fractions=[{missing_summary}]; output={result['output_path']}; "
            f"trace={sink_path}",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
