# Sprint 024 — refactor IngestionClient API + wire live to Alpha-Vantage

---

```yaml
---
id: 024
status: closed
phase: 1
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

---

## scope

Three concept changes bundled because they only work together:

1. **Refactor `IngestionClient.call()`** — replace three kwargs (`value_time`, `known_at`, `rows_written`) with one callback (`extract_metadata: Callable[[dict], ObservationMetadata]`). The caller does not know observation-time or row-count until the vendor response returns; the current API forced the mock case at the expense of the real case.
2. **Author `make_alphavantage_raw_fetcher(api_key, client=None) -> RawFetcher`** in `alphavantage.py`. Signature: `(tool, params) -> dict[str, Any]` (raw JSON, no probe-side normalisation). Distinct from `make_alphavantage_fetcher` which returns probe-shaped `FetchResult`.
3. **Author `scripts/ingest.py`** — CLI that wraps `IngestionClient` around the raw fetcher, pulls one month of 15-min bars for each accepted channel from `data/manifests/channel_coverage.json`, emits the five ingest-category tags for real, writes a JSONL trace and a JSON cache. Live smoke against Alpha-Vantage; the H9 hypothesis (first-live-contact surfaces at least one gap) gets its second data point.

Bundled because (2) needs (1)'s API and (3) needs both.

---

## prerequisites

- Sprint 023 closed (honest probe → real accepted channels in the manifest).
- v0.3 vocabulary locked (five ingest-category tags + `CHANNEL_FETCH_FAILED`).

---

## context_files

- `src/price_space_llm/ingestion/client.py` — the current `.call()` API to refactor.
- `src/price_space_llm/ingestion/alphavantage.py` — the probe-shape fetcher; adds `make_alphavantage_raw_fetcher` beside it.
- `data/manifests/channel_coverage.json` — the honest Sprint 023 manifest.
- `tests/test_ingestion_client.py` — 11 tests to update against the new API.

---

## signal contract

### Emits

- `INGESTION_CALL_ISSUED` per successful primary or fallback fetch (real emit for the first time).
- `INGESTION_CALL_CACHED` per second-and-later call to the same `(tool, channel, symbol, params)`.
- `SOURCE_FALLBACK_TRIGGERED` when primary raises and fallback is configured.
- `RAW_OBSERVATION_WRITTEN` per successful fetch, payload built from `extract_metadata`.
- `REVISION_LANDED` when a re-fetch returns bytes that differ from the cached prior.

### Consumes

- `configs/channels/v1.json`.
- `data/manifests/channel_coverage.json` — script reads the accepted subset.
- `ALPHAVANTAGE_API_KEY` env var.
- Alpha-Vantage HTTP API.

### Invariants

- No fabricated payload values. `extract_metadata` returns real observation-time + row-count from the response; if it raises, `IngestionCallFailed` propagates and no `RAW_OBSERVATION_WRITTEN` fires.
- The refactored `.call()` API is the only shape; the old kwargs shape is removed, not deprecated.
- All 82 existing tests continue to pass (11 in `test_ingestion_client.py` rewritten for the new API).
- Live smoke calls Alpha-Vantage at most 2 times (one month × two accepted channels — SPY and USO); free tier has 25 req/day, budget respected.

---

## artifact contract

### Files created

- `scripts/ingest.py` — the ingestion CLI (~150 lines).
- `tests/test_ingest_cli.py` — one subprocess test with a mock fetcher stubbed via env-var switch or module import.

### Files modified

- `src/price_space_llm/ingestion/client.py` — `.call()` signature change; internal flow unchanged.
- `src/price_space_llm/ingestion/alphavantage.py` — add `make_alphavantage_raw_fetcher`, `alphavantage_extract_metadata` helper for the intraday-monthly response shape.
- `tests/test_ingestion_client.py` — 11 tests updated to pass an `extract_metadata` callback.
- `pyproject.toml` — version bump 0.11.0 → 0.12.0.

### Content assertions

- `client.py::IngestionClient.call` signature no longer has `value_time`, `known_at`, `rows_written` kwargs; has `extract_metadata` kwarg.
- `alphavantage.py::make_alphavantage_raw_fetcher` returns a `RawFetcher` (Callable matching `(tool, params) -> dict`).
- `alphavantage.py::alphavantage_extract_metadata(response) -> ObservationMetadata` reads `"Time Series (15min)"`, sets `value_time = max(timestamp_keys)` in UTC, sets `known_at = value_time + timedelta(minutes=1)` for historical bars, sets `rows_written = len(series)`.
- `scripts/ingest.py` reads the manifest, iterates accepted channels, calls `client.call()` once per (channel, month), prints a stderr summary, exits 0 on all-successful.

### Command exit codes

- `uv run ruff check src tests scripts` exit 0.
- `uv run ruff format --check src tests scripts` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -q` exit 0; test count ≥ 84 (82 + 2 new; 11 rewritten).

### Live smoke

```
export ALPHAVANTAGE_API_KEY=$(grep ALPHAVANTAGE_API_KEY .env | cut -d= -f2)
uv run python scripts/ingest.py --manifest data/manifests/channel_coverage.json --month 2024-06
```

Expected: exit 0. Two fetches (SPY, USO). Trace at `logs/ingest-{run_id}/signals.jsonl` — SESSION_INIT + 2×INGESTION_CALL_ISSUED + 2×RAW_OBSERVATION_WRITTEN + SESSION_COMPLETE = 6 lines. Cache files at `data/raw/mcp_av/TIME_SERIES_INTRADAY/{key}.json` — two files, each holding a real Alpha-Vantage response.

Re-run the same command: exit 0. Trace = SESSION_INIT + 2×INGESTION_CALL_CACHED + SESSION_COMPLETE = 4 lines. No new fetches (both channels cache-hit).

---

## observation contract

Required (`pass_kind: functional`).

The live smoke's trace should contain, in order per (channel, month) request:

- First-run: `INGESTION_CALL_ISSUED` (source=mcp_av, real params_hash), then `RAW_OBSERVATION_WRITTEN` (real value_time, real rows_written matching the vendor's bar count for the month).
- Second-run: `INGESTION_CALL_CACHED` only.

Every field in every emitted payload comes from either a config value (channel/symbol/source) or the vendor response (value_time, rows_written) or the wall-clock (known_at as `value_time + 1min` per the historical-bar simplification). Zero fabricated defaults.

---

## done criteria

Refactor lands. Raw fetcher lands. Script wraps them. Live smoke against Alpha-Vantage produces an honest trace and real cache files. Second-run is a full cache-hit path with zero fetches.

---

## notes

**`known_at` simplification for historical bars.** Real streaming ingestion would carry the vendor's "released_at" or a wall-clock stamp at receipt. For historical monthly pulls, the bars are known to have existed since ~1min after their close. Sprint 024 uses `known_at = value_time + timedelta(minutes=1)`. Documented in the extractor's docstring; refined when a real streaming sprint lands.

**`value_time` semantics for a batch.** Response holds ~500 bars for a full month; `value_time` on the single `RAW_OBSERVATION_WRITTEN` event is the newest bar's timestamp (batch high-watermark). `rows_written` carries the batch size. Downstream readers who need per-bar granularity would replay the cached JSON; the trace records the batch, not the per-bar detail.

**Callback vs split-method for the API refactor.** Two shapes considered: (a) `.call(..., extract_metadata: Callable)` — single-call, one emit sequence, harder to forget the record step. (b) `.fetch()` + `.record()` split — two methods, matches the runtime steps more literally. Sprint 024 uses (a) because it makes the API less footgun-prone and the metadata-extraction responsibility explicit at construction. If (b) becomes desirable when a caller needs to defer the record (e.g., streaming ingestion where value_time is only known after downstream processing), the split lands in a future sprint.

**Retry-with-backoff still not added.** Same reasoning as Sprint 021: real 429 behavior needs a real 429 sprint to design against. Alpha-Vantage's free-tier limit (25/day) is easy to hit; when we do, that sprint opens.

**Free-tier budget: 25 req/day.** Sprint 024's live smoke uses 2 calls. Prior Sprint 020 live smoke used 15 (probe × 3 channels × 5 dates). Cumulative daily: 17. Well under 25. If iterative debugging pushes past the budget, wait a day or upgrade tier.

---

## plan-mode review checklist

- [x] Scope one paragraph, three concepts. Bundled per notes; halt-and-articulate: the refactor + new fetcher + wire are inseparable — refactor without fetcher leaves the API without a live user; fetcher without refactor forces the caller to fabricate metadata kwargs; wire without either is impossible. Sprint card names the bundle.
- [x] Signal contract cites v0.3 tags with real emit call sites.
- [x] Observation contract present (functional-band); live smoke command included; second-run cache-hit path spelled out.
- [x] Determinism budget declared (statistically-deterministic — live network).
- [x] Free-tier budget calculated (2 calls of 25/day).

---

*Sprint 024. First live emit of the five ingest-category tags from real code, not test-time mocks. Second data point for H9 (first-live-contact surfaces gaps).*

---

## close (2026-08-11)

Landed. `.call()` API refactored (three kwargs → one callback). `make_alphavantage_raw_fetcher` + `alphavantage_extract_metadata` added. `scripts/ingest.py` iterates accepted channels from the manifest and calls `IngestionClient.call(...)` per (channel, month).

Live smoke against Alpha-Vantage for `--month 2024-06`:
- First run: exit 0. Two live fetches (SPY + USO). Six-line trace: SESSION_INIT + 2× INGESTION_CALL_ISSUED + 2× RAW_OBSERVATION_WRITTEN + SESSION_COMPLETE. Real payloads: SPY 1235 rows / value_time 2024-06-29T01:00:00+00:00; USO 1203 rows / same latest bar. Two cache files written to `data/raw/mcp_av/TIME_SERIES_INTRADAY/{key}.json` (~160KB each).
- Second run: exit 0. Zero live fetches. Four-line trace: SESSION_INIT + 2× INGESTION_CALL_CACHED + SESSION_COMPLETE. Sink truncation kept the trace clean (only current session).

Test count 82 → 94 (12 new: 7 raw-fetcher/extractor unit tests + 5 CLI subprocess tests). Four tools green.

**Two H9 findings surfaced, both filed:**

1. `extended_hours=true` is Alpha-Vantage's TIME_SERIES_INTRADAY default; the response includes pre-market + regular + after-hours = ~1200-1600 bars per month for SPY. The probe's `EXPECTED_BARS_PER_TRADING_MONTH = 21 * 26 = 546` denominator assumes regular-hours only. On over-count, `missing_fraction` clamps to 0 (harmless). On under-count of a genuine regular-hours response (e.g. explicit `extended_hours=false`), the same denominator would report `~0.08` missing and drop a legitimate channel. Filed to drift-watchlist: refine denominator when the ingestion sprint that first calls with `extended_hours=false` opens.

2. `value_time = 2024-06-29T01:00:00+00:00 UTC` corresponds to 2024-06-28 21:00 EDT, not 2024-06-28 20:00 EDT (the actual close). Off by one hour because the fixed-offset EST simplification in `alphavantage.py` doesn't handle DST. Known deferred issue documented at the module docstring; not blocking Sprint 024.

