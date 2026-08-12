# Sprint 027 — multi-month ingestion (`--start-month --end-month`)

---

```yaml
---
id: 027
status: closed
phase: 1
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

---

## scope

Extend `scripts/ingest.py` with `--start-month YYYY-MM --end-month YYYY-MM`. Iterate months in the range; call `IngestionClient.call()` per (channel, month). Cache-hits and rate-limit paths unchanged from Sprint 024. Live smoke pulls July + August 2024 on top of Sprint 024's cached June; total budget 4 fresh fetches.

`--end-month` defaults to `--start-month` for backward compatibility with single-month invocations.

---

## signal contract

### Emits

Same tags as Sprint 024. Volume scales with (N_months × N_channels):
- `INGESTION_CALL_ISSUED` — one per fresh fetch.
- `INGESTION_CALL_CACHED` — one per cache-hit.
- `RAW_OBSERVATION_WRITTEN` — one per fresh fetch.

### Invariants

- Month order is chronological (Jan → Dec, then Jan+1); wrap-around handled in `_month_range`.
- `end_month < start_month` raises before any fetcher call.
- `run_id` reads `ingest-{fetcher}-{start_month}-{seed}` when start == end; `ingest-{fetcher}-{start_month}_{end_month}-{seed}` otherwise. Sink truncation per Sprint 024's fix.

---

## artifact contract

### Files modified

- `scripts/ingest.py` — `--month` replaced by `--start-month` + `--end-month`; `_month_range` helper; nested loop; run_id + config_hash use the span tag.
- `tests/test_ingest_cli.py` — every `--month` arg → `--start-month`; three new tests (`test_cli_month_range_produces_call_per_month_per_channel`, `test_cli_month_range_rejects_backwards_range`, `test_cli_single_month_run_id_omits_end_suffix`).

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 114 → 117 (+3).

### Live smoke

```
uv run python scripts/ingest.py --start-month 2024-06 --end-month 2024-08 --fetcher alphavantage
```

Expected (verified): exit 0. Trace: 1 SESSION_INIT + 2 INGESTION_CALL_CACHED (June × 2 channels) + 4 INGESTION_CALL_ISSUED (July + Aug × 2 channels) + 4 RAW_OBSERVATION_WRITTEN + 1 SESSION_COMPLETE = 12 lines. Six fresh cache files added to `data/raw/mcp_av/TIME_SERIES_INTRADAY/` — total is now four (June SPY, June USO, July SPY, July USO, Aug SPY, Aug USO).

---

## observation contract

Live smoke exit 0. Emit counts match the (N_months × N_channels) formula: 3 months × 2 channels = 6 total calls; June was already cached; 4 fresh fetches for July and August.

---

## notes

**Free-tier budget accounting.** Alpha-Vantage free tier: 25 requests/day. Sprint 020's probe used 15; Sprint 023's re-smoke used 2; Sprint 024's first ingest used 2; Sprint 027's smoke uses 4 fresh. Cumulative today: 23 of 25. One request left; if I ran another live sprint I'd hit the cap and see the rate-limit path fire.

**Retry-with-backoff still not added.** Same deferral as Sprint 021. When the first live 429 hits (probably Sprint 028 or later if the day's budget rolls), the retry sprint opens.

---

## close (2026-08-11)

Landed. `_month_range` iterates YYYY-MM strings with December wrap-around. Nested loop calls `client.call` per (channel, month). Live smoke exit 0, honest 12-line trace, 4 new cache files.
