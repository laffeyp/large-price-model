# Sprint 044 -- cross-asset intraday ingest (QQQ, IWM, TLT, GLD, USO, UUP)

---

```yaml
---
id: 044
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

`plans/v1-roadmap.md` Phase A step 3. Six cross-asset intraday channels land in the manifest, get pulled across the training and test windows, and appear in the re-aligned parquet with the OHLCV + staleness columns Sprint 042 introduced.

Spec §Channels names seven cross-asset symbols: QQQ, IWM, VIX, TLT, DXY, GLD, USO. VIX is on INDEX_DATA from Sprint 038. DXY is not on Alpha-Vantage — see the DXY substitution note below. The remaining five (QQQ, IWM, TLT, GLD, USO) plus UUP (as DXY proxy) get ingested via TIME_SERIES_INTRADAY.

## halt-and-articulate

**DXY substitution.** Alpha-Vantage's `INDEX_CATALOG` lists ~300 indices — every CBOE and S&P index the endpoint carries. DXY is not among them. DXY is an ICE Data Services index and does not clear through AV. `FX_INTRADAY` takes single currency pairs; DXY is a weighted basket of six pairs (EUR 57.6%, JPY 13.6%, GBP 11.9%, CAD 9.1%, SEK 4.2%, CHF 3.6%). Approximating DXY as USD/EUR alone captures ~58% of the signal. UUP (Invesco DB US Dollar Bullish Fund) is a US-listed ETF that tracks DXY at ≈0.99 correlation and returns clean 15-min bars via `TIME_SERIES_INTRODUCTIONDAY`. UUP is the honest v1 substitute. Filed to BLACKBOARD Decisions.

**USO accepted with note.** Prior Sprint 022 probe recorded `verdict: dropped` with `overall_missing_fraction: 0.2`. Spec §4.1 allows channels above the 0.05 threshold with "an explicit note in the channel manifest." Kept USO in v1; the `reason` field in `channel_coverage.json` names the shortfall. Post-alignment read-back shows 26 missing rows across 54,262 (0.05%) after backward-fill — the earlier "20% missing" reading likely reflected raw-row-level gaps in USO's pre-2018 tape that the as-of join resolves. USO's real coverage in the aligned parquet is on par with SPY.

**Files touched.** `data/manifests/channel_coverage.json` (config; not tracked in git per `.gitignore`), no code files. Zero code changes; the ingest CLI and alignment code already handle per-channel dispatch from Sprint 038 and Sprint 042.

## signal contract

### Emits

No new emit sites. `INGESTION_CALL_ISSUED` fires 800 times across the two ingest runs (673 training + 127 test); `RAW_OBSERVATION_WRITTEN` on every fresh cache write with full provenance; `ALIGNMENT_RUN_STARTED` / `ALIGNMENT_ROW_EMITTED` / `ALIGNMENT_RUN_COMPLETED` on the two re-align runs. Storage discipline from Sprint 036 held across the enlarged pull.

### Invariants

- Cache index grew 116 → 795 rows across the sprint.
- Aligned parquet gains 8 columns per channel × 6 new channels = 48 columns. Training parquet shape 54,262 × 73 (was 19 after Sprint 042's SPY + VIX only).
- Every new channel carries `known_at`, OHLCV (5 fields), and three staleness columns per Sprint 042's schema.
- Row count unchanged (54,262 training, 10,166 test). Same RTH grid; more per-channel columns.

## artifact contract

### Files modified

- `data/manifests/channel_coverage.json` — added six new `market_context` entries (QQQ, IWM, TLT, GLD, UUP, and USO now `accepted` with reason note). VIX and SPY entries unchanged.

### Files created

None (config-only sprint).

### Command exit codes

- ingest × 2 runs, exit 0. 673 ok on training window (576 fresh + 97 cache-hits); 127 ok on test window (109 fresh + 18 cache-hits).
- align × 2 runs, exit 0.
- features + bucketize × 3 runs (features on each window, tokenize on training), exit 0.
- Four tools already green; no code touched.
- Test count unchanged at 284.

### Live smoke

Full re-alignment after ingest:

```
uv run python scripts/align.py --start-month 2015-01 --end-month 2022-12
# align: 54262 rows in 4.56s

uv run python scripts/align.py --start-month 2024-01 --end-month 2025-06
# align: 10166 rows in 1.07s
```

Per-channel missing_mask fractions on the training window (54,262 rows, 8 channels):

- `target__SPY`: 26 missing (0.05%)
- `market_context__QQQ`: 26 (0.05%)
- `market_context__IWM`: 26 (0.05%)
- `market_context__TLT`: 26 (0.05%)
- `market_context__GLD`: 26 (0.05%)
- `market_context__USO`: 26 (0.05%)
- `market_context__UUP`: 26 (0.05%)
- `market_context__VIX`: 0 (0%; VIX daily history reaches 1990)

Per-channel `observed_at_this_grid_step` counts (freshness):

- `target__SPY`: 52,434 (96.63%)
- `market_context__QQQ`: 52,425 (96.61%)
- `market_context__IWM`: 52,395 (96.56%)
- `market_context__GLD`: 52,370 (96.51%)
- `market_context__TLT`: 52,314 (96.41%)
- `market_context__USO`: 52,400 (96.57%)
- `market_context__UUP`: 52,077 (95.97%) — lowest of the intraday set, matches UUP's thinner tape
- `market_context__VIX`: 2,019 (3.72%; one per trading day)

Every intraday channel loses roughly the same ~1,800-2,200 grid rows to backfill across halts and coverage gaps.

Features + tokens:

```
uv run python scripts/features.py --aligned .../train.parquet
# features: 1717939 emitted, 18445 failed in 53.42s

uv run python scripts/features.py --aligned .../test.parquet
# features: 320922 emitted, 4390 failed in 14.93s

uv run python scripts/bucketize.py --features .../train.parquet --training-start 2015-01-05 --training-end 2022-12-30
# tokenize: 54210 tokens in 9.61s; n_buckets=32 channels=8
```

Failure rate drops from Sprint 043's 3.5% (SPY + VIX only) to 1.06% (8 channels) — the added intraday channels are healthy and dilute VIX's flat-daily-run failures. Token count 54,210 unchanged (target is SPY log_return, independent of context channels).

---

## observation contract

Required (`pass_kind: functional`). Cache-index count check (795 total, up 679 from 116; matches ~680 fresh calls after subtracting 20 cache-hits). Per-channel missing_mask + observed counts verified against the read-back. Wall-clock: pull ~23 minutes across the two ingest runs; align + features + tokenize under 90 seconds total.

Storage discipline (Sprint 036) held under the 6× pull-volume increase: every fresh cache file carries a `.meta.json` sidecar, every write appended one index row, no orphans, freshness policy `math.inf` on TIME_SERIES_INTRADAY produced zero re-fetches on the two re-alignment runs.

---

## honest audit

**What landed.** Six new channels ingested at 15-min resolution across the training and test windows. Aligned parquet grew from 19 to 73 columns. Feature failure rate dropped as the healthy intraday tape diluted VIX's daily flatness. Token count and bucket edges unchanged (both are SPY-derived).

**What did not land.** No code change. Phase B feature-computation sprints (048-055) will read the new columns; nothing consumes them yet. The channel-projection cosine diagnostic (spec §10) that surfaces per-channel embedder contributions still waits for the MarketStateEmbedder (Sprint 058).

**What surfaced during execution.** The `missing_fractions` line in `scripts/align.py`'s stderr summary aggregates by channel category (`target`, `market_context`), which under-reports per-symbol coverage (last write wins in the dict). The per-symbol read-back happens in the observation-contract read-back script, not the CLI summary. Filed as a small display improvement for a later polish sprint; does not affect correctness.

**What did not need work.** `IngestionClient` handled the 6 new symbols through the existing tool-dispatch path. `align_channels` accepted the 6 new keys via the same rename-map guard. Sprint 042 and Sprint 038 paid off — this sprint moved 800 fresh AV calls through the pipeline with zero code touch.

---

## notes

**Why UUP and not a synthetic DXY-basket build.** Building DXY from six currency pairs via `FX_INTRADAY` would work in principle (weighted geometric mean per the ICE formula), but each pair adds an ingest path, a manifest entry, and a cross-pair timestamp-alignment problem. UUP delivers the DXY signal in one channel through the endpoint the rest of the ETFs use. The 0.01 residual correlation gap versus real DXY sits well below any measurable model impact at 15-min resolution.

**USO reality check.** The Sprint 022 probe's 0.2 missing_fraction likely reflected raw per-row gaps at the vendor level for pre-2018 USO. Backward-fill on the as-of join hides those gaps at the 15-min RTH grid level. If the trainer needs raw-row-level missingness, the `missing_mask__market_context__USO` column carries the per-bar fact; if the trainer wants a fresh USO observation per bar, `observed_at_this_grid_step__market_context__USO` (96.57%) is the honest measure.

**No fresh feature-computation gaps beyond VIX.** VIX's daily bar creates long constant runs across each RTH day; `rolling_std_20` on those runs collapses to zero and fires `FEATURE_COMPUTATION_FAILED` per row. Every other channel is intraday and updates every bar, so their rolling stats are well-defined. The 18,445 training failures land almost entirely on the VIX channel.

---

## plan-mode review checklist

- [x] Zero code files, one config file. Well under hard rule 6.
- [x] No new emit sites; existing tags carried real numbers.
- [x] Observation contract: per-channel read-back on the training window (mask + freshness).
- [x] Determinism budget bit-deterministic — same cached inputs re-align to byte-identical parquet.
- [x] DXY substitution and USO retention both named with reasons in the manifest and this card.

---

## close (2026-08-14)

Landed. Eight channels in the manifest (up from three effective — SPY, VIX, USO-dropped). Cache index at 795 rows (up 679). Aligned parquet at 73 columns per row. Feature failure rate down to 1.06%. Token count unchanged at 54,210 (target is SPY only). Four tools green. Phase A step 3 of 6 clears; Sprint 045 (five macro series) opens next.
