#!/usr/bin/env python3
"""Append one row to experiments/logbook.csv per tech-arch §13.

Typical use: after a training run completes, `scripts/register_run.py` writes
one row summarising the run's metadata + val metrics + (optional) held-out
Sharpe. The CSV is the operator-facing manifest of every registered run.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from price_space_llm.git import git_sha
from price_space_llm.logbook import DEFAULT_LOGBOOK_PATH, LogbookEntry, append_run


def _current_branch() -> str:
    """Best-effort git branch name; returns 'unknown' on failure or detached HEAD."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "unknown"
    except (FileNotFoundError, OSError):
        pass
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="register_run")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--target", required=True, help="e.g. SPY")
    parser.add_argument("--model-size", default="custom")
    parser.add_argument("--context-len", type=int, required=True)
    parser.add_argument("--patch-size", type=int, default=1)
    parser.add_argument("--head-type", default="categorical")
    parser.add_argument("--n-buckets", type=int, default=32)
    parser.add_argument("--train-loss", type=float, required=True)
    parser.add_argument("--val-nll", type=float, required=True)
    parser.add_argument("--val-ece", type=float, default=float("nan"))
    parser.add_argument("--val-brier", type=float, default=float("nan"))
    parser.add_argument("--val-rps", type=float, default=float("nan"))
    parser.add_argument("--val-dir-acc", type=float, default=float("nan"))
    parser.add_argument("--held-out-sharpe", type=float, default=float("nan"))
    parser.add_argument("--held-out-sharpe-se", type=float, default=float("nan"))
    parser.add_argument("--lambda-risk", type=float, default=0.0)
    parser.add_argument("--alpha-mag-weight", type=float, default=0.0)
    parser.add_argument("--touched-test", action="store_true")
    parser.add_argument("--notes", default="")
    parser.add_argument("--logbook-path", type=Path, default=DEFAULT_LOGBOOK_PATH)
    args = parser.parse_args(argv)

    entry = LogbookEntry(
        date=datetime.now(UTC).date().isoformat(),
        run_id=args.run_id,
        branch=_current_branch(),
        git_sha=git_sha() or "unknown",
        notes=args.notes,
        target=args.target,
        model_size=args.model_size,
        context_len=args.context_len,
        patch_size=args.patch_size,
        head_type=args.head_type,
        n_buckets=args.n_buckets,
        train_loss=args.train_loss,
        val_nll=args.val_nll,
        val_ece=args.val_ece,
        val_brier=args.val_brier,
        val_rps=args.val_rps,
        val_dir_acc=args.val_dir_acc,
        held_out_sharpe=args.held_out_sharpe,
        held_out_sharpe_se=args.held_out_sharpe_se,
        lambda_risk=args.lambda_risk,
        alpha_mag_weight=args.alpha_mag_weight,
        touched_test=args.touched_test,
    )
    append_run(entry, args.logbook_path)
    print(f"register_run: appended {args.run_id} to {args.logbook_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
