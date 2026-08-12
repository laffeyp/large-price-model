# Sprint 023 — rip out fill-value lies, wire CHANNEL_FETCH_FAILED

---

```yaml
---
id: 023
status: closed
phase: 1
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

---

## scope

Delete the two paths in `scripts/probe_channels.py` and `src/price_space_llm/ingestion/alphavantage.py` that emitted fabricated observations when the fetcher had no real data. Wire `probe_channel` in `src/price_space_llm/ingestion/probe.py` to catch fetcher exceptions and emit v0.3's `CHANNEL_FETCH_FAILED` instead. Add three tests covering: single-date failure with per-date recovery, all-dates failure with no `CHANNEL_COVERAGE_ASSESSED` emit, error message truncation at 1000 chars.

The two lie paths, verbatim from the failure entries:

- `scripts/probe_channels.py:_error_shim` fabricated `actual_frequency="15min"`, `earliest_timestamp="1970-01-01T00:00:00+00:00"`, `latest_timestamp="1970-01-01T00:00:00+00:00"`, `revision_behavior="immutable"`, `missing_fraction=1.0` and returned it as a `FetchResult`. `_error_shim` deleted; the CLI passes the raw fetcher through to the probe.
- `alphavantage.py:_extract_fetch_result` empty-series branch returned the same shape of fill values. Deleted; raises `AlphaVantageResponseError("empty Time Series in vendor response — no observations to serialise")` instead.

---

## prerequisites

- Sprint 022 closed (v0.3 vocabulary locks `CHANNEL_FETCH_FAILED`).

---

## signal contract

### Emits

- Existing tags unchanged: `SESSION_INIT`, `CHANNEL_PROBED`, `CHANNEL_REJECTED`, `CHANNEL_COVERAGE_ASSESSED`, `SESSION_COMPLETE`.
- New: `CHANNEL_FETCH_FAILED` per (channel, symbol, sample_date) whose fetcher raised.

### Invariants

- No fabricated field values. Every payload matches vocabulary types with values the running code actually observed.
- If any sample-date fetch for a channel succeeds, `CHANNEL_COVERAGE_ASSESSED` emits with aggregates over the successful subset.
- If every sample-date fetch fails, no `CHANNEL_COVERAGE_ASSESSED` emits (the vocabulary requires `earliest_timestamp`; none exists).
- `CHANNEL_FETCH_FAILED.error_message` is capped at 1000 characters so a verbose vendor can't flood the trace.

---

## artifact contract

### Files modified

- `src/price_space_llm/ingestion/probe.py` — try/except around each fetcher call; emit `CHANNEL_FETCH_FAILED` on exception; `ChannelCoverage` timestamps typed `str | None`; verdict `"dropped"` with `reason="all_fetches_failed"` on the zero-observation case.
- `src/price_space_llm/ingestion/alphavantage.py` — empty-series branch raises `AlphaVantageResponseError` instead of returning fill values; `_extract_fetch_result` docstring names the Sprint 023 correction.
- `scripts/probe_channels.py` — `_error_shim` deleted; `_resolve_fetcher("alphavantage")` returns `make_alphavantage_fetcher(key)` directly; module docstring updated.
- `tests/test_alphavantage.py` — `test_fetcher_marks_empty_series_as_fully_missing` → `test_fetcher_raises_on_empty_series`.
- `tests/test_probe.py` — three new tests: `test_probe_channel_emits_channel_fetch_failed_on_exception`, `test_probe_channel_all_fetches_failed_skips_coverage_assessed`, `test_probe_channel_truncates_long_error_message`.

### Content assertions

- `grep -n "1970-01-01" src/ scripts/` returns nothing.
- `grep -n "_error_shim" scripts/` returns nothing.
- `grep -n "CHANNEL_FETCH_FAILED" src/` returns exactly one emit site in `probe.py`.

### Command exit codes

- `uv run ruff check src tests scripts` exit 0.
- `uv run ruff format --check src tests scripts` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -q` exit 0; test count 77 → 80 (2 tests renamed/modified, 3 new).

### Live smoke

```
export ALPHAVANTAGE_API_KEY=$(grep ALPHAVANTAGE_API_KEY .env | cut -d= -f2)
rm -f logs/probe-alphavantage-0000000000000000/signals.jsonl
uv run python scripts/probe_channels.py configs/channels/v1.json --fetcher alphavantage
```

Expected: exit 2. Trace 19 lines: 1 SESSION_INIT, 10 CHANNEL_PROBED (SPY×5 + USO×5), 2 CHANNEL_COVERAGE_ASSESSED (SPY + USO, both `verdict=accepted`), 5 CHANNEL_FETCH_FAILED (VIX×5), 1 SESSION_COMPLETE. Manifest: `market_context__VIX` carries `verdict=dropped, reason=all_fetches_failed, earliest_timestamp=null`. Zero fabricated fields in the trace.

---

## observation contract

Required. Live smoke verified 19-line trace with the tag counts above. Every `CHANNEL_FETCH_FAILED.error_message` payload starts with "Invalid API call." (Alpha-Vantage's actual error string for unsupported symbols). Every `CHANNEL_PROBED` for SPY and USO carries real UTC timestamps parsed from the vendor response. Zero epoch-zero markers.

---

## done criteria

Lies removed. `CHANNEL_FETCH_FAILED` fires on real vendor errors. Live smoke produces an honest trace. Eighty tests pass. Every tool green.

---

## notes

**Why raise from `_extract_fetch_result` rather than returning `None`.** The caller pattern is `result = fetcher(...)` immediately followed by a series of dict accesses (`result["actual_frequency"]` etc.). Returning `None` would require every caller to check `if result is None: ...` — more boilerplate, easy to forget. Raising forces the exception up to `probe_channel`'s try/except where the handling lives.

**Why cap error_message at 1000 chars.** Alpha-Vantage error strings are typically short (~100 chars). A malicious or misconfigured vendor could return a 100KB error body; unbounded trace payloads bloat the JSONL and slow downstream readers. 1000 chars keeps every real vendor error verbatim while capping the pathological case.

**Zero-observation channels omit the closer.** The pairing constraint on `CHANNEL_COVERAGE_ASSESSED` in v0.3 is not yet formalised in Layer 4; a future sprint may add "channel with any CHANNEL_PROBED must have exactly one CHANNEL_COVERAGE_ASSESSED." For now, the reader-side convention is: if a channel's signals include only CHANNEL_FETCH_FAILED entries, it was unassessable.

**JSONL append hygiene bug still open.** Same as noted at Sprint 020 close. Not blocking Sprint 023; filed in `## Drift watchlist`. A signals-hygiene sprint truncates on SESSION_INIT.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (rip lies, wire tag).
- [x] Three code files modified + two test files modified. Above the ≤2 files ceiling; halt-and-articulate: the three code changes are inseparable (removing the shim requires the probe to catch; the empty-series raise pairs with the probe catch; the CLI's shim removal is the surface change). Bundled per this note.
- [x] Signal contract cites v0.3 tags.
- [x] Observation contract present (functional-band); live smoke command included.
- [x] Determinism budget declared (statistically-deterministic — live network).

---

## close (2026-08-11)

Ripped. `_error_shim` deleted. `_extract_fetch_result` empty-series raises. `probe_channel` catches fetcher exceptions and emits `CHANNEL_FETCH_FAILED`. Live smoke exit 2, 19-line honest trace, zero fill values. Test count 77 → 80. Four tools green.
