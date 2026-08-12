# Sprint 025 — alignment pipeline (Polars join_asof on `known_at`)

---

```yaml
---
id: 025
status: closed
phase: 1
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Author `src/price_space_llm/alignment/{join.py, __init__.py}` — the tech-arch §4.3 join_asof pipeline that takes cached raw Alpha-Vantage responses, builds a fixed 15-min UTC RTH grid over a month, and joins each channel's bars into the grid with `strategy="backward"`. This is the primary invariant of the whole system per tech-arch §17 — features at time T can only see data known at or before T.

Adopt `polars>=1.43` and `pyarrow>=25` in the same commit. Ship `scripts/align.py` that closes the loop from Phase 0 (probe) → Sprint 024 (ingest) → Sprint 025 (align). Live smoke against the SPY + USO bars Sprint 024 pulled for June 2024; expect zero `AS_OF_JOIN_MISS` (both channels have full-month data) and 520 grid rows (20 weekdays × 26 RTH bars).

---

## prerequisites

- Sprint 024 closed (real cached bars exist in `data/raw/mcp_av/TIME_SERIES_INTRADAY/`).
- v0.3 vocabulary locked (`ALIGNMENT_RUN_STARTED`, `ALIGNMENT_ROW_EMITTED`, `AS_OF_JOIN_MISS`, `ALIGNMENT_RUN_COMPLETED` all defined; `run_kind` enum includes `align`).

---

## signal contract

### Emits

- `SESSION_INIT` with `run_kind=align` (first live emit at this run_kind).
- `ALIGNMENT_RUN_STARTED` at open with `run_id`, `date_range_start`, `date_range_end`, deduped `channels` list, `target_symbol`.
- `ALIGNMENT_ROW_EMITTED` ambient — one per grid bar with `timestamp` and `missing_channels_count`.
- `AS_OF_JOIN_MISS` incident — one per (channel, grid_ts) where the join found no prior observation, reason `no_history_yet`.
- `ALIGNMENT_RUN_COMPLETED` summary with `total_rows`, `missing_fractions_per_channel`, `elapsed_seconds`, `output_path`.
- `SESSION_COMPLETE`.

### Invariants

- `join_asof(strategy="backward")` guarantees the alignment invariant: at grid time T, the joined column carries the latest observation whose `known_at <= T`. Anything known after T is invisible. Look-ahead leakage is impossible.
- Cache bars and grid bars use the same fixed EST offset (see drift-watchlist); wrong-by-one-hour in DST months but internally consistent, so the join semantics are correct — only emitted timestamps carry the +1h bias.
- Sink truncation from Sprint 024 keeps each run's trace independent even with the same `run_id`.

---

## artifact contract

### Files created

- `src/price_space_llm/alignment/__init__.py`.
- `src/price_space_llm/alignment/join.py` (~230 lines).
- `scripts/align.py` (~110 lines).
- `tests/test_alignment.py` (11 tests: 4 grid, 2 load, 3 align, 2 end-to-end).

### Files modified

- `pyproject.toml` — `dependencies` gains `polars>=1.43.2` and `pyarrow>=25.0.1`; version bump `0.12 → 0.13`.

### Command exit codes

- `uv sync --dev` exit 0.
- `uv run ruff check src tests scripts` exit 0.
- `uv run ruff format --check src tests scripts` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -q` exit 0; test count 94 → 105 (+11).
- `uv build` clean.

### Live smoke

```
uv run python scripts/align.py --month 2024-06
```

Expected: exit 0. Trace at `logs/align-2024-06-0000000000000000/signals.jsonl` — 524 lines (SESSION_INIT + ALIGNMENT_RUN_STARTED + 520 × ALIGNMENT_ROW_EMITTED + ALIGNMENT_RUN_COMPLETED + SESSION_COMPLETE). Parquet at `data/aligned/align-2024-06-0000000000000000.parquet` — 520 rows × 5 columns (`grid_ts`, per-channel `close` and `known_at`). Both channels `missing_fraction=0.000`.

---

## observation contract

Required (`pass_kind: functional`). Live smoke ran clean. Six categories walked in the Rubber Duck Pass.

---

## done criteria

Alignment lands. Live smoke produces a real parquet from real cached bars. Backward-join causality gate verified by `test_align_channels_backward_join_takes_latest_prior_bar` (grid at 15:00 sees the bar known at 14:31, not the bar known at 15:01).

---

## notes

**Emitter buffer overflow surfaced during test writing.** `StrictSignalEmitter(max_buffer=500)` default drops old entries when the deque overflows. A month of alignment emits ~1000+ signals (520 ROW_EMITTED plus per-miss). `test_run_alignment_writes_parquet_and_emits_summary` initially failed with `tags[0] == "ALIGNMENT_ROW_EMITTED"` instead of `ALIGNMENT_RUN_STARTED` because the STARTED emit had been evicted. Fix: test helper bumps buffer to 8192. Production `scripts/align.py` uses the default 500 because it inspects the JSONL sink, not the in-memory buffer.

**Naive weekday calendar.** June 2024 has 20 weekdays under Mon-Fri filtering; the real US market calendar has 19 (Juneteenth June 19 closed). Grid holds 26 bars for Juneteenth; they backward-fill from June 18's last bar (`known_at = 2024-06-19T01:01:00 UTC`, `close = 534.11`). Downstream feature computation on a market-closed day will see stale prices. Filed on drift-watchlist under the existing `pandas_market_calendars` deferral.

**Fixed EST offset compounds two known biases.** June 2024 is DST (real offset -4), but the code uses -5 for consistency with `alphavantage.py`. Both the bars and the grid live on the wrong clock in the same way, so the join is correct. Emitted `timestamp` payloads run one hour behind wall-clock reality. Grid's last bar is `2024-06-28T21:00:00 UTC`, which under -5 corresponds to 16:00 EST but is actually 17:00 EDT — real-world close was 20:00 EDT / 00:00 UTC. Same drift-watchlist entry.

**Parquet as the alignment output boundary.** First use of pyarrow-backed Polars in the pipeline. The parquet at `data/aligned/{run_id}.parquet` is what the feature-computation sprint reads. Wide format (one row per grid_ts, one column-set per channel) matches tech-arch §4.3 exactly.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (alignment).
- [x] Two new module files (alignment/) + one script + one test file + one dep change. Above the ≤2 files ceiling for code; halt-and-articulate: the alignment module + script + tests deliver one conceptual unit and splitting fragments the smoke path.
- [x] Signal contract cites v0.3 tags.
- [x] Observation contract present (functional-band); live smoke command and expected trace counts included.
- [x] Determinism budget declared (bit-deterministic — no wall-clock, no live network; the join_asof is deterministic over identical inputs).

---

## close (2026-08-11)

Landed. `join_asof(strategy="backward")` alignment invariant enforced and tested. Live smoke: exit 0, 520-row parquet, both channels missing_fraction=0, 524-line trace, ~0.04s wall-clock. Signals-drive scoreboard: `align` category (4 tags) all emit from live code. Test count 94 → 105. Four tools green.
