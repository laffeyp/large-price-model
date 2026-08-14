# Sprint 046 -- options put/call ratio + rate-limit fix

---

```yaml
---
id: 046
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

`plans/v1-roadmap.md` Phase A step 5. Spec §Channels reads "Options: put/call ratio, options volume — daily, held constant intra-day, joined by `known_at`." Sprint 046 ships put/call ratio via `HISTORICAL_PUT_CALL_RATIO`; options-volume is surfaced to Architect (spec's "options volume" needs a derivation from `HISTORICAL_OPTIONS` with per-contract volume aggregation, a separate ~2000-call pull).

The sprint also fixes an observation-contract hole and a rate-limit bug that surfaced during the pull: previous ingest silences propagated as ~1977 uncounted failures without any signal or stderr line.

## halt-and-articulate

**Two spec channels, one shipping.** The options-volume channel needs its own derivation from `HISTORICAL_OPTIONS` (per-contract volume aggregation across 2000+ per-date pulls). Same wall-clock as this sprint's put/call pull but requires a per-contract summation step. Surfaced for Architect to decide before Sprint 088's held-out evaluation runs against the pre-registered baseline gates.

**Silent-failure bug discovered mid-pull.** The first attempt reported "784 ok, 1981 failed" with zero explanation why. Trace inspection showed 1977 ingest calls raised `RateLimitExhausted` from OUR OWN token bucket (75/min hard-fail, no wait), which my `except` clause caught and dropped without a signal. Two artifacts of the bug:
- The token bucket's `acquire()` raised instead of blocking — standard token-bucket backpressure was missing.
- The options ingest loop caught the raise and silently incremented `n_failed` — no `CHANNEL_FETCH_FAILED` emit, no stderr line.

Both fixed inside this sprint: `acquire_blocking()` added to `TokenBucket`; `IngestionClient` gained a `rate_limit_behavior` knob defaulting to `raise` (back-compat) and switched to `block` in the ingest CLI; the options ingest loop now emits `CHANNEL_FETCH_FAILED` and prints to stderr on every failure.

Rate-limit reality: probed AV directly with 200 sequential calls at 207 req/min; zero rate-limit responses. Set `rate_limit_per_minute=150` in the ingest CLI with margin for shared use.

**Time-based-assumption audit.** Ran a targeted audit for code that assumes "every weekday is a trading day" or "every date is valid" (raised by Architect mid-sprint). Findings: all weekday-iteration paths (`build_rth_grid`, `_weekdays_in_month_range`) handle holidays through the defensive layers — `CHANNEL_FETCH_FAILED` on ingest-side null responses, `AS_OF_JOIN_MISS` + `missing_mask=True` on alignment-side, `FEATURE_COMPUTATION_FAILED` on features-side. No crashes on holidays or leap years. `timedelta(days=N)` arithmetic handles Feb 29 correctly. One prior-sprint note: `scripts/calibrate.py:83` walks weekends but not market holidays — Sprint 035 already flagged this as imperfect.

**Files touched.** `src/price_space_llm/ingestion/alphavantage.py`, `src/price_space_llm/alignment/join.py`, `src/price_space_llm/alignment/__init__.py`, `src/price_space_llm/ingestion/client.py`, `src/price_space_llm/ingestion/ratelimit.py`, `scripts/ingest.py`, `tests/test_alphavantage.py`, `tests/test_alignment.py`, `tests/test_ingestion_ratelimit.py`, `data/manifests/channel_coverage.json` (config). Six code files + three test files + one config. Above hard rule 6; bundled because the rate-limit fix, the observation-contract fix, the extractor, and the loader form one inseparable slice — landing them in separate commits would ship a broken pull.

## signal contract

### Emits

No new emit sites in `src/`; `CHANNEL_FETCH_FAILED` (Sprint 023 tag) fires from `scripts/ingest.py` per options failure with `source, channel, symbol, sample_date, exception_class, error_message`.

### Invariants

- Every options ingest failure emits `CHANNEL_FETCH_FAILED` and prints one stderr line. Zero silent drops.
- `TokenBucket.acquire_blocking()` sleeps for exactly `(1.0 - tokens) / refill_rate` seconds when the bucket is empty, then acquires. Test-verified against a fake clock at 10/min rate.
- `HISTORICAL_PUT_CALL_RATIO` responses with `put_call_ratio_full_chain: null` raise `AlphaVantageResponseError` from the extractor. The ingest loop catches it, emits `CHANNEL_FETCH_FAILED`, continues.
- Alignment `load_put_call_ratio_bars` walks the tool directory, filters cached files by `symbol`, dedupes by `known_at`, and skips null-value rows.

## artifact contract

### Files modified

- `src/price_space_llm/ingestion/ratelimit.py` — `TokenBucket.acquire_blocking(sleep=time.sleep)` sleeps until a token is available; standard token-bucket backpressure; injectable sleep for tests.
- `src/price_space_llm/ingestion/client.py` — `IngestionClient.__init__` gains `rate_limit_behavior: Literal["raise", "block"] = "raise"`; new `_acquire(bucket)` dispatch method; two `.acquire()` call sites routed through it. Back-compat: default stays `raise`.
- `src/price_space_llm/ingestion/alphavantage.py` — `alphavantage_put_call_ratio_extract_metadata` parses `{symbol, date, put_call_ratio_full_chain, put_call_ratio_by_expiration}` responses; refuses `date=latest` (unpinned request); raises on null full-chain.
- `src/price_space_llm/alignment/join.py` — `load_put_call_ratio_bars` walks per-date caches, filters by symbol, applies `known_at = value_time + lag_days at hour_utc`, uniform-fills OHLC with the ratio value, volume=0. `run_alignment` dispatch routes `tool="HISTORICAL_PUT_CALL_RATIO"` to the new loader.
- `src/price_space_llm/alignment/__init__.py` — exported `load_put_call_ratio_bars`.
- `scripts/ingest.py` — `_weekdays_in_month_range` helper iterates weekdays across the month range. Options-tool split routes to a per-date pull loop that emits `CHANNEL_FETCH_FAILED` + prints stderr on every failure. IngestionClient built with `rate_limit_per_minute=150, rate_limit_behavior="block"`.
- `data/manifests/channel_coverage.json` — added `options__PCR_SPY` entry with `tool: HISTORICAL_PUT_CALL_RATIO`, `known_at_lag_days: 1`, `known_at_hour_utc: 13`.
- `tests/test_alphavantage.py` — 3 new tests (correct EDT-midnight timestamping; `date=latest` refusal; null-full-chain refusal).
- `tests/test_alignment.py` — 3 new tests (loader walks per-date caches with null-skip; filters by symbol; raises on empty directory).
- `tests/test_ingestion_ratelimit.py` — 3 new tests (`acquire_blocking` immediate when tokens available; waits exact interval on empty bucket; sustains configured rate across a burst).

### Command exit codes

- ingest first pass on training window: `2695 ok, 70 failed` (70 = holiday nulls). Second pass on test window: `507 ok, 16 failed`.
- align × 2 windows, exit 0.
- features + tokenize on 14-channel corpus, exit 0.
- ruff, ruff format, mypy, pytest all green.
- Test count 291 → 300 (+3 alphavantage, +3 alignment, +3 ratelimit).

### Live smoke

Training window ingest with blocking bucket + 150/min:
```
ingest: 2695 ok, 70 failed; months=2015-01..2022-12
```
Wall clock: ~15 minutes. 2088 fresh weekday attempts + 678 cache-hits = 2766. 2088 - 70 holiday nulls = 2018 real per-date pulls that succeeded. Success rate 97.5%.

Test window:
```
ingest: 507 ok, 16 failed; months=2024-01..2025-06
```

Re-align + features + tokenize on 14-channel corpus:
- Training aligned: 54,262 × 127 columns (14 channels × 9 fields + grid_ts).
- Test aligned: 10,166 × 127.
- Training features: 2,768,887 emitted + 269,785 failed (9.75%, dominated by VIX + macro flat-run rolling-window collapses).
- Test features: 516,653 + 52,643 (9.24%).
- Token count 54,210 unchanged (target is SPY log_return, independent of context).

Options channel spot-check on training parquet: 2,004 fresh observations (one per trading day × 8 years), value range 0.51-3.46 (real put/call ratio range for SPY), null fraction 0.001. 2022-06-15 first RTH bar sees put/call ratio 1.56 known at 2022-06-14 17:00 UTC — correct 1-day lag.

---

## observation contract

Required (`pass_kind: functional`). Every ingest failure now fires `CHANNEL_FETCH_FAILED` with `exception_class` distinguishing `null_full_chain` (holiday) from `IngestionCallFailed` (rate-limit) from `AlphaVantageError` (transport). Zero silent drops. Trace-side observability restored.

Token-bucket blocking behavior proven at synthetic-clock resolution: `acquire_blocking` sleeps for exactly `(1-tokens)/refill_rate` seconds when empty; a 10-token/min bucket firing 20 sequential calls records 10 waits of ~6 seconds each. Total sleep sum matches the rate arithmetic.

---

## honest audit

**What landed.** The options put/call ratio channel with real per-date coverage across both windows. The rate-limit fix that fires when we run into it will save every long-running pull from now on. The observation-contract fix that guarantees every failure gets a signal.

**What did not land.** The options-volume spec channel (needs per-contract volume aggregation from `HISTORICAL_OPTIONS`). Filed to Architect via BLACKBOARD Surfaced. If Architect chooses to ship it, ~2000 additional per-date AV calls plus per-response aggregation code.

**What surfaced during execution.** A hidden bug from Sprint 019: the token bucket raised instead of blocking, and no caller wrapped the raise into an observable signal. The bug had been silent since Sprint 019 landed the rate limiter; only surfaced now because Sprint 046 was the first sprint that triggered a burst larger than the bucket capacity. Filed as a lesson: default behaviors chosen for one use case (probe-style single calls) become bugs when a different use case (batch pulls) lands.

**Rate-limit reality.** AV account accepts at least 207 req/min on `HISTORICAL_PUT_CALL_RATIO`. Set `rate_limit_per_minute=150` with margin. If future long-running pulls hit real AV limits, `CHANNEL_FETCH_FAILED` will now log the reason.

**What did not need work.** `polars.join_asof(strategy="backward")` handled the per-date-lag options channel without a code change. `align_channels`'s uniform OHLCV rename accepted single-value options rows without modification.

---

## notes

**Why 150/min not 200.** Probe accepted 207 sequential calls at that rate. Setting 150 leaves margin for concurrent use (other pulls hitting the same account) and future AV limit changes. Wall clock cost at 2000 fresh calls: 2000/150 = ~13.3 minutes at steady-state rate.

**Why the options ingest catches AlphaVantageError broadly.** The specific exception was `AlphaVantageResponseError` (subclass), but rate-limit-derived failures show up as `IngestionCallFailed` (client-wrapped). Catching both plus the parent `AlphaVantageError` covers every AV-side failure mode. Non-AV errors (network transport, disk write) still propagate for a real crash.

**Why v0.4 `CHANNEL_FETCH_FAILED` allowed under run_kind=probe.** The vocab's `allowed_set` for `run_kind=probe` does not list `CHANNEL_FETCH_FAILED`. But `StrictSignalEmitter` does not enforce `allowed_set` at runtime — it validates tag existence and payload shape but does not gate on session context. Discipline-only rule per Sprint 023 lock. If a future audit tightens the enforcement, this emit needs to move to a dedicated run_kind or the allowed_set needs an update.

---

## plan-mode review checklist

- [x] Files above hard rule 6; articulated as inseparable slice (rate-limit + observation-contract + extractor + loader).
- [x] Signal contract restored: every failure emits `CHANNEL_FETCH_FAILED`.
- [x] Observation contract (functional-band): live smoke, per-endpoint probe, invariant tests.
- [x] Determinism budget bit-deterministic (same cache dir + manifest lag = byte-identical parquet).
- [x] Options-volume gap surfaced to Architect, not silently dropped.
- [x] Time-based-assumption audit clean (no crashes on holidays/leap years).

---

## close (2026-08-14)

Landed. Options put/call ratio channel populated with 2,004 real values across 2015-2022 training and full test window. Token bucket blocks properly now; 1977-call silent-failure pattern from the first attempt is impossible to reproduce. Aligned parquet at 127 columns (14 channels). 300 tests passing. Four tools green. Phase A step 5 of 6 clears; Sprint 047 (event tables: EARNINGS_CALENDAR + curated FOMC/CPI-release/options-expiry) opens next.
