#!/usr/bin/env python3
"""Alignment CLI -- reads cached bars, runs the 15-min UTC RTH join_asof, writes parquet.

Reads `data/manifests/channel_coverage.json` for the accepted-channel
set. For each accepted (channel, symbol), loads the cached raw response
under `data/raw/`, converts to a bar DataFrame, joins into a fixed
15-min UTC RTH grid keyed on `known_at` (strategy=backward -- the
alignment invariant per tech-arch §17), and writes the wide aligned
DataFrame to `data/aligned/{run_id}.parquet`.

Emits the four align-category signals per v0.3 vocabulary.
"""

import argparse
import hashlib
import sys
import traceback
from pathlib import Path

from price_space_llm.alignment import enumerate_months, run_alignment
from price_space_llm.script_harness import script_session


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
    parser.add_argument("--month", help="YYYY-MM (single-month shorthand)")
    parser.add_argument("--start-month", help="YYYY-MM (inclusive start; use with --end-month)")
    parser.add_argument("--end-month", help="YYYY-MM (inclusive end; use with --start-month)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    if args.month and (args.start_month or args.end_month):
        print(
            "align: pass either --month OR --start-month/--end-month, not both",
            file=sys.stderr,
        )
        return 2
    if not args.month and not (args.start_month and args.end_month):
        print(
            "align: pass --month=YYYY-MM OR --start-month=YYYY-MM --end-month=YYYY-MM",
            file=sys.stderr,
        )
        return 2

    if args.month:
        months = [args.month]
        range_tag = args.month
    else:
        try:
            months = enumerate_months(args.start_month, args.end_month)
        except ValueError as ex:
            print(f"align: {ex}", file=sys.stderr)
            return 2
        range_tag = f"{args.start_month}-{args.end_month}"

    if not args.manifest.exists():
        print(f"align: manifest not found: {args.manifest}", file=sys.stderr)
        return 1

    run_id = f"align-{range_tag}-{args.seed:016d}"
    output_path = args.output_dir / f"{run_id}.parquet"

    manifest_bytes = args.manifest.read_bytes()
    config_hash = hashlib.sha256(f"{','.join(months)}:{manifest_bytes.hex()}".encode()).hexdigest()
    data_hash = hashlib.sha256(manifest_bytes).hexdigest()

    result = None
    with script_session(
        run_kind="align",
        run_id=run_id,
        config_hash=config_hash,
        data_hash=data_hash,
        seed=args.seed,
        logs_dir=args.logs_dir,
    ) as (emitter, sink_path):
        try:
            result = run_alignment(
                manifest_path=args.manifest,
                cache_dir=args.cache_dir,
                months=months,
                output_path=output_path,
                emitter=emitter,
                run_id=run_id,
            )
        except (FileNotFoundError, ValueError):
            traceback.print_exc(file=sys.stderr)
            return 1

    if result is not None:
        missing_summary = ", ".join(
            f"{k}={v:.3f}" for k, v in result.missing_fractions_per_channel.items()
        )
        print(
            f"align: {result.total_rows} rows in {result.elapsed_seconds:.2f}s; "
            f"missing_fractions=[{missing_summary}]; output={result.output_path}; "
            f"trace={sink_path}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
