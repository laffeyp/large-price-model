#!/usr/bin/env python3
"""Register a training run into experiments/logbook.csv from its trace + eval json.

Sprint 111: closes the tracking gap surfaced during Sprint 110 close. Every
future training run should be followed by:

    scripts/register_from_trace.py \\
        --trace logs/sprintNNN-.../signals.jsonl \\
        --eval-metrics artifacts/sprintNNN-eval/metrics.json \\
        --model-size <size> --notes "sprintNNN ..."

Trace-only mode (no eval-metrics): pulls val_nll from the best CHECKPOINT_WRITTEN
in the trace; leaves ECE/Brier/RPS/dir_acc as NaN.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_trace(path: Path) -> tuple[float, float]:
    """Return (final_train_loss, best_val_nll) from a training trace."""
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    steps = [entry for entry in lines if entry.get("tag") == "TRAINING_STEP_COMPLETED"]
    ckpts = [entry for entry in lines if entry.get("tag") == "CHECKPOINT_WRITTEN"]
    final_train_loss = steps[-1]["train_loss"] if steps else float("nan")
    best_val_nll = min((c["val_nll"] for c in ckpts), default=float("nan"))
    return final_train_loss, best_val_nll


def _weighted_metrics(eval_json: Path) -> dict[str, float]:
    """Pool val metrics across regimes weighted by n_examples."""
    doc = json.loads(eval_json.read_text())
    val = doc["metrics"]["val"]
    total_n = sum(v["n_examples"] for v in val.values())
    keys = ("nll", "ece", "brier", "rps", "dir_acc")
    return {k: sum(v[k] * v["n_examples"] for v in val.values()) / total_n for k in keys}


def _run_id_from_trace(trace: Path) -> str:
    return trace.parent.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="register_from_trace")
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--eval-metrics", type=Path, default=None)
    parser.add_argument("--model-size", required=True)
    parser.add_argument("--context-len", type=int, default=64)
    parser.add_argument("--patch-size", type=int, default=1)
    parser.add_argument("--head-type", default="categorical")
    parser.add_argument("--n-buckets", type=int, default=32)
    parser.add_argument("--target", default="SPY")
    parser.add_argument("--notes", default="")
    parser.add_argument("--held-out-sharpe", type=float, default=float("nan"))
    parser.add_argument("--held-out-sharpe-se", type=float, default=float("nan"))
    parser.add_argument("--touched-test", action="store_true")
    args = parser.parse_args(argv)

    if not args.trace.exists():
        print(f"register_from_trace: trace not found: {args.trace}", file=sys.stderr)
        return 1

    final_train_loss, best_train_val_nll = _read_trace(args.trace)
    if args.eval_metrics and args.eval_metrics.exists():
        pooled = _weighted_metrics(args.eval_metrics)
    else:
        pooled = {"nll": best_train_val_nll, "ece": float("nan"),
                  "brier": float("nan"), "rps": float("nan"), "dir_acc": float("nan")}

    run_id = _run_id_from_trace(args.trace)
    cmd = [
        "uv", "run", "python", str(REPO_ROOT / "scripts" / "register_run.py"),
        "--run-id", run_id,
        "--target", args.target,
        "--model-size", args.model_size,
        "--context-len", str(args.context_len),
        "--patch-size", str(args.patch_size),
        "--head-type", args.head_type,
        "--n-buckets", str(args.n_buckets),
        "--train-loss", f"{final_train_loss:.6f}",
        "--val-nll", f"{pooled['nll']:.6f}",
        "--val-ece", f"{pooled['ece']:.6f}",
        "--val-brier", f"{pooled['brier']:.6f}",
        "--val-rps", f"{pooled['rps']:.6f}",
        "--val-dir-acc", f"{pooled['dir_acc']:.6f}",
        "--held-out-sharpe", f"{args.held_out_sharpe:.6f}",
        "--held-out-sharpe-se", f"{args.held_out_sharpe_se:.6f}",
        "--notes", args.notes,
    ]
    if args.touched_test:
        cmd.append("--touched-test")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
