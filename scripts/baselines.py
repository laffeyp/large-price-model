#!/usr/bin/env python3
"""Baselines CLI: fit + eval three baselines, emit BASELINE_COMPARISON_ASSESSED x 3.

Reads tokens from Sprint 030, bucket_stats from artifacts/tokenizer/, and
the transformer's val NLL from a Sprint 032 metrics.json. Fits linear,
target_only, magnitude_weighted; each computes a val NLL; emits one
BASELINE_COMPARISON_ASSESSED per baseline with delta_pct + meets_gate
against the product-spec pre-registered thresholds.
"""

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path
from typing import cast

from price_space_llm.baselines import (
    BaselineKind,
    compare_to_transformer,
    fit_and_eval,
    load_transformer_val_nll,
)
from price_space_llm.config import ConfigValidationFailed, load_config
from price_space_llm.git import git_sha
from price_space_llm.model.dataset import load_tokens, split_tokens
from price_space_llm.script_harness import script_session
from price_space_llm.tokenizer import load_bucket_stats

BASELINES: tuple[BaselineKind, ...] = ("linear", "target_only", "magnitude_weighted")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="baselines")
    parser.add_argument("--tokens", type=Path, required=True)
    parser.add_argument("--transformer-metrics", type=Path, required=True)
    parser.add_argument(
        "--bucket-stats",
        type=Path,
        default=Path("artifacts/tokenizer/bucket_stats.json"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiment/v1.json"),
    )
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--train-frac", type=float, default=0.8)
    args = parser.parse_args(argv)

    for label, path in (
        ("tokens", args.tokens),
        ("transformer-metrics", args.transformer_metrics),
        ("bucket-stats", args.bucket_stats),
    ):
        if not path.exists():
            print(f"baselines: {label} not found: {path}", file=sys.stderr)
            return 1

    run_id = f"baselines-{args.tokens.stem}-{args.seed:016d}"
    # Sprint 041: config_hash keyed to the experiment config; data_hash to tokens.
    config_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()
    data_hash = hashlib.sha256(args.tokens.read_bytes()).hexdigest()

    results = []
    with script_session(
        run_kind="eval",
        run_id=run_id,
        config_hash=config_hash,
        data_hash=data_hash,
        seed=args.seed,
        logs_dir=args.logs_dir,
    ) as (emitter, sink_path):
        try:
            config_result = load_config(
                args.config, emitter=emitter, run_id=run_id, git_sha=git_sha()
            )
        except ConfigValidationFailed as ex:
            print(f"baselines: config invalid: {ex}", file=sys.stderr)
            return 1
        cfg = config_result.config

        stats = load_bucket_stats(args.bucket_stats)
        transformer_val_nll = load_transformer_val_nll(args.transformer_metrics)

        try:
            tokens = load_tokens(args.tokens, cfg.target_symbol)
            train_tokens, val_tokens = split_tokens(tokens, args.train_frac)
        except (ValueError, FileNotFoundError):
            traceback.print_exc(file=sys.stderr)
            return 1

        for kind_str in BASELINES:
            kind = cast(BaselineKind, kind_str)
            fit_result = fit_and_eval(
                kind,
                train_tokens,
                val_tokens,
                vocab_size=cfg.n_buckets,
                context_len=cfg.context_len,
                bucket_edges=list(stats.edges) if kind == "magnitude_weighted" else None,
                seed=args.seed,
            )
            comparison = compare_to_transformer(fit_result, transformer_val_nll)
            emitter.emit(
                "BASELINE_COMPARISON_ASSESSED",
                run_id=run_id,
                baseline_kind=kind_str,
                baseline_run_id=fit_result.baseline_run_id,
                transformer_val_nll=comparison.transformer_val_nll,
                baseline_val_nll=comparison.baseline_val_nll,
                delta_pct=comparison.delta_pct,
                required_delta_pct=comparison.required_delta_pct,
                meets_gate=comparison.meets_gate,
            )
            results.append((fit_result, comparison))

    for _fit, comp in results:
        status = "PASS" if comp.meets_gate else "MISS"
        print(
            f"baselines: {comp.kind}: baseline_nll={comp.baseline_val_nll:.4f} "
            f"transformer_nll={comp.transformer_val_nll:.4f} delta={comp.delta_pct:+.2f}% "
            f"required>={comp.required_delta_pct:.1f}% -> {status}",
            file=sys.stderr,
        )
    print(f"baselines: trace={sink_path}", file=sys.stderr)

    # Also stamp an aggregate JSON so downstream can consume without parsing the trace.
    summary_path = Path("artifacts") / run_id / "baselines.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "transformer_val_nll": results[0][1].transformer_val_nll,
                "comparisons": [
                    {
                        "kind": c.kind,
                        "baseline_run_id": c.baseline_run_id,
                        "baseline_val_nll": c.baseline_val_nll,
                        "delta_pct": c.delta_pct,
                        "required_delta_pct": c.required_delta_pct,
                        "meets_gate": c.meets_gate,
                    }
                    for _, c in results
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
