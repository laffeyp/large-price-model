# Sprint 042 -- aligned parquet enrichment (OHLCV + staleness columns)

---

```yaml
---
id: 042
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

`plans/v1-roadmap.md` Phase A first step. The aligned parquet is close-only per channel and carries no staleness columns. Spec §5 mandates full OHLCV plus three "load-bearing" staleness columns per channel: `missing_mask__{key}`, `age_since_known_at__{key}`, `observed_at_this_grid_step__{key}`. Every target-side feature the spec §6 declares (`bar_shape`, `range_pct`, `volume_z_100`, `dollar_volume`, `spread_proxy`, `realized_vol_30`) reads OHLCV from this file. The frozen normalizer's staleness signals (Phase B) read the three new columns from this file.

## halt-and-articulate

**Files touched.** `src/price_space_llm/alignment/join.py` (one code file), `tests/test_alignment.py` (four new tests). Within hard rule 6.

**Volume field on the index-data path.** `INDEX_DATA` returns OHLC per day, no volume. `load_index_daily_bars` writes `volume=0` for VIX rows to keep the schema uniform across channels. Downstream `volume_z_100` on VIX collapses to zero-variance and will emit `FEATURE_COMPUTATION_FAILED` per row; that surfaces the honest fact that VIX has no volume, rather than silently making one up. Named here so the feature sprint (Phase B) does not read `volume=0` as a real measurement.

**Rename map guards each OHLCV field.** `align_channels` renames only fields that exist on the incoming bars DataFrame. Legacy test fixtures that construct bars with `{known_at, close, channel, symbol}` still work — the rename picks up `close` alone and skips the others. Back-compat retained for the ~20 existing alignment tests.

## signal contract

### Emits

No new emit sites. `ALIGNMENT_ROW_EMITTED` and `AS_OF_JOIN_MISS` fire as before.

### Invariants

- Every non-null channel row in the aligned parquet carries `{open, high, low, close, volume}` under the `{channel}__{symbol}__{field}` naming.
- `missing_mask__{key}` = True iff the close column is null (as-of join found no eligible row).
- `observed_at_this_grid_step__{key}` = True iff the picked `known_at` differs from the previous grid row's picked `known_at`. False on the first row of a missing streak.
- `age_since_known_at__{key}` = 0 on a fresh observation; increments by 1 per grid row with the same `known_at`; resets to 0 while `missing_mask` is True.

## artifact contract

### Files modified

- `src/price_space_llm/alignment/join.py`:
  - `load_channel_bars` returns `{known_at, open, high, low, close, volume, channel, symbol}` per bar. Reads `1. open` / `2. high` / `3. low` / `4. close` / `5. volume` from the Alpha-Vantage intraday response.
  - `load_index_daily_bars` returns the same schema; `volume=0` for daily index responses.
  - `align_channels` renames all present OHLCV fields into `{key}__{field}` columns; computes the three staleness columns per channel via a single pass over each channel's known_at + close series.
- `tests/test_alignment.py`:
  - `test_load_channel_bars_parses_cache` updated for OHLCV columns.
  - `test_align_channels_emits_ohlcv_columns_per_channel` (new).
  - `test_align_channels_missing_mask_true_when_no_prior_observation` (new).
  - `test_align_channels_observed_at_this_grid_step_and_age_since_known_at` (new).
  - `test_align_channels_age_stays_zero_while_missing_mask_true` (new).

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 278 → 282 (+4 staleness/OHLCV invariants).

### Live smoke

Re-aligned both cached windows:

```
uv run python scripts/align.py --start-month 2015-01 --end-month 2022-12
# align: 54262 rows in 3.04s; missing_fractions=[target=0.000, market_context=0.000]

uv run python scripts/align.py --start-month 2024-01 --end-month 2025-06
# align: 10166 rows in 0.65s; missing_fractions=[target=0.003, market_context=0.000]
```

Training-window parquet shape 54,262 × 19 columns (up from 5). Column list: `grid_ts`, per-channel `known_at + open + high + low + close + volume` (12), per-channel `missing_mask + observed_at_this_grid_step + age_since_known_at` (6). Two channels × 9 columns = 18 + grid_ts = 19.

Invariant read-back:

- SPY `observed_at_this_grid_step` fires at 52,434 of 54,262 grid rows (96.6%). The 1,828 non-fresh rows are backward-fills where a bar did not print at that RTH grid step (holidays, market halts, occasional AV coverage gaps that fall inside RTH).
- VIX `observed_at_this_grid_step` fires at 2,019 grid rows — one per trading day, matching the spec: VIX daily close prints at 21:01 UTC outside RTH, so the "fresh" event lands on the first RTH bar of the next day (14:45 UTC) that finally sees a new `known_at`.
- SPY `age_since_known_at` max = 25, mean = 0.43. Max 25 covers a full day of backfill during a rare halt or gap. VIX max = 51, mean = 13.3 — 51 spans a two-day weekend (26 Friday bars + 26 Monday bars − 1).
- SPY `missing_mask` sum = 26 (one full RTH day of no SPY prints somewhere in 8 years). VIX `missing_mask` sum = 0 (VIX daily history reaches 1990, so every 2015+ grid_ts has a prior known_at).

Spot-check 2024-06-03 14:45 UTC (Monday morning, first RTH bar):
- SPY open 515.15, high 515.29, low 514.72, close observed_true, age 0.
- VIX close observed_true, age 0 (Friday's close 12.92, `known_at = 2024-05-31 21:01 UTC` — a fresh known_at relative to the prior grid step, which had seen Thursday's close).

15 minutes later, 15:00 UTC:
- SPY fresh again (age 0) — every 15-min bar prints a new SPY observation.
- VIX still on Friday's close (age 1) — VIX does not update until 21:01 UTC on day D+1.

Behavior matches spec §5.

---

## observation contract

Required (`pass_kind: functional`). Column-presence check on the training-window parquet: 19 columns, all six OHLCV + three staleness fields present per channel. Invariant read-back verified at aggregate (freshness counts, age extremes, missing_mask sums) and per-bar (Monday morning spot check).

Four new unit tests lock the invariants at synthetic-data resolution: OHLCV round-trip through the aligned frame, missing_mask true before the first observation, staleness counter increments correctly across gaps, age stays zero while missing.

Existing 23 alignment tests continue to pass; the rename map's per-field guard preserved back-compat with fixtures that construct close-only bars.

---

## honest audit

**What landed.** Aligned parquet now carries every column the spec §5 declares. Downstream feature-layer sprints (Phase B: 048-055) can now compute the spec §6 features without a data-layer prerequisite.

**What did not land.** No feature computation. No consumer of the new columns yet. The four target-side features (`bar_shape`, `range_pct`, `volume_z_100`, `dollar_volume`, `spread_proxy`, `realized_vol_30`) land in Sprint 048; cross-asset in 049; macro/options/event in 050-052; session flags in 053.

**What surfaced during execution.** VIX volume is `0` on every row because INDEX_DATA does not carry volume. `volume_z_100` on VIX will collapse to a zero-variance z-score and fire `FEATURE_COMPUTATION_FAILED` per row. That is honest — the feature does not exist for a daily index — but the Phase B feature-layer sprint needs to name it explicitly so the failure count does not read as a bug. Filed to note on the roadmap Phase B entry.

**What did not need work.** Sprint 025's `join_asof(strategy="backward")` handled the wider schema without a code change beyond the rename map. Sprint 038's INDEX_DATA dispatch continued to route VIX through the daily-bar loader with no adjustment. Layered work paying off.

---

## notes

**Why compute staleness in Python, not Polars expressions.** The counter resets on `observed_at_this_grid_step=True` and clamps to 0 while `missing_mask=True`. A single-pass Python loop over ~65k rows takes ~30ms — well under the parquet write time. A Polars expression would need `cum_count_when(condition)` semantics that Polars 1.x does not expose directly. Vectorizing this is a Phase C micro-optimization if profiling shows it matters.

**Why `volume` cast to `int64`.** Alpha-Vantage returns volume as a string decimal like `"1000000"` for intraday bars. Casting via `int(float(...))` accepts both integer and fractional-string forms without loss for the integer volume domain.

**Non-RTH VIX observation.** VIX daily close prints at 21:01 UTC. The RTH grid runs 14:45 through 21:00 UTC (US/Eastern 09:45 through 16:00 under the fixed offset). So `observed_at_this_grid_step` fires for VIX exactly once per trading day, on the FIRST RTH bar of the next day. That is what "fresh" means for a daily channel joined onto a 15-min grid; the alternative reading — that VIX observations should fire at 21:00 UTC — would require the grid to include a bar the RTH definition excludes.

---

## plan-mode review checklist

- [x] One code file + one test file. Hard rule 6 clean.
- [x] No new emit sites; existing sites unchanged.
- [x] Observation contract: column list, aggregate invariants, per-bar spot-check.
- [x] Determinism budget bit-deterministic — same cached input, byte-identical parquet output.
- [x] Downstream consumer sprint (Phase B) named; no premature feature computation.

---

## close (2026-08-13)

Landed. Aligned parquet at 54,262 × 19 columns for training window and 10,166 × 19 for test window. Every spec §5 column present. Test count 278 → 282. Four tools green. Phase A step 1 of 6 clears; Sprint 043 (`zoneinfo` DST migration) opens next.
