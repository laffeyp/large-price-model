#!/usr/bin/env python3
"""Simulator CLI — Sprint 092 skeleton.

Reads an aligned parquet, walks bars over the requested date range, emits
`SIM_RUN_STARTED` / `BAR_PROCESSED` / `SIM_RUN_COMPLETED`. No model, no
decisions, no positions, no trades — Sprint 093 wires those.

Held-out safety: `--split test` on a held-out aligned parquet requires
`--i-know-this-is-a-test-look` per the Sprint 065 `heldout_guard`
convention. Same shape as `scripts/evaluate.py`.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

from price_space_llm.heldout_guard import (
    HeldoutReadRefused,
    UnrecognizedArtifactShape,
    guard_heldout_parquet,
)
from price_space_llm.script_harness import script_session
from price_space_llm.simulation import run_simulation_skeleton


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simulate")
    parser.add_argument("--aligned", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "val", "test"), default="train")
    parser.add_argument("--date-range-start", type=date.fromisoformat, required=True)
    parser.add_argument("--date-range-end", type=date.fromisoformat, required=True)
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--i-know-this-is-a-test-look",
        action="store_true",
        help="Sprint 065 acknowledgment for held-out parquet reads.",
    )
    parser.add_argument(
        "--checkpoint-run-id",
        default="skeleton-no-checkpoint",
        help="Sprint 101: training run_id whose checkpoint drives this sim.",
    )
    parser.add_argument(
        "--cost-calibration-run-id",
        default="skeleton-no-calibration",
        help="Sprint 101: the cost-calibration run_id (skeleton uses a placeholder).",
    )
    args = parser.parse_args(argv)

    if not args.aligned.exists():
        print(f"simulate: aligned parquet not found: {args.aligned}", file=sys.stderr)
        return 1

    # Sprint 092: guard the read; skeleton needs the held-out ack only when the
    # filename encodes a heldout range. Training-window paths pass through.
    try:
        guard_heldout_parquet(
            args.aligned, allow_test_look=args.i_know_this_is_a_test_look
        )
    except HeldoutReadRefused as ex:
        print(f"simulate: heldout read refused: {ex}", file=sys.stderr)
        return 2
    except UnrecognizedArtifactShape as ex:
        print(f"simulate: unrecognized artifact shape: {ex}", file=sys.stderr)
        return 3

    span = f"{args.date_range_start.isoformat()}_{args.date_range_end.isoformat()}"
    run_id = f"simulate-{args.aligned.stem}-{args.split}-{span}-{args.seed:016d}"
    config_hash = hashlib.sha256(
        f"{args.split}:{args.date_range_start}:{args.date_range_end}".encode()
    ).hexdigest()
    data_hash = hashlib.sha256(args.aligned.read_bytes()).hexdigest()

    with script_session(
        run_kind="simulate",
        run_id=run_id,
        config_hash=config_hash,
        data_hash=data_hash,
        seed=args.seed,
        logs_dir=args.logs_dir,
    ) as (emitter, sink_path):
        result = run_simulation_skeleton(
            args.aligned,
            split=args.split,
            date_range_start=args.date_range_start,
            date_range_end=args.date_range_end,
            emitter=emitter,
            run_id=run_id,
            checkpoint_step=0,
            checkpoint_run_id=args.checkpoint_run_id,
            cost_calibration_run_id=args.cost_calibration_run_id,
        )

    skipped_note = (
        f"; n_bars_skipped_undefined_vol={result.n_bars_skipped_undefined_vol}"
        if result.n_bars_skipped_undefined_vol
        else ""
    )
    print(
        f"simulate: skeleton over {result.n_bars_processed} bars "
        f"({args.date_range_start}..{args.date_range_end}); "
        f"n_trades={result.n_trades}{skipped_note}; trace={sink_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
