#!/usr/bin/env python3
"""Sprint 118: are the baselines converged, and what is the best each can do?

The `fit_linear` / `fit_mlp` / `fit_gru` defaults (200 Adam steps, batch 32,
lr 1e-3) are smoke-test settings, not the configuration behind any reported
number. This probe answers two questions a reader of the Phase H result asks:

1. Was the linear baseline undertrained? Records the validation curve at the
   project's lr=1e-3 every 100 steps. Answer on the 2015-2022 artifact: no.
   It peaks near step 800 and overfits after (65,536 weights, 43,409 windows).
2. What is the best each baseline reaches? Sweeps lr x weight_decay, early-
   stops on the same validation windows the transformer was selected on, then
   re-runs the best config per kind at seeds 0-4.

Split matches `linear_per_regime.py` (Sprint 111): `train_frac=0.8` over the
target stream, ignore-index tokens clamped to 0, context 64, 32 buckets. The
transformer's pooled val_nll in `experiments/logbook.csv` is scored on the same
10,789 validation windows.

Training window only. The script refuses any artifact whose resolved filename
does not carry the 2015-01..2022-12 range: `heldout_guard` does not recognize
tokenized `.pt` names, so this check lives here.

Usage:
    uv run python scripts/analysis/baseline_convergence.py \
        --output reports/baseline-convergence.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from price_space_llm import baselines as B
from price_space_llm.model.dataset import load_tokens_pt

DEFAULT_TOKENS = Path(
    "data/tokenized/normalized/"
    "tokens.tokenize-features-align-2015-01-2022-12-0000000000000000-0000000000000000-0000000000000000.pt"
)
TRAINING_RANGE_MARK = "2015-01-2022-12"
VOCAB, CONTEXT = 32, 64
MAKERS = {
    "linear": lambda: B.LinearBaseline(VOCAB, CONTEXT),
    "mlp": lambda: B.MLPBaseline(VOCAB, CONTEXT),
    "gru": lambda: B.GRUBaseline(VOCAB, CONTEXT),
}
GRID = {
    "linear": {"lr": (1e-3, 3e-4), "wd": (0.0, 1e-2, 1e-1), "max_steps": 8000, "eval_every": 100},
    "mlp": {"lr": (1e-3, 3e-4), "wd": (0.0, 1e-2, 1e-1), "max_steps": 8000, "eval_every": 100},
    "gru": {"lr": (1e-3, 3e-4), "wd": (1e-1,), "max_steps": 4000, "eval_every": 200},
}
SEEDS = (0, 1, 2, 3, 4)


def _fit_early_stopped(
    kind: str,
    xt: torch.Tensor,
    yt: torch.Tensor,
    xv: torch.Tensor,
    yv: torch.Tensor,
    *,
    lr: float,
    wd: float,
    max_steps: int,
    eval_every: int,
    seed: int,
    batch_size: int = 32,
) -> dict[str, Any]:
    """AdamW fit; score val every `eval_every` steps; return best (nll, step) and the curve."""
    torch.manual_seed(seed)
    gen = torch.Generator().manual_seed(seed)
    model = MAKERS[kind]()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    best: tuple[float, int] = (float("inf"), 0)
    curve: list[list[float]] = []
    for step in range(1, max_steps + 1):
        idx = torch.randint(0, xt.shape[0], (batch_size,), generator=gen)
        loss = F.cross_entropy(model(xt[idx]), yt[idx])
        opt.zero_grad(set_to_none=True)
        loss.backward()  # type: ignore[no-untyped-call]
        opt.step()
        if step % eval_every == 0:
            model.eval()
            with torch.no_grad():
                nll = F.cross_entropy(model(xv), yv).item()
            model.train()
            curve.append([step, round(nll, 4)])
            best = min(best, (nll, step))
    return {"best_val_nll": round(best[0], 4), "best_step": best[1], "curve": curve}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="baseline_convergence")
    parser.add_argument("--tokens-pt", type=Path, default=DEFAULT_TOKENS)
    parser.add_argument("--train-frac", type=float, default=0.8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    resolved = args.tokens_pt.resolve()
    if TRAINING_RANGE_MARK not in resolved.name:
        print(
            f"baseline_convergence: refusing {resolved.name}: "
            f"not a {TRAINING_RANGE_MARK} artifact",
            file=sys.stderr,
        )
        return 2

    tokens = [max(0, int(t)) for t in load_tokens_pt(resolved).targets.tolist()]
    n_train = int(len(tokens) * args.train_frac)
    xt, yt = B._build_windows(tokens[:n_train], CONTEXT)
    xv, yv = B._build_windows(tokens[n_train:], CONTEXT)
    print(
        f"baseline_convergence: {resolved.name} "
        f"train_windows={xt.shape[0]} val_windows={xv.shape[0]}"
    )

    t0 = time.monotonic()
    grid_rows: list[dict[str, Any]] = []
    best_by_kind: dict[str, dict[str, Any]] = {}
    for kind, g in GRID.items():
        for lr in g["lr"]:
            for wd in g["wd"]:
                r = _fit_early_stopped(
                    kind, xt, yt, xv, yv, lr=lr, wd=wd, seed=0,
                    max_steps=g["max_steps"], eval_every=g["eval_every"],
                )
                row = {"kind": kind, "lr": lr, "wd": wd, **r}
                grid_rows.append(row)
                print(f"  {kind:6s} lr={lr:g} wd={wd:g} "
                      f"best={r['best_val_nll']} @ {r['best_step']}")
                incumbent = best_by_kind.get(kind)
                if incumbent is None or r["best_val_nll"] < incumbent["best_val_nll"]:
                    best_by_kind[kind] = row

    seed_rows: dict[str, dict[str, Any]] = {}
    for kind, row in best_by_kind.items():
        g = GRID[kind]
        per_seed = [
            _fit_early_stopped(
                kind, xt, yt, xv, yv, lr=row["lr"], wd=row["wd"], seed=s,
                max_steps=g["max_steps"], eval_every=g["eval_every"],
            )["best_val_nll"]
            for s in SEEDS
        ]
        seed_rows[kind] = {
            "lr": row["lr"], "wd": row["wd"], "per_seed": per_seed,
            "mean": round(statistics.mean(per_seed), 4),
            "stdev": round(statistics.stdev(per_seed), 4),
        }
        summary = seed_rows[kind]
        print(f"  {kind:6s} best config x5 seeds: mean={summary['mean']} sd={summary['stdev']}")

    args.output.write_text(json.dumps({
        "sprint": 118,
        "tokens_pt": resolved.name,
        "split": {"train_frac": args.train_frac, "train_windows": int(xt.shape[0]),
                  "val_windows": int(xv.shape[0]), "context_len": CONTEXT, "n_buckets": VOCAB},
        "selection": "best val_nll checkpoint, same rule the transformer runs used",
        "grid": grid_rows,
        "best_config_multiseed": seed_rows,
        "elapsed_seconds": round(time.monotonic() - t0, 1),
    }, indent=1) + "\n")
    print(f"baseline_convergence: wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
