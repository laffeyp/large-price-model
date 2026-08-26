#!/usr/bin/env python3
"""Sprint 111: per-regime linear-baseline diagnostic.

Fit a LinearBaseline(64x32 -> 32) on the training partition of a tokenized .pt
artifact; predict on val; split val by vol regime using the same 33rd/66th
percentile thresholds evaluate.py uses; report per-regime nll/top1/dir_acc.

Answers: does the linear baseline dominate the transformer only on pooled
val_nll (dragged by high-vol which the transformer can't touch either), or
does linear also beat the transformer on the low-vol regime where the
transformer actually predicts?
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import torch
import torch.nn.functional as F

from price_space_llm.baselines import LinearBaseline, fit_linear
from price_space_llm.evaluation.regimes import (
    assign_regime,
    fit_regime_thresholds,
)
from price_space_llm.model.dataset import load_tokens_pt

REGIME_LABELS = ("low", "mid", "high")

REPO_ROOT = Path(__file__).resolve().parents[2]


def _dir_from_bucket(bucket: int, half_v: int) -> int:
    """Encode direction as sign of (bucket - median). 0 → down, 1 → up. Median bucket is neutral."""
    return int(bucket >= half_v)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linear_per_regime")
    parser.add_argument("--tokens-pt", type=Path, required=True,
                        help="Sprint 052 tokenized .pt artifact")
    parser.add_argument("--context-len", type=int, default=64)
    parser.add_argument("--n-buckets", type=int, default=32)
    parser.add_argument("--train-frac", type=float, default=0.8)
    parser.add_argument("--n-steps", type=int, default=2000,
                        help="Adam steps for linear-baseline fit; default 2000")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    print(f"linear_per_regime: loading {args.tokens_pt}")
    artifact = load_tokens_pt(args.tokens_pt)
    raw_tokens = artifact.targets
    raw_vols = artifact.vol.tolist()
    n_total = len(raw_tokens)
    n_train = int(n_total * args.train_frac)

    # Sprint 111: -100 is the PyTorch cross-entropy ignore_index sentinel used on
    # masked-invalid bars. Linear baseline uses F.one_hot which rejects negatives.
    # Replace -100 with 0 (bucket 0) for the linear input; the fitter is trained
    # on all valid windows so a handful of neutral-bucket tokens in the context
    # have negligible effect. Downstream target metrics are computed only on
    # valid targets by mask filter below.
    tokens = [max(0, int(t)) for t in raw_tokens.tolist()]

    train_tokens = tokens[:n_train]
    val_tokens = tokens[n_train:]
    train_vols = raw_vols[:n_train]
    val_vols = raw_vols[n_train:]
    val_valid_mask = [int(t) >= 0 for t in raw_tokens.tolist()[n_train:]]
    print(f"  n_total={n_total}, n_train={n_train}, n_val={n_total - n_train}")
    print(f"  masked-invalid targets in val: {sum(1 for v in val_valid_mask if not v)}")

    # Regime thresholds fit on training vol (as evaluate.py does).
    thresholds = fit_regime_thresholds(train_vols)
    print(f"  regime thresholds: low<{thresholds.low_threshold:.6f}, "
          f"mid<{thresholds.mid_threshold:.6f}")

    # Fit linear baseline.
    print(f"linear_per_regime: fit_linear n_steps={args.n_steps} lr={args.lr}")
    model: LinearBaseline = fit_linear(
        train_tokens, vocab_size=args.n_buckets, context_len=args.context_len,
        n_steps=args.n_steps, batch_size=args.batch_size, lr=args.lr, seed=args.seed,
    )
    model.eval()

    # Build val windows aligned to val_tokens; regime for window at start_pos = s
    # follows the target bar's vol at index s + context_len.
    print(f"linear_per_regime: evaluating on val ({len(val_tokens)} tokens)")
    n_val_windows = len(val_tokens) - args.context_len
    if n_val_windows < 1:
        raise ValueError("val partition too short for the given context_len")
    val_t = torch.tensor(val_tokens, dtype=torch.long)
    inputs = torch.stack([val_t[s : s + args.context_len] for s in range(n_val_windows)])
    targets = torch.stack([val_t[s + args.context_len] for s in range(n_val_windows)])

    with torch.no_grad():
        logits = model(inputs)
        log_probs = F.log_softmax(logits, dim=-1)
    nll_per = -log_probs[torch.arange(n_val_windows), targets]
    pred_top1 = logits.argmax(dim=-1)
    correct_top1 = (pred_top1 == targets).to(torch.float32)
    half_v = args.n_buckets // 2
    pred_dir = torch.tensor([_dir_from_bucket(int(b), half_v) for b in pred_top1])
    tgt_dir = torch.tensor([_dir_from_bucket(int(b), half_v) for b in targets])
    dir_correct = (pred_dir == tgt_dir).to(torch.float32)

    # Bin windows by regime of the target bar's vol; drop windows with masked
    # (originally -100) targets so nll math stays honest.
    regimes = [assign_regime(val_vols[s + args.context_len], thresholds)
               if val_valid_mask[s + args.context_len] else "SKIP"
               for s in range(n_val_windows)]

    per_regime: dict[str, dict[str, float]] = {}
    for label in REGIME_LABELS:
        mask_idx = [i for i, r in enumerate(regimes) if r == label]
        if not mask_idx:
            per_regime[label] = {"n_examples": 0, "nll": float("nan"),
                                 "top1": float("nan"), "dir_acc": float("nan")}
            continue
        idx_t = torch.tensor(mask_idx, dtype=torch.long)
        per_regime[label] = {
            "n_examples": len(mask_idx),
            "nll": float(nll_per[idx_t].mean().item()),
            "top1": float(correct_top1[idx_t].mean().item()),
            "dir_acc": float(dir_correct[idx_t].mean().item()),
        }

    # Pooled (weighted by n_examples).
    total_n = sum(per_regime[r]["n_examples"] for r in REGIME_LABELS)
    def wavg(key: str) -> float:
        return sum(per_regime[r][key] * per_regime[r]["n_examples"]
                   for r in REGIME_LABELS if per_regime[r]["n_examples"]) / total_n

    result = {
        "sprint": 111,
        "baseline": "linear",
        "context_len": args.context_len,
        "n_buckets": args.n_buckets,
        "n_train": n_train,
        "n_val": len(val_tokens),
        "regime_thresholds": {
            "low_upper": thresholds.low_threshold,
            "mid_upper": thresholds.mid_threshold,
        },
        "per_regime": per_regime,
        "pooled": {
            "nll": wavg("nll"),
            "top1": wavg("top1"),
            "dir_acc": wavg("dir_acc"),
            "n_examples": total_n,
        },
        "config": {
            "n_steps": args.n_steps,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "seed": args.seed,
            "train_frac": args.train_frac,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print()
    print(f'{"regime":>6} {"n":>6} {"nll":>8} {"top1":>8} {"dir_acc":>9}')
    for r in REGIME_LABELS:
        v = per_regime[r]
        print(f'{r:>6} {v["n_examples"]:>6} {v["nll"]:>8.4f} '
              f'{v["top1"]:>8.4f} {v["dir_acc"]:>9.4f}')
    p = result["pooled"]
    print(f'{"pooled":>6} {p["n_examples"]:>6} {p["nll"]:>8.4f} '
          f'{p["top1"]:>8.4f} {p["dir_acc"]:>9.4f}')
    print(f'\nchance nll = log({args.n_buckets}) = {math.log(args.n_buckets):.4f}')
    print(f'chance top1 = 1/{args.n_buckets} = {1.0 / args.n_buckets:.4f}')
    print(f'\nresult written to {args.output}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
