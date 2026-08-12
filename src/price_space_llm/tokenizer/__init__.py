"""Return bucketizer + market-state token emitter.

Reads the features parquet (from Sprint 026), fits quantile bucket
boundaries on the training partition of the target symbol's
`log_return`, persists boundaries to `artifacts/tokenizer/`, assigns
`bucket_id` to every training bar, and emits one
`MARKET_STATE_TOKEN_EMITTED` per bar per (channel_count, d_model).

Frozen-artifact contract per tech-arch §7: `bucket_stats.json` is
written once at fit time, sha256'd, and never mutated. Every downstream
consumer reads from the file, not from a live fit.
"""

from price_space_llm.tokenizer.bucketize import (
    BucketStats,
    TokenizerResult,
    fit_bucketizer,
    load_bucket_stats,
    run_tokenizer,
    write_bucket_stats,
)

__all__ = [
    "BucketStats",
    "TokenizerResult",
    "fit_bucketizer",
    "load_bucket_stats",
    "run_tokenizer",
    "write_bucket_stats",
]
