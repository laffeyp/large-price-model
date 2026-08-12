# Sprint 030 -- tokenizer (bucketizer fit + token emit)

---

```yaml
---
id: 030
status: closed
phase: 1
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Author `src/price_space_llm/tokenizer/bucketize.py` + `scripts/bucketize.py`. Read the features parquet, fit `n_buckets` quantile edges on the target symbol's non-null `log_return` in the training range, persist a frozen `bucket_stats.json` under `artifacts/tokenizer/` with a sha256, assign `bucket_id` per training bar, emit one `MARKET_STATE_TOKEN_EMITTED` per grid bar.

Every vocabulary tag under `tokenize` and `embed` categories lands from live code.

---

## signal contract

### Emits

- `BUCKETIZER_FITTED` (tokenize/summary) with n_buckets, training range, row count.
- `BUCKET_STATS_WRITTEN` (tokenize/event) with path, sha256, n_buckets.
- `BUCKET_ASSIGNED` (tokenize/ambient) per training bar with timestamp, bucket_id, vol_normalized_return.
- `MARKET_STATE_TOKEN_EMITTED` (embed/ambient) per grid bar with timestamp, d_model, channel_count.

### Invariants

- Bucket edges are strictly increasing. Tie-break: adjacent tied quantiles nudged by relative 1e-12 epsilon so `assign_buckets` returns distinct ids. Zero-return dominant windows (holidays) produce ties at 0.0; the epsilon fix keeps `bucket_id ∈ [0, n_buckets-1]` well-defined.
- Every input value maps to exactly one bucket; nulls preserve to null.
- Values below the smallest edge → bucket 0; values above the largest → bucket `n_buckets-1`.
- `bucket_stats.json` written once per run, sha256'd, never mutated (frozen-artifact contract per tech-arch §7).

---

## artifact contract

### Files created

- `src/price_space_llm/tokenizer/__init__.py`
- `src/price_space_llm/tokenizer/bucketize.py` (~230 lines)
- `scripts/bucketize.py` (~120 lines)
- `tests/test_tokenizer.py` (13 tests, including 2 Hypothesis properties)

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 130 → 142 (+12).

### Live smoke

```
uv run python scripts/bucketize.py \
  --features data/features/features-align-2024-06-0000000000000000-0000000000000000.parquet \
  --training-start 2024-06-03 --training-end 2024-06-28
```

Expected (verified): exit 0, 0.03s. Trace: SESSION_INIT + CONFIG_RESOLVED + BUCKETIZER_FITTED + BUCKET_STATS_WRITTEN + 519×BUCKET_ASSIGNED + 520×MARKET_STATE_TOKEN_EMITTED + SESSION_COMPLETE. `artifacts/tokenizer/bucket_stats.json` written with 31 edges (n_buckets=32 → 31 boundaries). Tokens parquet at `data/tokenized/{run_id}.parquet`. Bucket count distribution 16-17 per bucket over 519 rows (target quantile mean = 16.2).

---

## observation contract

Required. Live smoke verified end-to-end. Quantile balance holds within ±1 of the expected per-bucket count. `test_bucket_assignment_is_quantile_consistent` walks 100 random distributions and asserts no bucket holds more than 3× its expected share.

---

## notes

**Script name collision with stdlib.** First-pass CLI was named `scripts/tokenize.py`. That shadowed the stdlib's `tokenize` module — when `inspect` (used by httpx/pydantic during import) tried to import stdlib `tokenize`, Python resolved to my script first because Python auto-adds the script's directory to `sys.path[0]`. Every subprocess CLI test crashed with a confusing `AttributeError: module 'inspect' has no attribute 'signature' (most likely due to a circular import)`. Renamed `scripts/bucketize.py`. Lesson: never name a script the same as a stdlib module. Filing to `## Drift watchlist`.

**Quantile helper is stdlib-only.** `np.quantile` would be a natural fit but numpy is not a project dep. Wrote a 10-line linear-interpolation `_quantile` over a sorted list. Behaves identically to `np.quantile(..., method='linear')` for the cases tested. If future performance matters (fitting on years of bars), swap to `numpy` — the numeric equivalence is preserved.

**PBT covers both invariants.** `test_edges_are_strictly_increasing` walks 100 random distributions and asserts strict monotonicity holds for every fit; `test_bucket_assignment_is_quantile_consistent` walks 100 more and asserts bucket balance stays within 3× of uniform. Both properties held zero counter-examples.

**`run_kind=train` for the tokenizer session.** Same choice as `scripts/features.py`; v0.3's SESSION_INIT enum has no `tokenize` value, and tokenization is the setup phase of training per tech-arch §7. Consistent with the earlier decision.

---

## close (2026-08-11)

Landed. Four vocabulary tags now emit from live code. 519-row tokens parquet, 31 edges frozen at sha256, bucket distribution flat within ±1. Test count 130 → 142.
