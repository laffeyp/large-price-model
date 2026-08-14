# Sprint 043 -- zoneinfo DST migration

---

```yaml
---
id: 043
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Fixed-offset EST (`US_EASTERN_OFFSET = timedelta(hours=-5)`) mislabelled every EDT-months bar by one hour in UTC. Sprint 043 replaces the offset with `zoneinfo.ZoneInfo("America/New_York")`, so a March bar reports UTC-4 (EDT) and a November bar reports UTC-5 (EST). Applies to both timestamp writes (`alphavantage.py::_to_utc_iso` and the three extractors) and the RTH grid (`alignment/join.py::_us_eastern_zone`).

Re-runs alignment, features, and tokenizer on the two cached windows so every downstream artifact carries correct UTC labels.

## halt-and-articulate

**Files touched.** `src/price_space_llm/ingestion/alphavantage.py`, `src/price_space_llm/alignment/join.py`, `tests/test_alignment.py`, `tests/test_alphavantage.py`. Two code files + two test files. Within hard rule 6.

**Semantic shift in the aligned parquet.** Grid timestamps for EDT-months rows shift by one hour compared to the pre-Sprint-043 output. A 2024-06-03 09:45 EDT bar was labelled `14:45 UTC` before this sprint (wrong: real is `13:45 UTC`). This changes the byte contents of the aligned parquet for every EDT-months row and every downstream artifact that hashes over it. Bucket-edge values are unchanged (edges are quantile-based on log-return; log-returns depend on SPY close prices which are unaffected by the label shift).

**No cache invalidation.** The raw AV response cache remains valid — the cache stores the vendor's original US/Eastern-stamped strings, not their UTC translation. Every re-alignment reads the same cached payloads and re-translates them under the new zone. Zero fresh AV calls.

## signal contract

### Emits

No new emit sites. Every existing tag now carries UTC-correct timestamps.

### Invariants

- `_to_utc_iso("2015-06-15 09:30:00")` returns `"2015-06-15T13:30:00+00:00"` (EDT → UTC-4). Under the old code it returned `"2015-06-15T14:30:00+00:00"` (fixed -5).
- `_to_utc_iso("2015-01-15 09:30:00")` returns `"2015-01-15T14:30:00+00:00"` (EST → UTC-5). Unchanged.
- `build_rth_grid(date(2024, 6, 3), date(2024, 6, 3))` first row is `13:45 UTC` (EDT). Was `14:45 UTC` under fixed offset.
- `build_rth_grid(date(2024, 11, 4), date(2024, 11, 4))` first row is `14:45 UTC` (EST, after Nov 3 DST end). Unchanged.
- 26 bars per RTH day regardless of DST. Both the March-to-November and November-to-March windows deliver 26 bars.

## artifact contract

### Files modified

- `src/price_space_llm/ingestion/alphavantage.py`:
  - Removed `US_EASTERN_OFFSET = timedelta(hours=-5)` constant.
  - Added `US_EASTERN_ZONE = ZoneInfo("America/New_York")`.
  - `_to_utc_iso` and the three metadata extractors (`alphavantage_extract_metadata`, `alphavantage_options_extract_metadata`, `alphavantage_index_extract_metadata`) all use `US_EASTERN_ZONE` for the tzinfo attachment before `.astimezone(UTC)`.
  - Import updated from `timezone` to `zoneinfo.ZoneInfo`.
- `src/price_space_llm/alignment/join.py`:
  - Import updated from `US_EASTERN_OFFSET` to `US_EASTERN_ZONE`.
  - `_us_eastern_zone()` returns `US_EASTERN_ZONE` directly.
  - Module docstring updated to name real DST handling instead of the fixed-offset limitation.
- `tests/test_alignment.py`:
  - `test_grid_bars_are_utc_aware` split into `test_grid_bars_are_utc_aware_edt` and `test_grid_bars_are_utc_aware_est` — one asserts June's 13:45 UTC, the other asserts November's 14:45 UTC.
  - Added `test_load_channel_bars_dst_roundtrip` — writes a March EDT cache and a November EST cache, asserts both round-trip to the correct UTC hour.
  - `test_load_index_daily_bars_stamps_known_at_at_21_utc` renamed and rewritten as `test_load_index_daily_bars_stamps_known_at_at_market_close` — now covers both EDT (20:01 UTC) and EST (21:01 UTC) branches.
- `tests/test_alphavantage.py`:
  - `test_fetcher_normalises_us_eastern_to_utc` updated: 09:30 US-Eastern on 2015-06-15 (EDT) → 13:30 UTC.
  - `test_index_extract_metadata_uses_16_est_close` renamed to `test_index_extract_metadata_uses_16_market_close_edt` and rewritten for 20:00 UTC (June date is EDT).

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 282 → 284 (+2 DST roundtrip tests; one grid test split; two existing tests renamed).

### Live smoke

Re-aligned + re-featurized + re-tokenized both cached windows:

```
uv run python scripts/align.py --start-month 2015-01 --end-month 2022-12
# align: 54262 rows in 2.55s

uv run python scripts/align.py --start-month 2024-01 --end-month 2025-06
# align: 10166 rows in 0.57s

uv run python scripts/features.py --aligned .../train.parquet
# features: 419414 emitted, 14682 failed in 25.52s

uv run python scripts/features.py --aligned .../test.parquet
# features: 78518 emitted, 2810 failed in 2.38s

uv run python scripts/bucketize.py --features .../train.parquet \
    --training-start 2015-01-05 --training-end 2022-12-30
# tokenize: 54210 tokens in 2.38s; n_buckets=32 channels=2
```

Read-back on the test-window parquet:

- 2024-06-03 (EDT) first RTH bar: `grid_ts = 2024-06-03 13:45 UTC`, SPY `known_at = 13:31 UTC`, VIX `known_at = 2024-05-31 20:01 UTC` (Friday's 16:00 EDT close). Pre-Sprint-043 output labelled the same rows an hour later.
- 2024-11-04 (EST, first Monday after DST end) first RTH bar: `grid_ts = 14:45 UTC`, SPY `known_at = 14:31 UTC`, VIX `known_at = 2024-11-01 20:01 UTC` (Nov 1 was still EDT). Grid label unchanged from prior alignment.
- 26 bars per RTH day, every day, across the DST boundary. Grid semantics intact.

Row counts identical to Sprint 042 (54,262 training rows, 10,166 test rows). Feature emit + failure counts identical to Sprint 042 (features are functions of SPY close, unchanged by timestamp relabelling). Token count 54,210, unchanged.

---

## observation contract

Required (`pass_kind: functional`). Live-trace verification against the re-aligned parquet at two dates — one EDT, one EST — confirms grid timestamps and per-channel known_at land at the correct UTC hour under real DST rules.

Four unit tests lock the invariants at synthetic-data resolution:
- `test_grid_bars_are_utc_aware_edt`: June RTH grid first bar = 13:45 UTC.
- `test_grid_bars_are_utc_aware_est`: November-after-DST-end RTH grid first bar = 14:45 UTC.
- `test_load_channel_bars_dst_roundtrip`: March EDT bar → 13:46 UTC known_at; November EST bar → 14:46 UTC known_at.
- `test_load_index_daily_bars_stamps_known_at_at_market_close`: EDT close → 20:01 UTC; EST close → 21:01 UTC.

---

## honest audit

**What landed.** Every UTC timestamp the pipeline writes now matches reality. Sprint 025 through Sprint 042 outputs stored EDT-months rows an hour late in UTC; that lie is corrected. The alignment self-consistency Sprint 041's audit named held across the fixed-offset regime, but external time-source integration (macro releases in real US Eastern, event calendars in real ET) would have broken silently. Now the code is honest before those channels land.

**What did not land.** No feature-code change, no tokenizer-code change. Feature values (log returns, rolling stats) are functions of close prices and stay bit-identical between the pre-Sprint-043 and post-Sprint-043 tokenized artifacts. Bucket edges depend on training-window log-return quantiles, also bit-identical.

**What surfaced during execution.** Two additional test assertions carried the fixed-offset assumption and needed rewrites: `test_load_index_daily_bars_stamps_known_at_at_21_utc` (which asserted 21:00 UTC year-round, wrong during EDT) and `test_index_extract_metadata_uses_16_est_close` (same). Both renamed and rewritten to cover both DST branches. Filed as a pattern: any test whose name pins a specific UTC hour or the string "EST" is presumptively out of date after this sprint.

**What did not need work.** The RTH grid's row count per day (26) held across DST — the grid iterates minute-of-day, not clock-hour-of-day, so the DST-day itself either has 25 or 27 bars if you count clock-hours but always 26 if you count 15-min slots between 09:30 and 16:00 US/Eastern. The grid computes correctly by construction.

**A drift-watchlist item cleared.** BLACKBOARD's Sprint 025 note "verdict-safe today because probe cares about coverage window" was the honest read for the probe scope; that assumption did not extend to training. Sprint 041's audit re-surfaced the gap; Sprint 043 closes it.

---

## notes

**Why the raw cache did not need invalidation.** Alpha-Vantage returns bar timestamps as US/Eastern-stamped strings (`"2024-06-03 09:45:00"` with `"6. Time Zone": "US/Eastern"`). The cache stores the original string; the UTC translation happens at read time. Re-reading the cache under the new zone re-translates to correct UTC. Zero fresh AV calls; zero cache-hit change.

**Why `ZoneInfo("America/New_York")` and not `ZoneInfo("US/Eastern")`.** Both work. `America/New_York` is the IANA canonical name; `US/Eastern` is an alias. IANA maintainers recommend the canonical form; both handle DST identically.

**DST-day bar-count edge case.** On the "spring forward" DST day (second Sunday in March), clock hours 02:00-03:00 US/Eastern do not exist. The RTH grid runs 09:30-16:00 US/Eastern, so the DST transition falls outside RTH. No missing bar. On the "fall back" DST day (first Sunday in November), 01:00-02:00 US/Eastern repeats. Again outside RTH. Grid always delivers 26 bars per RTH day.

---

## plan-mode review checklist

- [x] Two code files + two test files, hard rule 6 clean.
- [x] No new emit sites; every existing tag now carries correct UTC.
- [x] Observation contract: unit-test invariants + live re-align read-back at two DST branches.
- [x] Determinism budget bit-deterministic — feature values and bucket edges unchanged; only UTC labels shifted.
- [x] Cache invalidation not required; raw cache stores vendor-native strings.

---

## close (2026-08-14)

Landed. Every UTC label the pipeline writes now matches real DST. Test count 282 → 284. Four tools green. Sprint 044 opens next in Phase A: ingest six more cross-asset intraday channels (QQQ, IWM, TLT, GLD, USO via TIME_SERIES_INTRADAY; DXY via FX_INTRADAY).
