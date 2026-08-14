#!/usr/bin/env python3
"""Tokenizer CLI -- fits bucketizer on training range, writes frozen bucket_stats,
assigns bucket_ids, emits tokens.

Reads `data/features/{run_id}.parquet` and an `ExperimentConfig` for
n_buckets + target_symbol + context_len. Splits by training-range dates.
Fits quantile edges on the target's non-null log_returns in the training
partition. Persists `artifacts/tokenizer/bucket_stats.json` (frozen
artifact per tech-arch §7). Writes `data/tokenized/{run_id}.parquet`
with (grid_ts, bucket_id) pairs for the training rows.

Emits SESSION_INIT + CONFIG_RESOLVED + BUCKETIZER_FITTED +
BUCKET_STATS_WRITTEN + BUCKET_ASSIGNED (per training bar) +
MARKET_STATE_TOKEN_EMITTED (per grid bar) + SESSION_COMPLETE.
"""

import argparse
import hashlib
import sys
import traceback
from datetime import date
from pathlib import Path

from price_space_llm.config import ConfigValidationFailed, load_config
from price_space_llm.git import git_sha
from price_space_llm.script_harness import script_session
from price_space_llm.tokenizer import run_tokenizer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tokenize")
    parser.add_argument(
        "--features",
        type=Path,
        required=True,
        help="Path to features parquet from `scripts/features.py`.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/tokenized"))
    parser.add_argument(
        "--bucket-stats",
        type=Path,
        default=Path("artifacts/tokenizer/bucket_stats.json"),
        help="Frozen artifact destination. Overwritten on each fit; sha256 emitted.",
    )
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiment/v1.json"),
    )
    parser.add_argument(
        "--training-start",
        type=date.fromisoformat,
        required=True,
        help="YYYY-MM-DD (inclusive). First grid date included in the fit.",
    )
    parser.add_argument(
        "--training-end",
        type=date.fromisoformat,
        required=True,
        help="YYYY-MM-DD (inclusive). Last grid date included in the fit.",
    )
    parser.add_argument(
        "--d-model",
        type=int,
        default=64,
        help="Embedding width for MARKET_STATE_TOKEN_EMITTED payload.",
    )
    args = parser.parse_args(argv)

    if not args.features.exists():
        print(f"tokenize: features parquet not found: {args.features}", file=sys.stderr)
        return 1

    run_id = f"tokenize-{args.features.stem}-{args.seed:016d}"
    # Sprint 041: config_hash keyed to the experiment config; data_hash to features.
    config_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()
    data_hash = hashlib.sha256(args.features.read_bytes()).hexdigest()

    result = None
    with script_session(
        run_kind="train",
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
            print(f"tokenize: config invalid: {ex}", file=sys.stderr)
            return 1
        cfg = config_result.config

        try:
            result = run_tokenizer(
                features_path=args.features,
                output_dir=args.output_dir,
                bucket_stats_path=args.bucket_stats,
                target_symbol=cfg.target_symbol,
                n_buckets=cfg.n_buckets,
                d_model=args.d_model,
                training_range_start=args.training_start,
                training_range_end=args.training_end,
                emitter=emitter,
                run_id=run_id,
            )
        except (FileNotFoundError, ValueError):
            traceback.print_exc(file=sys.stderr)
            return 1

    if result is not None:
        print(
            f"tokenize: {result.n_tokens_emitted} tokens in {result.elapsed_seconds:.2f}s; "
            f"n_buckets={result.n_buckets} channels={result.channel_count}; "
            f"bucket_stats={result.bucket_stats_path}; "
            f"tokens={result.tokens_output_path}; trace={sink_path}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
