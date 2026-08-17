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
from price_space_llm.heldout_guard import HeldoutReadRefused, guard_heldout_parquet
from price_space_llm.script_harness import script_session
from price_space_llm.tokenizer import run_tokenizer
from price_space_llm.tokenizer.bucketize import load_bucket_stats, run_tokenizer_pt


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
    # Sprint 052: extended tokenized artifact per tech-arch §5. Default `both`
    # keeps every pre-Sprint-052 parquet consumer working while making the new
    # .pt available to Sprint 053's MarketStateEmbedder.
    parser.add_argument(
        "--format",
        choices=("parquet", "pt", "both"),
        default="both",
        help="'parquet' is the pre-Sprint-052 shape; 'pt' is the extended "
        "artifact with per-channel feature tensors; 'both' writes both.",
    )
    parser.add_argument(
        "--channel-coverage",
        type=Path,
        default=Path("data/manifests/channel_coverage.json"),
        help="Recorded in the .pt artifact's meta.channel_coverage_sha field.",
    )
    # Sprint 054: frozen normalizer per product-spec § Feature normalization.
    parser.add_argument(
        "--fit-normalizer",
        action="store_true",
        help="Fit per-(channel, feature) mean + std on the training partition, "
        "persist to --normalizer-path, and apply before writing the .pt artifact. "
        "Requires --format pt or --format both.",
    )
    parser.add_argument(
        "--normalizer-path",
        type=Path,
        default=Path("artifacts/tokenizer/normalizers.pt"),
        help="Frozen normalizer destination (versioned via write_versioned).",
    )
    parser.add_argument(
        "--allow-test-look",
        action="store_true",
        help="Sprint 065: acknowledge reading a held-out features parquet.",
    )
    args = parser.parse_args(argv)

    # Sprint 065: refuse to tokenize a held-out features parquet without ack.
    try:
        guard_heldout_parquet(args.features, allow_test_look=args.allow_test_look)
    except HeldoutReadRefused as ex:
        print(f"tokenize: {ex}", file=sys.stderr)
        return 2

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

        pt_output_path: Path | None = None
        try:
            if args.format in ("parquet", "both"):
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
            if args.format in ("pt", "both"):
                # If --format pt without --format both, we still need to fit +
                # write bucket_stats before writing the .pt artifact. The
                # `parquet` branch above does that as a side effect; when we
                # skip it, we reuse the latest versioned bucket_stats file.
                if args.format == "pt":
                    import polars as pl

                    from price_space_llm.tokenizer import fit_bucketizer, write_bucket_stats

                    feats_df = pl.read_parquet(args.features)
                    stats = fit_bucketizer(
                        feats_df,
                        target_symbol=cfg.target_symbol,
                        n_buckets=cfg.n_buckets,
                        training_range_start=args.training_start,
                        training_range_end=args.training_end,
                        emitter=emitter,
                    )
                    write_bucket_stats(stats, args.bucket_stats, emitter, run_id=run_id)
                else:
                    latest_stats = args.bucket_stats.parent / (
                        args.bucket_stats.stem + ".latest.json"
                    )
                    stats = load_bucket_stats(
                        latest_stats if latest_stats.exists() else args.bucket_stats
                    )
                # Sprint 054: optional frozen normalizer fit + apply.
                normalizer = None
                if args.fit_normalizer:
                    from price_space_llm.model.dataset import load_tokens_pt
                    from price_space_llm.normalizer import (
                        fit_frozen_normalizer,
                        write_frozen_normalizer,
                    )

                    # Two-pass: first write an unnormalized .pt to get shapes,
                    # then fit + write normalizer, then re-materialize with
                    # normalization applied. Simpler than fitting off the parquet
                    # directly (avoids duplicating the per-channel column discovery).
                    intermediate = run_tokenizer_pt(
                        features_path=args.features,
                        output_dir=args.output_dir,
                        stats=stats,
                        target_symbol=cfg.target_symbol,
                        emitter=emitter,
                        run_id=f"{run_id}-pre-norm",
                        channel_coverage_path=args.channel_coverage,
                        config_hash=config_hash,
                        data_hash=data_hash,
                        git_sha_value=git_sha() or "unknown",
                    )
                    intermediate_artifact = load_tokens_pt(intermediate)
                    normalizer = fit_frozen_normalizer(
                        intermediate_artifact,
                        training_range_start=args.training_start.isoformat(),
                        training_range_end=args.training_end.isoformat(),
                        emitter=emitter,
                        run_id=run_id,
                    )
                    write_frozen_normalizer(
                        normalizer,
                        args.normalizer_path,
                        emitter,
                        run_id=run_id,
                    )
                    # Clean up the intermediate.
                    intermediate.unlink(missing_ok=True)
                pt_output_path = run_tokenizer_pt(
                    features_path=args.features,
                    output_dir=args.output_dir,
                    stats=stats,
                    target_symbol=cfg.target_symbol,
                    emitter=emitter,
                    run_id=run_id,
                    channel_coverage_path=args.channel_coverage,
                    config_hash=config_hash,
                    data_hash=data_hash,
                    git_sha_value=git_sha() or "unknown",
                    normalizer=normalizer,
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
    if pt_output_path is not None:
        print(f"tokenize: pt artifact={pt_output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
