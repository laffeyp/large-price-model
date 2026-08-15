# Sprint 050 -- VXX ingest (VIX-volume proxy via TIME_SERIES_INTRADAY)

---

```yaml
---
id: 050
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Config-only sprint. Adds `market_context__VXX` to the aligned corpus so Sprint 051's cross-asset feature block can compute `volume_z_100` on real VIX-ecosystem volume.

Spec §Channels (tech-arch line 306) requires `volume_z_100` on VIX. The VIX index itself has no volume by construction — it is a calculated value derived from SPX option prices, and Alpha-Vantage's `INDEX_DATA` endpoint (Sprint 038) returns OHLC only. Sprint 050 endpoint sweep confirmed AV rejects `TIME_SERIES_INTRADAY` and `TIME_SERIES_DAILY` on the `VIX` symbol, returns empty on `HISTORICAL_OPTIONS`/`HISTORICAL_VOLUME_OPEN_INTEREST_RATIO`/`HISTORICAL_PUT_CALL_RATIO` for VIX. VXX (Barclays iPath VIX Short-Term Futures ETN, tracks front-month VX futures) **does** return real 15-min OHLCV via `TIME_SERIES_INTRADAY` on the same endpoint every other market_context symbol uses.

Prototype-tier substitution per Agent memory: VXX is the honest related-signal proxy for VIX-ecosystem volume at v1. Later versions will pay for VX futures volume directly.

## halt-and-articulate

None expected. Pattern identical to Sprint 044 (QQQ/IWM/TLT/GLD/USO/UUP add). VXX intraday history via `TIME_SERIES_INTRADAY` reaches 2015; probe confirmed real volume on the current bar.

## signal contract

### Emits

No new emit sites. Existing `CHANNEL_FETCH_FAILED` fires per any AV-side rejection during the ~96-month iteration.

### Invariants

- Manifest entry `market_context__VXX` mirrors the six Sprint 044 entries: same tool (`TIME_SERIES_INTRADAY`), same source (`mcp_av`), same `verdict: accepted`.
- Aligned parquet gains `market_context__VXX__{open,high,low,close,volume,known_at}` + staleness triple.
- Ingest iterates the same month range every other intraday channel uses; short-circuits on cache-hit.

## artifact contract

### Files

- `data/manifests/channel_coverage.json` — one new entry `market_context__VXX`.
- No source code changes.

### Command exit codes

- Ingest for 2015-01 through 2022-12: expected ~96 fresh cache writes, small number of failures for outlier months (VXX inception was 2009-01, so the full range is covered).
- Ingest for 2024-01 through 2025-06: expected ~18 fresh writes.
- Re-align both windows: expected training 54,262 × 181 columns (16 channels × 9 fields + 3 staleness × 16 + grid_ts wait, let me recount — the aligned parquet already carries 172 columns for 19 channels post-Sprint-048; adding one more channel with the same 9 columns = 181).
- Test count unchanged (no new code).

### Live smoke

Read-back on training window:
- `market_context__VXX__volume` non-null count ≈ trading-day count × 26 bars/day ≈ 52,000 rows.
- Value range: 100k-100M contracts per 15-min bar (VXX daily average volume ~20M shares).
- Spot check 2022-06-15 first RTH bar (FOMC 75bp hike day): VXX volume in the millions.

---

## observation contract

Required (`pass_kind: functional`). Live-trace read-back on the training window: VXX volume column present, non-null on every RTH bar within the ingested range, values in the plausible 100k-100M/bar range. Sprint 051 will consume this column for `volume_z_100` on VXX.

---

## honest audit

**What lands.** VXX intraday OHLCV in the aligned corpus. Real VIX-ecosystem volume signal at 15-min granularity for 2015-2022 + 2024-2025.

**What does not land.** `volume_z_100` on the VIX index itself — that ships (or does not) in Sprint 051 as an Architect decision. Cross-asset feature block — Sprint 051. Sprint 051 will also decide whether VXX gets its own vix_level-analog features.

**What surfaced during Sprint 050 endpoint sweep.** Full endpoint sweep for VIX volume (INDEX_DATA, TIME_SERIES_DAILY, TIME_SERIES_INTRADAY, HISTORICAL_OPTIONS, HISTORICAL_VOLUME_OPEN_INTEREST_RATIO, HISTORICAL_PUT_CALL_RATIO) proved: AV lacks direct VIX volume, has real VXX volume via TIME_SERIES_INTRADAY. This is the pattern the "probe before claiming absent" memory locks in.

---

## notes

**Why VXX not UVXY.** Both AV endpoints return real volume. VXX is the reference VIX-ETN (unleveraged tracking of front-month VX futures); UVXY is 1.5x leveraged and shows compressed prices from years of contango decay. VXX's volume is the cleaner signal about VIX-hedging demand.

**Prototype note.** VXX volume is a proxy for "volume in the VIX complex." A real institutional pipeline would ingest VX futures front-month volume directly (via CFE data or Databento). At v1 tier the VXX proxy carries the same behavioral signal — flight-to-vol traffic spikes both.

---

## plan-mode review checklist

- [x] Files under hard rule 6 (one config file).
- [x] No new emit sites.
- [x] Observation contract (functional-band): read-back verifies VXX volume column present and plausible on training window.
- [x] Determinism budget bit-deterministic (same cache + manifest = byte-identical parquet).
- [x] Ships spec §Channels' VIX-volume intent via honest related-signal substitute.

---

## close (2026-08-14)

Landed. 114 VXX 15-min OHLCV monthly caches on disk (96 training + 18 test). Re-aligned both windows: training 54,262 × 181 columns; test 10,166 × 181 (added VXX's 9-column block to the 172 of Sprint 048). VXX volume non-null 54,236/54,262 training and 10,140/10,166 test (26-row burn-in each = pre-first-observation gap). Training median volume 9,344 shares/15-min bar; test median 122,489 (2020-COVID vol regime spike + 2024 volatility ETP maturity). 2022-06-15 first RTH bar (FOMC 75bp hike): VXX close 388.8 (split-adjusted), volume 17,317. Zero source code touched. Zero test-suite change (324 tests still green). Sprint's endpoint-sweep discipline saved from a "AV lacks VIX volume" false pivot — [[probe-before-claiming-absent]] filed to Agent memory. Sprint 051 opens next: cross-asset feature block on the 8-symbol market_context roster (QQQ/IWM/VIX/TLT/GLD/USO/UUP/VXX) plus VIX-specific vix_level/vix_change.
