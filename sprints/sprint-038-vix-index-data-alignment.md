# Sprint 038 -- VIX via INDEX_DATA + daily-bars alignment path

---

```yaml
---
id: 038
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Sprint 023 dropped VIX from the manifest because `TIME_SERIES_INTRADAY` refused it. That reading was narrow. Alpha-Vantage carries VIX via the `INDEX_DATA` endpoint at daily/weekly/monthly granularity — 9,246 daily OHLC rows going back to 1990-01-02, current through the day of pull. The regime code has been substituting `target__SPY__rolling_std_20` for VIX terciles ever since. Sprint 038 lands the real signal.

The change touches four spots:
1. `alphavantage.py::alphavantage_index_extract_metadata` parses the INDEX_DATA response envelope (`{symbol, name, interval, data: [{date, open, high, low, close}]}`) and stamps `value_time` at the latest row's date + 16:00 US/Eastern → UTC, `known_at` at `value_time + 1 minute`.
2. `alignment/join.py::load_index_daily_bars` reads a cached INDEX_DATA response and returns `(known_at, close, channel, symbol)` bars — same shape `load_channel_bars` returns for intraday, so the downstream `join_asof(strategy="backward")` accepts them without changes.
3. `alignment/join.py::run_alignment` reads a per-channel `tool` field from the manifest (default `TIME_SERIES_INTRADAY`), dispatches INDEX_DATA to the daily loader and skips the per-month iteration, else runs the intraday path as before. Unsupported tools raise.
4. `scripts/ingest.py` reads the per-channel `tool` from the manifest, splits accepted channels into INDEX_DATA (one call per channel, whole history) and TIME_SERIES_INTRADAY (one call per channel per month), calls each with the matching extractor.

## halt-and-articulate

**User correction reversed a prior wrong reading.** Sprint 023's "AV refuses VIX" was Alpha-Vantage refusing intraday VIX on the equity endpoint. That reading became "AV has no VIX" in later sprints — a widening of the fact into a fiction. The narrow truth: no intraday VIX exists on Alpha-Vantage; daily VIX exists via INDEX_DATA and works fine. Filed to Decisions with the correction.

**Daily-to-15-min alignment is one line of dispatch, not a new operator.** `polars.join_asof(strategy="backward")` on `known_at` already implements the forward-fill semantic the daily-to-intraday alignment needs: every 15-min RTH bar picks the most-recent daily bar whose `known_at ≤ grid_ts`. Existing align path unchanged; only the per-channel loader dispatch is new.

**Manifest schema drift.** The pre-Sprint-038 manifest had no `tool` field per channel. Sprint 038 requires it for future channels that use non-intraday endpoints. Default falls back to `TIME_SERIES_INTRADAY` for back-compat; every new channel added from here on names its tool explicitly.

## signal contract

### Emits

No new emit sites. `INGESTION_CALL_ISSUED` fires with `tool="INDEX_DATA"` on VIX pulls. `RAW_OBSERVATION_WRITTEN` payload's `rows_written` reports `len(data)` = 9,246 for the full-history VIX response, `value_time`/`known_at` at the latest date's 16:00 EST/21:00 UTC. `ALIGNMENT_RUN_STARTED` and `ALIGNMENT_ROW_EMITTED` unchanged.

### Invariants

- INDEX_DATA cache-key is `sha256(tool="INDEX_DATA", channel, symbol, params={"symbol", "interval", "datatype"})`. No `month` in the params — one full-history call covers everything.
- `known_at` for a daily VIX close on date D is D at 21:01 UTC (16:00 fixed-EST + 1 minute). Every 15-min RTH bar on day D+1 sees D's close via backward-fill; day D's own morning bars see day D-1's close because day D's daily bar hasn't printed by then.
- `run_alignment` raises `ValueError("unsupported tool ...")` on any manifest channel whose `tool` is neither `INDEX_DATA` nor `TIME_SERIES_INTRADAY`.

## artifact contract

### Files modified

- `src/price_space_llm/ingestion/alphavantage.py` — added `alphavantage_index_extract_metadata`; exported it via `__all__`.
- `src/price_space_llm/alignment/join.py` — added `load_index_daily_bars`; refactored `run_alignment` per-channel loop to dispatch on `c.get("tool", "TIME_SERIES_INTRADAY")`.
- `src/price_space_llm/alignment/__init__.py` — exported `load_index_daily_bars`.
- `scripts/ingest.py` — `_load_accepted_channels` returns `tool` per channel; `main` splits channels by tool, iterates INDEX_DATA channels once and TIME_SERIES_INTRADAY channels per month; imports the new extractor.
- `tests/test_alphavantage.py` — added 4 tests covering the INDEX_DATA extractor (correct 16-EST timestamping, empty-data guard, missing-data-key guard, missing-date guard).
- `tests/test_alignment.py` — added 4 tests (`load_index_daily_bars` known_at stamping, empty-data guard, `run_alignment` INDEX_DATA + TIME_SERIES_INTRADAY dispatch with VIX forward-fill assertion, unsupported-tool rejection).

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 268 → 276 (+8: 4 extractor, 4 alignment).

### Live smoke

Pull VIX daily + SPY intraday for June–August 2024:

```
uv run python scripts/ingest.py \
    --manifest scratchpad/sprint038-manifest.json \
    --start-month 2024-06 --end-month 2024-08 \
    --fetcher alphavantage
```

Exit 0. `ingest: 4 ok, 0 failed; months=2024-06..2024-08`. Four calls = 1 VIX INDEX_DATA (fresh, 9,246 rows across 1990-01-02 through 2026-08-12) + 3 SPY TIME_SERIES_INTRADAY (all cache-hit from prior sprints). VIX cache landed at `data/raw/mcp_av/INDEX_DATA/d7deffb5....json` with `.meta.json` sidecar per Sprint 036 discipline.

Align + features + tokenize:

```
uv run python scripts/align.py --manifest ... --start-month 2024-06 --end-month 2024-08
# align: 1690 rows in 0.10s; missing_fractions=[target=0.000, market_context=0.000]

uv run python scripts/features.py --aligned data/aligned/align-2024-06-2024-08-....parquet
# features: 12995 emitted, 525 failed in 0.29s

uv run python scripts/bucketize.py --features ... --training-start 2024-06-03 --training-end 2024-08-30
# tokenize: 1689 tokens in 0.08s; n_buckets=32 channels=2
```

Verification of the causality invariant:

```
2024-06-03 14:45 UTC  |  SPY close 514.81  |  VIX close 12.92  (VIX known_at 2024-05-31 21:01 UTC)
2024-06-03 15:00 UTC  |  SPY close 514.08  |  VIX close 12.92  (Friday's close, correctly held)
2024-06-03 15:15 UTC  |  SPY close 514.36  |  VIX close 12.92
```

VIX takes 61 distinct values across the three months = one distinct value per trading day. Backward-fill semantics correct by direct observation.

---

## observation contract

Required (`pass_kind: functional`). Live smoke exit 0 across ingest + align + features + tokenize on real Alpha-Vantage VIX data. Emit surface unchanged. Causality invariant proven at two altitudes: unit test (`test_run_alignment_dispatches_index_data_channel` asserts every non-null VIX value on 2024-06-03 grid rows equals the 2024-05-31 close 12.92) and read-back on the full aligned parquet.

Extractor invariant proven by `test_index_extract_metadata_uses_16_est_close`: for a response with latest date 2024-06-28, `value_time` = 2024-06-28 21:00 UTC and `known_at` = value_time + 60s.

---

## honest audit

**What landed.** Real VIX signal from a real endpoint. Alignment dispatches by per-channel tool. Storage discipline from Sprint 036 held on the new endpoint — cache index, sidecar, freshness policy all inherited without touching code, because `IngestionClient.call` is tool-generic.

**What did not land.** The `data/manifests/channel_coverage.json` at the project root still lists VIX with no `tool` field (defaulting to TIME_SERIES_INTRADAY on read) and USO as dropped. Sprint 038 smokes with a scratchpad manifest that adds `tool: INDEX_DATA` on VIX. Sprint 039 (operational pull) will materialise the corrected project manifest with VIX under INDEX_DATA. Not blocking.

**What surfaced during execution.** The 525 feature failures on the SPY+VIX chained smoke (up from 147 on SPY+USO) are the rolling-window features on VIX daily. VIX close is a step function — long constant runs — so `rolling_std_20` reports zero for many bars, which trips the "std is zero → z-score undefined" guard. Real behavior of a real signal; not a bug. When Sprint 039 lands full-history VIX in an actual training run, the trainer will handle these nulls the same way it handles any other missing feature.

**What did not need change.** `polars.join_asof(strategy="backward")` handled daily-to-15-min forward-fill without a code line. `IngestionClient` accepted `tool="INDEX_DATA"` on the first try — its signature was already tool-generic from Sprint 019. The cost of the Sprint 036 storage refactor pays off here: adding a new endpoint required zero storage-layer work.

---

## notes

**Why one INDEX_DATA call, not per-month.** Alpha-Vantage's INDEX_DATA does not accept a `month` parameter; one call returns the full history. That means the cache-key stays constant across pulls; the freshness policy (immutable for INDEX_DATA per Sprint 036 defaults — treated the same as TIME_SERIES_INTRADAY historical bars) means the second pull is a cache-hit forever. Cheap.

**Why `known_at = date + 16:00 EST + 1 minute` and not `+ 5 hours`.** The VIX daily close prints promptly at 16:00 EST — CBOE publishes the settlement value within seconds. The 1-minute buffer is a rounding convention matching the intraday `known_at` convention (bar close + 1 minute). The 2-hour buffer used for HISTORICAL_OPTIONS covers the options-chain publication delay, which is different.

**FRESHNESS_POLICY silently covers INDEX_DATA.** `FRESHNESS_POLICY` in `cache.py` has no explicit entry for INDEX_DATA. The default (`math.inf`) applies. Historical daily bars are immutable, so this is correct. Named here so a future Reviewer doesn't ask.

**Manifest `tool` field is the schema change.** Everywhere else the manifest is unchanged. Old manifests without `tool` still work; new manifests should name `tool` per channel.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (VIX via INDEX_DATA + daily-to-15-min forward-fill dispatch).
- [x] Files under hard rule 6 (3 code + 1 script + 2 test files).
- [x] Signal contract: no new tags; existing tags carry accurate `tool` field.
- [x] Observation contract (functional-band): live smoke + unit invariants across two altitudes.
- [x] Determinism budget declared (bit-deterministic — same cache-key, same content).
- [x] Prior wrong reading corrected honestly (Sprint 023's "AV refuses VIX" narrowed to "AV refuses intraday VIX").

---

## close (2026-08-13)

Landed. Real VIX daily bars from Alpha-Vantage's INDEX_DATA endpoint, 9,246 rows since 1990, forward-fill onto the 15-min RTH grid via the existing as-of join. Test count 268 → 276. Four tools green. Sprint 039 (operational pull + full pipeline over the tech-arch training and test windows) proceeds with a two-channel accepted manifest.
