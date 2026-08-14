# Sprint 047 -- options volume (per-contract aggregation from HISTORICAL_OPTIONS)

---

```yaml
---
id: 047
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Ships the second spec §Channels options channel. Sprint 046 landed the put/call ratio; Sprint 047 lands aggregate options volume. Both channels named in spec, both ship. No scope reduction — Architect rule ratified 2026-08-14 and filed to Agent memory.

`HISTORICAL_OPTIONS` returns per-contract rows (~9,000-10,000 contracts per SPY date) with `volume`, `open_interest`, IV, Greeks, etc. The loader sums the `volume` field across all contracts per date to produce one aggregate scalar per date — total SPY options volume.

## halt-and-articulate

**Column-collision bug caught mid-sprint.** Both options channels initially declared `channel="options", symbol="SPY"` in the manifest. Aligned column names are `{channel}__{symbol}__*`, so both channels collapsed to `options__SPY__*`. Rename map in `align_channels` silently overwrote one with the other. Read-back after re-align showed shape (54262, 127) — same 127 as Sprint 046's single-options-channel state, meaning the new channel didn't add columns.

Fix: introduced `av_symbol` split in the manifest. `symbol` identifies the aligned column (`PCR_SPY`, `VOL_SPY`); `av_symbol` identifies the AV underlying (`SPY`). Ingest passes `av_symbol` to AV; loaders filter cache by `av_symbol` but tag DataFrame `symbol` with the manifest identifier. `run_alignment` reads both fields from the manifest and passes each to the loader.

Named because the split needs to propagate to any future channels that share an underlying but differ in aggregation.

**Files touched.** `src/price_space_llm/alignment/join.py`, `src/price_space_llm/alignment/__init__.py`, `scripts/ingest.py`, `tests/test_alignment.py`, `data/manifests/channel_coverage.json` (config). Three code files + one test file + one config file. Within hard rule 6.

## signal contract

### Emits

No new emit sites in `src/`. `CHANNEL_FETCH_FAILED` (Sprint 046 wiring) fires per HISTORICAL_OPTIONS failure with `exception_class=AlphaVantageResponseError` and `error_message` naming the AV-side "No data for symbol SPY on date YYYY-MM-DD" reason for holidays.

### Invariants

- `load_options_volume_bars` sums `volume` across every per-contract row per date, returning one row per date with the summed value in `close`.
- The DataFrame's `symbol` field carries the manifest identifier (e.g. `VOL_SPY`), not the AV underlying (`SPY`). Enables two channels on the same underlying without column collision.
- `av_symbol` defaults to `symbol` for back-compat with channels that don't need the split.
- Ingest sends AV requests with `symbol=av_symbol`; cache key includes params so requests targeting the same AV symbol but different tools cache separately.

## artifact contract

### Files modified

- `src/price_space_llm/alignment/join.py` — new `load_options_volume_bars`: walks HISTORICAL_OPTIONS cache dir, filters by `av_symbol` on `data[0].symbol`, sums `volume` per date, uniform-fills OHLC with the sum. `load_put_call_ratio_bars` gains `av_symbol: str | None = None` parameter (defaults to `symbol`). `run_alignment` HISTORICAL_PUT_CALL_RATIO and HISTORICAL_OPTIONS dispatch branches pass `av_symbol` from the manifest.
- `src/price_space_llm/alignment/__init__.py` — exported `load_options_volume_bars`.
- `scripts/ingest.py` — `_OPTIONS_PER_DATE_TOOLS` now includes `HISTORICAL_OPTIONS`. `_OPTIONS_EXTRACTORS` maps each tool to its extractor. `_load_accepted_channels` reads `av_symbol` (defaults to `symbol`). Options ingest loop picks the extractor per tool and passes `symbol=av_symbol` in AV params.
- `data/manifests/channel_coverage.json` — `options__PCR_SPY` renamed to `symbol="PCR_SPY", av_symbol="SPY"`. New `options__VOL_SPY` entry with `tool: HISTORICAL_OPTIONS, symbol: VOL_SPY, av_symbol: SPY`.
- `tests/test_alignment.py` — 4 new tests: `load_options_volume_bars` sums across contracts; filters by av_symbol; raises on empty directory; put/call loader honors av_symbol split.

### Command exit codes

- Training-window pull: `4772 ok, 80 failed` (80 = holiday "no data" from AV). Wall clock ~14 min at 150/min.
- Test-window pull: `897 ok, 17 failed` (holidays).
- Re-align × 2 windows, exit 0.
- Features × 2 + tokenize, exit 0.
- ruff, ruff format, mypy, pytest all green.
- Test count 300 → 304 (+4 alignment tests).

### Live smoke

Full ingest:
```
Training: 4772 ok, 80 failed (all holidays; AV returns "No data for SPY on date ...")
Test:     897 ok, 17 failed
```

Re-align both windows:
- Training: 54,262 × 136 columns (15 channels × 9 fields + grid_ts).
- Test:     10,166 × 136.

Read-back on training window:
- `options__VOL_SPY__close`: 2,007 fresh events (one per trading day × 8 years); value range 1,030,166 - 13,543,665 contracts/day.
- `options__PCR_SPY__close`: 2,004 fresh events; range 0.51-3.46.
- 52 null grid rows per channel (start-of-2015 pre-first-observation window).

Spot-check on 2022-06-15 first RTH bar (day of Fed's 75bp hike):
- PCR: 1.56
- VOL: 9,887,146 contracts

9.9M options contracts is real heavy-activity for an FOMC-decision day. Both channels present, distinct, and honest.

Features on 15-channel corpus:
- Training: 2,968,845 emitted + 286,875 failed (9.66% failure rate).
- Test: 554,066 + 55,894 (9.16%).

Token count 54,210 unchanged (SPY-derived).

---

## observation contract

Required (`pass_kind: functional`). Live-trace read-back at aggregate (2,007 fresh events matching trading-day count) and per-bar (2022-06-15 = 9.9M contracts, consistent with FOMC-decision heavy day). Four unit tests lock the invariants at synthetic-data resolution: per-date summation, av_symbol filtering, empty-directory guard, av_symbol/symbol split.

Column-collision fix proven by shape check: training aligned parquet went from 127 columns (Sprint 046, one options channel silently overwriting) to 136 columns (Sprint 047, two distinct options channels).

---

## honest audit

**What landed.** Both spec-declared options channels. Total SPY options volume 2015-2022 covered at ~2,004 fresh trading-day observations (~99% coverage; the ~50 gaps are pre-first-observation window plus market holidays). The av_symbol/symbol split unblocks any future channel that shares an underlying with an existing channel but computes a different aggregate.

**What did not land.** No new AV endpoint work; reused Sprint 035's HISTORICAL_OPTIONS extractor. No changes to the trainer, features, or tokenizer — those already handle the added channel via the same code paths.

**What surfaced during execution.** The column-collision bug from the naive manifest naming. The first re-align showed shape (54262, 127) which is the Sprint 046 state — same column count, no new channel. Rename-map silently overwrote one options channel with the other. Fix landed inside the sprint.

**What did not need work.** Sprint 046's blocking-bucket rate limiter (150/min) sustained the ~2000-call HISTORICAL_OPTIONS pull without a single rate-limit failure. Sprint 042's uniform OHLCV schema accepted the aggregate volume without modification. Sprint 036 storage discipline held through ~2000 new cache writes.

---

## notes

**Cache duplication.** Both options channels target the same underlying (SPY) but use different tools (HISTORICAL_PUT_CALL_RATIO vs HISTORICAL_OPTIONS). The cache key includes the tool, so responses cache into distinct sha256-named files under separate tool directories. No duplication.

**Uniform-fill for VOL_SPY.** Volume is an unbounded positive integer (1M-13M range). Filling `open=high=low=close=value` and `volume=0` keeps the aligned parquet schema uniform. Downstream feature computation reads `close`. The trainer's `log_return = log(close_t/close_{t-1})` on a step-function daily channel behaves the same way as VIX and the macros — long constant runs, `rolling_std_20 → 0`, `FEATURE_COMPUTATION_FAILED` per row. Real behavior of a daily channel on the 15-min grid.

**Why not build a "smart" per-channel schema.** The uniform OHLCV schema treats every channel identically for downstream code. A per-channel schema would require dispatch in the features layer. The uniform-fill's cost is zero information (open=high=low=close is redundant but not wrong).

**Contract-level aggregation is a real cost.** Each HISTORICAL_OPTIONS response is ~500KB-2MB of per-contract data. 2088 fresh calls = ~2-3 GB of raw JSON on disk. Storage discipline (Sprint 036) handled the volume without issue. Re-alignment reads and sums all contract rows each run; training-window re-align time went from 5 seconds (14 channels) to 25 seconds (15 channels) because the volume loader iterates ~18 million total contract rows across the 2000 dates. Acceptable at v1 scale; if this becomes a bottleneck a pre-computed daily aggregate could cache the per-date sum.

---

## plan-mode review checklist

- [x] Files under hard rule 6 (three code + one test + one config).
- [x] No new emit sites; existing CHANNEL_FETCH_FAILED wires through cleanly.
- [x] Observation contract (functional-band): 2,007 fresh events verified; 2022-06-15 spot check against real FOMC-day options activity.
- [x] Determinism budget bit-deterministic (same cache + manifest = byte-identical parquet).
- [x] Column-collision bug caught inside the sprint, fixed inside the sprint, named on the card.
- [x] Ships spec §Channels' second options channel — no scope reduction.

---

## close (2026-08-14)

Landed. Both spec-declared options channels populated with real values across both windows. Aligned parquet at 136 columns (15 channels). 304 tests passing. Four tools green. Options family complete. Phase A step 5 of 6 complete (Sprints 046+047 together); Sprint 048 (event tables — EARNINGS_CALENDAR + curated FOMC/CPI-release/options-expiry) opens next.
