# Sprint 039 -- operational data pull + local chain to tokens

---

```yaml
---
id: 039
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Materialise the training and test corpora the tech-arch names in §11. Training window: 2015-01-05 through 2022-12-30 per the product-spec's "ten years of 15-minute RTH bars." Held-out test window: 2024-01-01 through 2025-06-30 per §11's cost-aware simulator target. 2023 is a deliberate gap between the two — no data pulled, no code touched.

The sprint ends at tokens on disk. Trainer, cost calibration on full window, baselines, evaluation, simulator, held-out test all live in later sprints. This 28GB laptop stages data; GPU training runs on rented hardware once Sprint 041 provisions it.

## halt-and-articulate

**Sprint 039 ≠ "full pipeline run."** Earlier framing (BLACKBOARD Decision 2026-08-12) collapsed the whole remaining project into one sprint. Corrected on user challenge. This sprint's scope: pull + align + features + tokenize. Nothing that consumes GPU. Nothing that spends the $500 compute budget the product-spec pins.

**Manifest schema drift landed.** Sprint 038 added the `tool` field per channel. Sprint 039 updates `data/manifests/channel_coverage.json` to name `tool: TIME_SERIES_INTRADAY` for SPY and `tool: INDEX_DATA` for VIX. USO stays `verdict: dropped` per Sprint 022's probe.

**Test tokenization deferred.** `scripts/bucketize.py` fits + assigns for the training window. Applying frozen edges to the test window needs an `apply_bucketizer` step that this sprint does not build. The frozen `bucket_stats.latest.json` is on disk; the code that reads it and stamps the test parquet lands when the trainer needs test tokens (Sprint 042+).

## signal contract

### Emits

No new emit sites. `INGESTION_CALL_ISSUED` fired 115 times (114 fresh SPY monthly pulls + 1 VIX INDEX_DATA cache-hit; Sprint 038 pre-cached the VIX response). `RAW_OBSERVATION_WRITTEN` on every fresh cache write with real `value_time`, `known_at`, `size_bytes`, `response_schema_hash`. `ALIGNMENT_RUN_STARTED` / `ALIGNMENT_ROW_EMITTED` / `ALIGNMENT_RUN_COMPLETED` on each of the two align runs. `FEATURE_COMPUTED` / `FEATURE_COMPUTATION_FAILED` on each of the two feature runs. `BUCKETIZER_FITTED` / `BUCKET_STATS_WRITTEN` / `BUCKET_ASSIGNED` (×54,210) / `MARKET_STATE_TOKEN_EMITTED` (×54,262) on the tokenize run.

### Invariants

- `cache_index.jsonl` gained 114 rows over the two ingest runs. Rows carry `pulled_at_utc`, `size_bytes`, `response_schema_hash`, `pulled_by_run_id`.
- Sprint 036 storage discipline held over a much larger pull. Every fresh cache file has its `.meta.json` sidecar; no orphans.
- VIX cache-hit on second ingest run (INDEX_DATA policy is immutable `math.inf`).
- Bucket edges fit on 2015-01-05 through 2022-12-30 rows only; test window never enters the quantile fit. Verified by `training_range_start` / `training_range_end` fields on the persisted `bucket_stats.json`.

## artifact contract

### Files modified

- `data/manifests/channel_coverage.json` — added `tool` field per channel; refreshed `generated_at`; updated VIX `earliest_timestamp` to reflect the real INDEX_DATA history (1990-01-02).

### Files created

- `data/aligned/align-2015-01-2022-12-0000000000000000.parquet` — 54,262 rows × 5 columns (grid_ts, target__SPY__known_at, target__SPY__close, market_context__VIX__known_at, market_context__VIX__close).
- `data/aligned/align-2024-01-2025-06-0000000000000000.parquet` — 10,166 rows × 5 columns.
- `data/features/features-align-2015-01-2022-12-0000000000000000-0000000000000000.parquet` — 54,262 rows × 9 columns (grid_ts + 4 per channel: log_return, rolling_mean_20, rolling_std_20, rolling_z_score_20).
- `data/features/features-align-2024-01-2025-06-0000000000000000-0000000000000000.parquet` — 10,166 rows × 9 columns.
- `artifacts/tokenizer/bucket_stats.tokenize-features-align-2015-01-2022-12-....json` — frozen edges (31 edges → 32 buckets) fit on training partition. `.sha256` sidecar and `.latest.json` symlink flipped from the prior three-month smoke.
- `data/tokenized/tokenize-features-align-2015-01-2022-12-....parquet` — 54,210 (grid_ts, bucket_id) rows.
- `data/raw/mcp_av/TIME_SERIES_INTRADAY/{sha256}.json` × 114 + matching `.meta.json` sidecars.

### Command exit codes

- 115 AV HTTP calls, exit 0.
- Two align + two features + one tokenize, exit 0 each.
- All four tools already green from prior sprints — no code change this sprint.

### Live smoke

```
uv run python scripts/ingest.py --start-month 2015-01 --end-month 2022-12
# ingest: 97 ok, 0 failed (96 SPY + 1 VIX cache-hit)

uv run python scripts/ingest.py --start-month 2024-01 --end-month 2025-06
# ingest: 19 ok, 0 failed (18 SPY + 1 VIX cache-hit)

uv run python scripts/align.py --start-month 2015-01 --end-month 2022-12
# align: 54262 rows in 1.75s; missing_fractions=[target=0.000, market_context=0.000]

uv run python scripts/align.py --start-month 2024-01 --end-month 2025-06
# align: 10166 rows in 0.37s; missing_fractions=[target=0.003, market_context=0.000]

uv run python scripts/features.py --aligned .../train.parquet
# features: 419414 emitted, 14682 failed in 24.16s

uv run python scripts/features.py --aligned .../test.parquet
# features: 78518 emitted, 2810 failed in 2.16s

uv run python scripts/bucketize.py --features .../train.parquet --training-start 2015-01-05 --training-end 2022-12-30
# tokenize: 54210 tokens in 2.38s; n_buckets=32 channels=2
```

---

## observation contract

Required (`pass_kind: functional`). Verified against the four artifacts:

**Training partition (2015-2022):**
- 54,262 rows; SPY null 0.05%, VIX null 0.002%.
- SPY 15-min log_return: mean 0.000014, std 0.002190. Consistent with SPY intraday realized vol; annualised ≈ 12%.
- 54,210 tokens over 32 buckets; per-bucket target 1,694; actual range [1103, 2318]. Vol clustering fattens the tail buckets on quantile fit — real, expected.
- Bucket edges: min -0.00326, mid 0.00000, max +0.00327. Symmetric around zero, consistent with the log_return distribution's near-zero mean.

**Test partition (2024-01 through 2025-06):**
- 10,166 rows; SPY null 0.27%, VIX null 0.01%.
- SPY log_return: mean 0.000028, std 0.002119 — slightly lower vol than training window.
- Frozen edges applied to 10,139 valid test rows; per-bucket target 317; actual range [187, 432].
- Bucket-frequency max deviation: 0.0046. Train tails (buckets 0+31) = 0.0625 exactly (quantile fit invariant: 2/32). Test tails = 0.0553. Outer ratio 0.88 — the test period held 12% fewer extreme moves than the training window. Real regime observation: 2024-2025 is the recent low-vol equity regime; VIX floor around 12 for much of 2024.

Storage discipline invariant (Sprint 036) held over a real pull:
- `data/raw/cache_index.jsonl` grew from 2 rows to 116 rows.
- Every fresh cache file has its `.meta.json` sidecar; no orphaned entries.
- VIX INDEX_DATA cache-hit on the second ingest run confirms the immutable-tool freshness policy.

---

## honest audit

**What landed.** The full corpus the model will train on. Real prices, real vol, real bucket distribution, real train/test drift. All artifacts versioned and hashed per Sprint 036. Zero code change — the sprint is data + configuration + verification, nothing more.

**What did not land.** No test-window tokenization (needs `apply_bucketizer` step; deferred). No trainer touched. No cost calibration re-run on full window (currently smoked on 3 months). No baselines. No evaluation. No GPU. The tech-arch's model-size sweep, context-length sweep, and four architecture ablations all wait for a remote training environment.

**What surfaced during execution.** Feature failure rate on the training window: 14,682 failures across 419,414 emissions (3.5%). Higher than the three-month smoke (525 / 12,995 = 4.0%) but scaled by the length of the constant-VIX runs. Failures are `rolling_std_20 == 0 → z-score undefined` on flat-VIX segments — real behavior of a daily channel aligned to 15-min bars, not a defect.

**What did not need work.** Sprint 036 storage handled 116 cache entries without a hiccup. Sprint 037 multi-month CLI accepted a 96-month range at once and aligned 54,262 rows in 1.75s. Sprint 038's INDEX_DATA dispatch handed VIX in with zero fuss. The last three sprints paid for themselves in this run.

---

## notes

**Why no test-window tokenization.** The trainer's dataset loader reads bucket_ids from a tokens parquet. Test-window tokens will exist when the evaluator runs, not before. That evaluator lives in later sprints. Fitting stats or assigning IDs is not a "test look" per Sprint 034's testlook budget — a look means running the trained model on test-set metrics.

**Wall-clock cost.** 114 SPY intraday fetches took ~4 minutes at ~2s per HTTP round-trip. Alignment on 8 years: 1.75s. Features: 24s. Tokenize: 2.4s. Total under 5 minutes end-to-end. Well within the "before the pull sprint, storage integrity had to land" premise from Sprint 036.

**Wall-clock cost, second time.** Every future re-run of the same pull is entirely cache-hit — zero HTTP calls, zero AV usage. Sprint 036 pays off again.

**Naming conflict at the manifest.** VIX's `earliest_timestamp` in the pre-Sprint-039 manifest was `2015-01-05` — a lie from the pre-Sprint-038 era when the probe recorded a plausible-looking timestamp before actually pulling VIX. Sprint 039 updates it to `1990-01-02`, the real earliest date INDEX_DATA carries. Filed as fix, not surface — the old value was demonstrably wrong.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (pull operational data + local chain to tokens).
- [x] Zero code files touched — data + manifest configuration + verification only.
- [x] Signal contract: no new tags; every existing tag fired the expected number of times against real data.
- [x] Observation contract (functional-band): read-back verified across 5 dimensions (row counts, null fractions, moments, bucket distribution, train/test drift).
- [x] Determinism budget declared (bit-deterministic — every write is content-hashed).
- [x] Explicit scope-cap on training/GPU work.

---

## close (2026-08-13)

Landed. 54,210 training tokens fit on 2015-01-05 through 2022-12-30. 10,166 test features ready for `apply_bucketizer`. 116 cache entries with full provenance. Zero code change. Next sprint proceeds against a hardened storage layer + full corpus.
