# Sprint 056 -- extended `bucket_stats.json` schema

---

```yaml
---
id: 056
status: closed
phase: 3
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Closes review § 3 aggregate-audit HIGH item: *"`bucket_stats.json` schema is wrong. Spec § 7.1 requires per-bucket `bucket_lower`, `bucket_upper`, `bucket_train_mean`, `bucket_train_median`, `bucket_train_frequency`. Simulator's decode of outer buckets to expected return requires `bucket_train_mean`; `baselines.py` currently fakes it from edge midpoints."*

Sprint 056 extends the frozen artifact and swaps the magnitude-weighted baseline's midpoint-fake for the real mean.

### Deliverables

1. **`BucketRow` dataclass** — new. Fields: `lower: float | None`, `upper: float | None` (None means -∞ / +∞), `train_mean: float`, `train_median: float`, `train_frequency: float`.
2. **`BucketStats` gains `per_bucket: tuple[BucketRow, ...]`** — length = `n_buckets`, one row per bucket.
3. **`fit_bucketizer` computes per-bucket stats** — after edges dedup, bin the training values with `assign_buckets`, compute per-bucket mean + median + count/total. Bounds derived from edges: bucket 0 = (None, edges[0]], bucket i = (edges[i-1], edges[i]], bucket n-1 = (edges[n-2], None].
4. **`write_bucket_stats` + `load_bucket_stats`** — serialize `per_bucket` via `asdict`. `float('-inf')` / `float('+inf')` are not JSON-serializable; the loader/writer converts to/from `null`.
5. **`compute_magnitude_weights_from_stats(stats: BucketStats)`** — new function alongside the existing `compute_magnitude_weights(bucket_edges, vocab_size)`. Uses `stats.per_bucket[i].train_mean` directly. Sprint 056 wires the stats-based path; a follow-up sprint retires the edge-midpoint fallback once every caller migrates.

## halt-and-articulate

**JSON can't carry infinity.** `float('-inf')` and `float('+inf')` produce `"Infinity"`/`"-Infinity"` under Python's default `json.dumps(allow_nan=True)` — non-strict JSON. Sprint 056 stores bounds as `null` in the JSON (proper strict JSON) and converts to `None` in `BucketRow`. Downstream consumers that want infinities do `lower or float('-inf')` explicitly.

**Median needs no special import.** `statistics.median` from the stdlib works on a list of floats; no numpy/scipy dep.

## signal contract

### Emits

Existing `BUCKETIZER_FITTED` + `BUCKET_STATS_WRITTEN` cover the fit + write. No new tags needed — the per-bucket stats live in the serialized artifact, not in the trace payload.

### Invariants

- `stats.per_bucket` has exactly `n_buckets` entries after fit.
- `stats.per_bucket[0].lower is None` and `stats.per_bucket[-1].upper is None` (open tails).
- For interior `i`: `stats.per_bucket[i].lower == stats.edges[i-1]` and `stats.per_bucket[i].upper == stats.edges[i]`.
- Σ `train_frequency` across per_bucket ≈ 1.0 (float rounding aside).
- `train_mean` and `train_median` are finite for any bucket with ≥1 training row; NaN otherwise (documented; empty-bucket case is rare with 32-bucket quantile edges over ~50k rows).
- `write` + `load` round-trip preserves every field bit-identically.
- `compute_magnitude_weights_from_stats(stats)` returns `Tensor[vocab_size]` with mean 1.0 (normalized).

## artifact contract

### Files (4 — under hard rule 6)

- `src/price_space_llm/tokenizer/bucketize.py` — new `BucketRow` dataclass, extended `BucketStats`, extended `fit_bucketizer`, JSON write/load handling infinity-as-null.
- `src/price_space_llm/baselines.py` — new `compute_magnitude_weights_from_stats(stats)` alongside the old `compute_magnitude_weights(bucket_edges, vocab_size)`.
- `tests/test_tokenizer.py` — new tests: per-bucket shape; interior bounds match edges; open tails; frequency sums to 1; write+load round-trip preserves the fields; strict JSON (no `Infinity` string).
- `tests/test_baselines.py` — new tests: `compute_magnitude_weights_from_stats` uses `train_mean` and normalizes to mean 1.

### Command exit codes

- ruff, ruff format, mypy: green.
- pytest: 364 → 372+.
- `scripts/bucketize.py --format both` on real training features exits 0; produced JSON has `per_bucket` array of length 32.

### Live smoke

Re-run bucketize on training window:
- `bucket_stats.{run_id}.json` now carries `per_bucket` array of 32 entries.
- Interior bounds match `edges`.
- `train_frequency` sums to 1 within 1e-6.
- `train_mean` on bucket 15 (mid-vol-normalized-return quantile) close to 0; bucket 0 (outer left tail) negative; bucket 31 (outer right tail) positive.

---

## observation contract

Required (`pass_kind: functional`). Unit tests lock every property. Live-smoke verifies the extended JSON lands on disk with correct shapes and monotone statistics across bucket index.

---

## honest audit

**What lands.** Per-bucket statistics in the frozen artifact. Real `train_mean`-based magnitude weights alongside the midpoint fake.

**What does not land.** Retiring the edge-midpoint `compute_magnitude_weights` function — deferred until every caller migrates. Simulator's decode path — Sprint 074 (roadmap Phase F); it will consume `bucket_train_mean` from the extended stats.

**What surfaces.** Empty buckets would produce NaN `train_mean` + `train_median`. At 32 quantile buckets over 50K+ training rows this shouldn't happen; the code emits NaN rather than filling to preserve honesty if it ever does.

---

## notes

**Why store bounds as `None` in the JSON, not `-Infinity`.** Strict JSON (RFC 8259) doesn't allow non-finite numbers. Python's `json.dumps` with `allow_nan=True` (default) writes `"Infinity"`, which no other language's JSON parser accepts. `None` is the portable choice.

**Why keep the old `compute_magnitude_weights` around.** Existing baselines + tests use it. A cleanup sprint retires it once every caller reads `BucketStats` and consumes `compute_magnitude_weights_from_stats` instead. Sprint 056 stays narrow.

---

## plan-mode review checklist

- [x] Files under hard rule 6 (4).
- [x] No new emit sites.
- [x] Observation contract (functional-band): 6 tokenizer tests + 3 baseline tests + live smoke on real training window.
- [x] Determinism budget bit-deterministic (same features + same edges = byte-identical extended stats).
- [x] Closes review § 3 aggregate-audit HIGH: bucket_stats.json now carries per-bucket lower/upper/train_mean/train_median/train_frequency.

---

## close (2026-08-15)

Landed. `BucketRow` dataclass (lower, upper, train_mean, train_median, train_frequency); `BucketStats.per_bucket` field length == n_buckets. `fit_bucketizer` computes per-bucket stats via `_compute_per_bucket_stats` after edge dedup. Write path uses `allow_nan=False` + sanitizes NaN + None bounds → strict JSON. Load path restores NaN for empty-bucket means. `compute_magnitude_weights_from_stats(BucketStats)` returns `|train_mean|` weights normalized to mean 1; rejects legacy stats missing per_bucket. Old `compute_magnitude_weights(edges, vocab_size)` kept for back-compat with a note pointing at the new function. Live smoke on training window (54,262 rows): per_bucket length 32, frequency sum 1.0000, bucket 0 `lower=None train_mean=-0.0061` (outer left tail), bucket 15 (middle) `train_mean=0.0`, bucket 31 `upper=None train_mean=+0.0060` (outer right tail). Test count 364 → 373 (+9: 6 tokenizer + 3 baseline). Four tools green. Sprint 074 (roadmap Phase F simulator) will consume `bucket_train_mean` for the decode-outer-buckets-to-expected-return path. Sprint 057 opens next per roadmap (originally: "Extended tokenized artifact" — already done as Sprint 052; renumbered work continues with the roadmap's next unaddressed item).
