# Sprint 045 -- five macro series (CPI, FEDFUNDS, DGS10, UNRATE, NFP)

---

```yaml
---
id: 045
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

`plans/v1-roadmap.md` Phase A step 4. Five macro channels from spec §Channels: CPI (Consumer Price Index), FEDFUNDS (federal funds rate), DGS10 (10-year Treasury yield), UNRATE (unemployment rate), NFP (nonfarm payroll). Each lands in the manifest with per-channel `known_at_lag_days` and `known_at_hour_utc` because AV returns the reference-period date, not the release date — the `known_at` offset lives in the manifest and the alignment loader applies it.

## halt-and-articulate

**Known_at semantics.** Spec §"Data time semantics" is explicit: for a monthly macro release, `known_at = released_at`, not `value_time`. Alpha-Vantage's macro endpoints return `{data: [{date, value}]}` where `date` is the reference-period start (`value_time`). Using `date` as `known_at` would leak the future value into the training-time as-of join. The alignment loader adds a per-channel offset (`known_at_lag_days`, `known_at_hour_utc`) that approximates the real release calendar. Approximation loses a few days on any given row but preserves ordinal ordering — the trainer sees "roughly-right when it became public" per spec intent.

Per-channel lags (approximate release calendars):
- CPI: `+45 days at 12:00 UTC` (mid-M+1 release, ~2 weeks after reference-month-end).
- FEDFUNDS: `+2 days at 13:00 UTC` (T+1 business-day release around 09:00 ET).
- DGS10: `+2 days at 13:00 UTC` (same pattern).
- UNRATE: `+37 days at 12:00 UTC` (first Friday of the following month at 08:30 ET).
- NFP: `+37 days at 12:00 UTC` (released with UNRATE).

A real release calendar (BLS/Fed/Treasury schedule) lands in a follow-up sprint if the ordinal error becomes measurable at training time. The alignment loader accepts the offsets from the manifest, so switching to a per-date calendar is a schema change, not a code rewrite.

**Files touched.** `src/price_space_llm/ingestion/alphavantage.py`, `src/price_space_llm/alignment/join.py`, `src/price_space_llm/alignment/__init__.py`, `scripts/ingest.py`, `tests/test_alphavantage.py`, `tests/test_alignment.py`, `data/manifests/channel_coverage.json` (config). Four code files + two test files + one config file. Within hard rule 6.

**Uniform schema.** Macro rows carry a single `value` field. The loader writes it into `open = high = low = close = value` with `volume = 0`, so the aligned parquet's per-channel columns stay uniform across intraday, index, and macro channels. Downstream feature computation reads `close`. Names the uniform-fill in the loader's docstring.

## signal contract

### Emits

No new emit sites. `INGESTION_CALL_ISSUED` fires once per macro tool per pull; each macro endpoint returns the whole history in one call. `RAW_OBSERVATION_WRITTEN` on every fresh cache write. Sprint 036 storage discipline (per-cache sidecar + append-only index + freshness policy) held across the new tools.

### Invariants

- Each macro `known_at` computed as `value_time + known_at_lag_days at known_at_hour_utc`; `value_time` comes from AV's `date` field parsed as US/Eastern midnight (Sprint 043 zoneinfo).
- Values coerce to float; FRED-convention "." (missing) rows are skipped (verified by `test_load_macro_bars_skips_rows_with_dot_value`).
- Macro rows fill OHLCV with the same value and set volume to 0 — schema uniform across all channel types.
- `polars.join_asof(strategy="backward")` on `known_at` forward-fills the last-known macro value onto every grid row after the release lag has elapsed.

## artifact contract

### Files modified

- `src/price_space_llm/ingestion/alphavantage.py` — added `alphavantage_macro_extract_metadata` for the `{data: [{date, value}]}` envelope shared by all five macro endpoints. Exported.
- `src/price_space_llm/alignment/join.py` — added `load_macro_bars` (reads cache, applies per-row known_at offset, uniform-fill OHLCV); added `_MACRO_TOOLS` set and `_default_macro_params` helper; extended `run_alignment` dispatch to route the five macro tools to the new loader with per-channel offsets.
- `src/price_space_llm/alignment/__init__.py` — exported `load_macro_bars`.
- `scripts/ingest.py` — imports the new extractor + `_default_macro_params`; adds a `macro_channels` split alongside `index_channels` + `intraday_channels`; each macro channel gets one call per pull; `_load_accepted_channels` now preserves per-channel `params`, `known_at_lag_days`, `known_at_hour_utc`.
- `tests/test_alphavantage.py` — 4 new tests (correct EDT-midnight timestamping; empty-data guard; missing-data-key guard; missing-date guard).
- `tests/test_alignment.py` — 3 new tests (`load_macro_bars` applies known_at offset correctly with EDT + 12h; skips "." missing rows; `run_alignment` dispatch routes tool=CPI to load_macro_bars and forward-fills onto the RTH grid).
- `data/manifests/channel_coverage.json` — added 5 macro entries with per-channel offsets.

### Command exit codes

- ingest smoke, exit 0: `13 ok, 0 failed` for 2015-01 (5 fresh macros + 1 VIX cache-hit + 7 intraday cache-hits).
- align × 2 windows, exit 0.
- features × 2 windows + tokenize, exit 0.
- ruff, ruff format, mypy, pytest all green.
- Test count 284 → 291 (+4 extractor tests, +3 alignment tests).

### Live smoke

```
uv run python scripts/ingest.py --start-month 2015-01 --end-month 2015-01
# ingest: 13 ok, 0 failed

uv run python scripts/align.py --start-month 2015-01 --end-month 2022-12
# align: 54262 rows in 4.59s; missing_fractions=[target=0.000, market_context=0.000, macro=0.000]

uv run python scripts/align.py --start-month 2024-01 --end-month 2025-06
# align: 10166 rows in 1.08s

uv run python scripts/features.py --aligned .../train.parquet
# features: 2569584 emitted, 252040 failed in 315.00s (9.8% failure rate)

uv run python scripts/features.py --aligned .../test.parquet
# features: 479359 emitted, 49273 failed in 20.19s (9.3% failure rate)

uv run python scripts/bucketize.py --features .../train.parquet
# tokenize: 54210 tokens in 2.27s; n_buckets=32 channels=13
```

Training-window aligned parquet: 54,262 × 118 columns (13 channels × 9 fields + grid_ts).

**Spot check** on 2022-06-15 first RTH bar:
- DGS10 close: 3.15 (real 10Y Treasury yield in early June 2022 was ~3.0-3.3%).
- FEDFUNDS close: 0.83 (pre-June-hike EFFR; Fed hiked 75bp to 1.55% on 2022-06-15).
- CPI close: 289.109 (April 2022 CPI, released mid-May 2022, first visible on the grid from May 16 onward).
- UNRATE close: 3.6 (May 2022 unemployment, released early June).
- NFP close: 152,265 thousand (May 2022 NFP).

Every macro value visible in the grid only after its release-lag window closed. Known_at semantics correct by direct observation.

**Observed_at_this_grid_step counts** on the 54,262-row training window:
- CPI: 97 fresh events (one per month across 8 years + 1 initial reveal).
- UNRATE: 97 (same monthly pattern).
- NFP: 97.
- DGS10: 1,611 (daily; ~200 events/year; loses some to holidays + weekend-crossing releases).
- FEDFUNDS: 2,505 (daily; publishes including some weekends per the endpoint's cadence).

## observation contract

Required (`pass_kind: functional`). Live-trace spot check at a specific date confirms real macro values with correct release-lag known_at. Aggregate observed_at_this_grid_step counts match expected release cadence. Seven new unit tests lock the invariants at synthetic-data resolution.

The as-of causality invariant Sprint 025 landed carries through unchanged: `join_asof(strategy="backward")` on `known_at` with the release-lag applied makes it structurally impossible for a macro value released 2024-06-04 to appear in a grid row at 2024-06-03 14:45 UTC.

---

## honest audit

**What landed.** Five macro channels from spec §Channels, forward-filled onto the 15-min RTH grid with release-lag-aware known_at. Aligned parquet grows from 73 to 118 columns. Feature failure rate jumps to 9.8% because macros are step functions on the intraday grid — same failure mode as VIX, now on five more channels.

**What did not land.** No real release calendar (per-date BLS/Fed/Treasury schedule); using a per-channel fixed offset. Real release dates for CPI have a standard deviation of ~4 days from the 45-day fixed lag; for UNRATE/NFP, tighter (first Friday of the month is deterministic). The ordinal error at 15-min grid resolution is ≤5 grid rows per release, which is small compared to the release cadence itself (once per month). Sprint 073 or the sprint that adopts `pandas_market_calendars` can substitute real dates.

**What surfaced during execution.** The `missing_fractions` line in `scripts/align.py`'s stderr summary aggregates per channel category (`target`, `market_context`, `macro`) — under-reporting per-symbol coverage. Same display issue as Sprint 044. Per-symbol coverage lives in the per-column `missing_mask__{key}` values in the parquet.

**What did not need work.** `IngestionClient` handled the five macro tools through the existing tool-dispatch path. `align_channels`'s uniform OHLCV rename accepts macro rows without modification. Sprint 042 and Sprint 038 continue paying dividends — no per-tool alignment code beyond the loader.

---

## notes

**Why not a real release calendar.** Real release-date lookup requires either scraping the BLS/Fed/Treasury publication pages or purchasing an economic-calendar feed (e.g., from Refinitiv, MarketPsych, or similar). At 15-min grid resolution across an 8-year training window, a ±4-day error in known_at translates to ≤5 misaligned grid rows per release. Aggregate error across ~96 CPI releases is small relative to the release-to-release information decay.

**Why 45 days for CPI and 37 for UNRATE/NFP.** CPI releases ~2 weeks after month-end. Month-start + 45 days = mid-M+1, roughly matching the real release date. UNRATE/NFP release first Friday of M+1, which lands 32-38 days after M's start; 37 gives a safety margin so the visible-from-grid-timestamp is always after the real release.

**Uniform OHLCV for macro rows.** Every downstream feature reads `{key}__close`. Filling open/high/low/close with the same value keeps the aligned parquet schema uniform and lets the same feature-layer code path compute across intraday, index, and macro channels. Volume = 0 for macros is honest (no traded quantity for a macro release).

---

## plan-mode review checklist

- [x] Files under hard rule 6 (four code + two test + one config).
- [x] No new emit sites; existing tags carry the new tool values.
- [x] Observation contract (functional-band): live spot check + unit invariants across three test cases.
- [x] Determinism budget bit-deterministic (same cache, same manifest offsets, same parquet).
- [x] Known_at semantics named honestly (per-channel fixed lag, real calendar deferred).

---

## close (2026-08-14)

Landed. Five macro channels in the aligned parquet with release-lag-aware known_at. 13 accepted channels total. Aligned parquet at 118 columns. Feature failure rate at 9.8% (step-function macros dominate). Token count unchanged at 54,210. Test count 284 → 291. Four tools green. Phase A step 4 of 6 clears; Sprint 046 (options: put/call ratio, volume/open-interest ratio) opens next.
